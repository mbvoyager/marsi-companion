"""Small authenticated LAN API for one Marsi household companion."""
from __future__ import annotations

import argparse
import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
import logging
import os
import socket
import threading
from datetime import datetime
from urllib.parse import parse_qs, urlsplit

from .config import ServerConfig, load_env, validate_bind
from .core import Companion, ServiceError, clean_text, ritual, session_name
from .speech import MAX_AUDIO_BYTES, Speech

LOG = logging.getLogger("marsi.local")


class Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 8

    def __init__(self, address, companion):
        self.companion = companion
        self.stopping = threading.Event()
        super().__init__(address, Handler)

    def observance_loop(self):
        while not self.stopping.is_set():
            try:
                app = self.companion
                app.observances.run(datetime.now().astimezone(), app.telemetry.pair(), app.config.observances)
            except Exception as error:
                LOG.error("Observance could not be recorded (%s)", type(error).__name__)
            self.stopping.wait(60)

    def start_observances(self):
        self.scheduler = threading.Thread(target=self.observance_loop, daemon=True)
        self.scheduler.start()

    def server_close(self):
        self.stopping.set()
        if hasattr(self, "scheduler"):
            self.scheduler.join(timeout=2)
        super().server_close()


class Handler(BaseHTTPRequestHandler):
    # Short-lived connections keep the implementation and resource use predictable.
    server_version = "Marsi/0.1"

    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, *args):
        # Conversations and credentials must not appear in access logs.
        pass

    def respond(self, status: int, payload: dict):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def authenticated(self):
        token = self.server.companion.config.token
        provided = self.headers.get("Authorization", "")
        if token and not hmac.compare_digest(provided.encode(), ("Bearer " + token).encode()):
            raise ServiceError("A valid Marsi token is required.", 401)

    def read_body(self, limit=MAX_AUDIO_BYTES) -> bytes:
        if self.headers.get("Transfer-Encoding"):
            raise ServiceError("Chunked requests are not supported.", 400)
        length = self.headers.get("Content-Length")
        if length is None:
            raise ServiceError("Content-Length is required.", 411)
        try:
            count = int(length)
        except ValueError as error:
            raise ValueError("Invalid Content-Length") from error
        if count < 0 or count > limit:
            raise ServiceError("Request body exceeds the allowed size.", 413)
        data = self.rfile.read(count)
        if len(data) != count:
            raise ValueError("Incomplete request body")
        return data

    def read_json(self) -> dict:
        if self.headers.get_content_type() != "application/json":
            raise ServiceError("Use Content-Type: application/json.", 415)
        try:
            payload = json.loads(self.read_body(16384))
        except (UnicodeError, json.JSONDecodeError) as error:
            raise ValueError("Invalid JSON") from error
        if not isinstance(payload, dict):
            raise ValueError("JSON must be an object")
        return payload

    def dispatch(self, method: str):
        try:
            path = urlsplit(self.path).path
            app = self.server.companion
            if method == "GET" and path == "/health":
                return self.respond(200, {"status": "ok", "mode": "demo" if app.config.demo else "local-llm"})
            self.authenticated()
            if method == "GET" and path == "/v1/journal":
                query = parse_qs(urlsplit(self.path).query)
                session = session_name(query.get("session_id", ["pi"])[0])
                return self.respond(200, app.memory.journal(session, before=int(query.get("before", [0])[0]),
                                                          after=int(query.get("after", [0])[0]),
                                                          limit=int(query.get("limit", [80])[0])))
            if method == "POST" and path == "/v1/telemetry":
                app.telemetry.receive_pi(self.read_json().get("readings"))
                return self.respond(200, app.telemetry.pair())
            if method == "GET" and path == "/v1/telemetry":
                return self.respond(200, app.telemetry.pair())
            if method == "GET" and path == "/v1/memory":
                query = parse_qs(urlsplit(self.path).query)
                session = session_name(query.get("session_id", ["pi"])[0])
                with app.exclusive():
                    return self.respond(200, {"session_id": session, "notes": app.memory.notes(session)})
            if (method, path) not in (("POST", "/v1/chat"), ("POST", "/v1/voice"),
                                      ("POST", "/v1/ritual"), ("POST", "/v1/memory"),
                                      ("POST", "/v1/art"), ("POST", "/v1/sermon"), ("POST", "/v1/speak"),
                                      ("DELETE", "/v1/session")):
                raise ServiceError("Unknown endpoint.", 404)
            if path == "/v1/voice":
                session = session_name(self.headers.get("X-Marsi-Session", "pi"))
                if self.headers.get_content_type() != "audio/wav":
                    raise ServiceError("Use Content-Type: audio/wav.", 415)
                recording = self.read_body()
                audio_flag = parse_qs(urlsplit(self.path).query).get("want_audio", ["true"])[0]
                if audio_flag not in ("true", "false"):
                    raise ValueError("want_audio must be true or false")
                wants_audio = audio_flag == "true"
                payload = {}
            else:
                payload = self.read_json()
                session = session_name(payload.get("session_id", "pi"))
                wants_audio = payload.get("want_audio", False)
                if type(wants_audio) is not bool:
                    raise ValueError("want_audio must be a boolean")
            with app.exclusive():
                if path == "/v1/session":
                    app.memory.forget(session)
                    return self.respond(200, {"forgotten": session})
                if path == "/v1/memory":
                    app.memory.add_note(session, clean_text(payload.get("text"), 200))
                    return self.respond(200, {"notes": app.memory.notes(session)})
                if path == "/v1/voice":
                    text = clean_text(app.speech.transcribe(recording))
                    result = app.chat(session, text)
                    result["heard"] = text
                elif path == "/v1/chat":
                    result = app.chat(session, clean_text(payload.get("text")))
                elif path in ("/v1/art", "/v1/sermon"):
                    result = app.inscription(session, path.rsplit("/", 1)[1])
                elif path == "/v1/speak":
                    # Read a persisted observance aloud; no arbitrary text or
                    # generated ASCII is passed to the speech engine.
                    entry_id = payload.get("entry_id")
                    if type(entry_id) is not int:
                        raise ValueError("entry_id must be an integer")
                    with app.memory.connect() as db:
                        row = db.execute("SELECT spoken FROM journal WHERE session=? AND id=? AND kind IN ('morning','sermon','art')", (session, entry_id)).fetchone()
                    if not row or not row[0]:
                        raise ServiceError("Spoken inscription unavailable.", 404)
                    result = {"text": row[0], "source": "playback", "entry_id": entry_id}
                else:
                    result = ritual()
                    app.memory.add_event(session, result)
                if wants_audio:
                    try:
                        result["audio_base64"] = base64.b64encode(app.speech.synthesize(result.get("spoken_text") or result["text"])).decode("ascii")
                    except ServiceError as error:
                        result["voice_error"] = str(error)
                self.respond(200, result)
        except ServiceError as error:
            self.respond(error.status, {"error": str(error)})
        except ValueError as error:
            self.respond(400, {"error": str(error)})
        except (socket.timeout, ConnectionError):
            self.close_connection = True
        except Exception as error:
            LOG.error("Marsi request failed (%s)", type(error).__name__)
            self.respond(500, {"error": "Internal error. Check the server console."})

    def do_GET(self):
        self.dispatch("GET")

    def do_POST(self):
        self.dispatch("POST")

    def do_DELETE(self):
        self.dispatch("DELETE")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", default=".env.server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--demo", action="store_true", help="Rehearse with authored companion replies instead of Qwen")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    if os.name == "posix":
        os.umask(0o077)
    try:
        load_env(args.env)
        config = ServerConfig.from_env(args.demo)
        validate_bind(args.host, config.token)
        app = Companion(config, speech=Speech(config))
        with Server((args.host, args.port), app) as server:
            server.start_observances()
            LOG.info("Marsi listening on %s:%s (%s)", args.host, args.port, "template demo" if args.demo else config.model)
            server.serve_forever()
    except (ValueError, OSError) as error:
        parser.exit(1, f"Cannot start Marsi: {error}\n")
    except KeyboardInterrupt:
        LOG.info("The tiny forge is resting.")


if __name__ == "__main__":
    main()
