"""Small authenticated LAN API for one Marsi household companion."""
from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
import logging
import os
from pathlib import Path
import socket
import sqlite3
import ssl
import threading
from datetime import datetime
from urllib.parse import parse_qs, urlsplit

from .config import ServerConfig, load_env, validate_bind
from .audio_transfer import attach_audio
from .climate import ClimateConfig, ClimateSubscriber
from .core import Companion, ServiceError, clean_text, ritual, session_name
from .speech import MAX_AUDIO_BYTES, Speech, VOICE_CHECK_TEXT

LOG = logging.getLogger("marsi.local")
CLIMATE_HEARTBEAT_SECONDS = 15
WEB_DIRECTORY = Path(__file__).with_name("web")
WEB_ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/web/marsi.css": ("marsi.css", "text/css; charset=utf-8"),
    "/web/marsi.mjs": ("marsi.mjs", "text/javascript; charset=utf-8"),
    "/web/climate.mjs": ("climate.mjs", "text/javascript; charset=utf-8"),
    "/web/vox.mjs": ("vox.mjs", "text/javascript; charset=utf-8"),
    "/web/recorder.js": ("recorder.js", "text/javascript; charset=utf-8"),
}


class Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 8

    def __init__(self, address, companion, *, shared=None, tls=None):
        self.companion = companion
        self.shared, self.tls = shared, tls
        self.stopping = shared.stopping if shared else threading.Event()
        self.climate = shared.climate if shared else None
        self.climate_streams = shared.climate_streams if shared else threading.BoundedSemaphore(8)
        super().__init__(address, Handler)

    def get_request(self):
        connection, address = super().get_request()
        if self.tls is not None:
            try:
                connection = self.tls.wrap_socket(connection, server_side=True, do_handshake_on_connect=False)
            except OSError:
                connection.close()
                raise
        return connection, address

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

    def start_climate(self):
        path = self.companion.config.climate_config
        if path is None:
            return
        try:
            climate = ClimateSubscriber(ClimateConfig.load(path), self.companion.memory)
            climate.start()
        except (OSError, RuntimeError, ValueError, sqlite3.Error) as error:
            LOG.error("Climate logging unavailable: %s", error)
        else:
            self.climate = climate

    def server_close(self):
        if self.shared is None:
            self.stopping.set()
            if self.climate is not None:
                with self.climate.archive.updates:
                    self.climate.archive.updates.notify_all()
                self.climate.close()
            if hasattr(self, "scheduler"):
                self.scheduler.join(timeout=2)
        super().server_close()


class Handler(BaseHTTPRequestHandler):
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

    def web_asset(self, path):
        filename, mime = WEB_ASSETS[path]
        body = (WEB_DIRECTORY / filename).read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy", "microphone=(self), camera=(), geolocation=()")
        self.send_header("Content-Security-Policy", "default-src 'self'; connect-src 'self'; media-src 'self' blob:; "
                         "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
        self.end_headers()
        self.wfile.write(body)

    def stream_climate(self, archive):
        slots = self.server.climate_streams
        if not slots.acquire(blocking=False):
            raise ServiceError("Too many climate streams. Try again shortly.", 503)
        stopping = self.server.stopping
        revision, previous = -1, None
        self.close_connection = True
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            while not stopping.is_set():
                with archive.updates:
                    changed = archive.updates.wait_for(lambda: archive.revision != revision or stopping.is_set(),
                                                       timeout=CLIMATE_HEARTBEAT_SECONDS)
                    revision = archive.revision
                if stopping.is_set():
                    break
                snapshot = archive.current()
                # Freshness can change during a heartbeat even without a new report.
                if changed or snapshot["sensors"] != previous:
                    payload = json.dumps(snapshot, ensure_ascii=False).encode("utf-8")
                    self.wfile.write(b"event: climate\ndata: " + payload + b"\n\n")
                    previous = snapshot["sensors"]
                else:
                    self.wfile.write(b": keepalive\n\n")
        except OSError:
            pass
        except sqlite3.Error as error:
            LOG.error("Climate stream could not read the archive (%s)", type(error).__name__)
        finally:
            slots.release()

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
            if method == "GET" and path in WEB_ASSETS:
                return self.web_asset(path)
            self.authenticated()
            if method == "GET" and path in ("/v1/climate/now", "/v1/climate/history", "/v1/climate/events"):
                if self.server.climate is None:
                    raise ServiceError("The climate archive is unavailable. Check the server configuration.", 503)
                archive = self.server.climate.archive
                if path == "/v1/climate/events":
                    return self.stream_climate(archive)
                if path == "/v1/climate/history":
                    query = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
                    return self.respond(200, archive.history(query.get("range", ["3h"])[0]))
                return self.respond(200, archive.current())
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
                                      ("POST", "/v1/voice-check"),
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
                elif path == "/v1/voice-check":
                    # Diagnose actual speech without Qwen or a saved conversation.
                    text = clean_text(payload.get("text", VOICE_CHECK_TEXT), 300)
                    result = {"text": text, "source": "voice-check"}
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
                        attach_audio(result, app.speech.synthesize(result.get("spoken_text") or result["text"]))
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


def start_web_https(primary: Server, host: str) -> Server | None:
    cert = os.getenv("MARSI_WEB_TLS_CERT", "")
    key = os.getenv("MARSI_WEB_TLS_KEY", "")
    if not cert and not key:
        return None
    try:
        if not cert or not key:
            raise ValueError("Set both MARSI_WEB_TLS_CERT and MARSI_WEB_TLS_KEY")
        port = int(os.getenv("MARSI_WEB_HTTPS_PORT", "8766"))
        if not 1 <= port <= 65535:
            raise ValueError("MARSI_WEB_HTTPS_PORT must be 1..65535")
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(Path(cert).expanduser(), Path(key).expanduser(), password="")
        listener = Server((host, port), primary.companion, shared=primary, tls=context)
    except (OSError, ValueError) as error:
        LOG.warning("Marsi HTTPS unavailable: %s", error)
        return None
    threading.Thread(target=listener.serve_forever, name="marsi-https", daemon=True).start()
    LOG.info("Marsi browser HTTPS listening on %s:%s", host, port)
    return listener


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
            server.start_climate()
            LOG.info("Marsi listening on %s:%s (%s)", args.host, args.port, "template demo" if args.demo else config.model)
            https = start_web_https(server, args.host)
            try:
                server.serve_forever()
            finally:
                if https is not None:
                    https.shutdown()
                    https.server_close()
    except (ValueError, OSError, ServiceError) as error:
        parser.exit(1, f"Cannot start Marsi: {error}\n")
    except KeyboardInterrupt:
        LOG.info("The tiny forge is resting.")


if __name__ == "__main__":
    main()
