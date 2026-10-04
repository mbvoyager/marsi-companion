"""Shared client for the Pi and a keyboard-only Ubuntu smoke test."""
from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request

from .config import load_env, validate_url
from .core import clean_text, session_name
from .speech import MAX_AUDIO_BYTES


class ClientError(Exception):
    pass


class Client:
    def __init__(self, url: str, token: str = "", session: str = "pi", timeout: float = 240):
        self.url, self.token = validate_url(url), token
        self.session, self.timeout = session_name(session), timeout
        self.http = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    @classmethod
    def from_env(cls):
        return cls(os.getenv("MARSI_SERVER_URL", "http://127.0.0.1:8765"),
                   os.getenv("MARSI_TOKEN", ""), os.getenv("MARSI_SESSION", "pi"))

    def request(self, path: str, payload=None, *, method="POST", audio: bytes | None = None):
        headers = {"Authorization": "Bearer " + self.token, "X-Marsi-Session": self.session}
        if audio is not None:
            body, headers["Content-Type"] = audio, "audio/wav"
        elif payload is not None:
            body, headers["Content-Type"] = json.dumps(payload, ensure_ascii=False).encode(), "application/json"
        else:
            body = None
        request = urllib.request.Request(self.url + path, data=body, headers=headers, method=method)
        try:
            with self.http.open(request, timeout=10 if path == "/health" or path.startswith(("/v1/telemetry", "/v1/journal")) else self.timeout) as response:
                raw = response.read(12_000_001)
            if len(raw) > 12_000_000:
                raise ClientError("Marsi sent a reply that was too large.")
            result = json.loads(raw)
            if not isinstance(result, dict):
                raise ClientError("Marsi sent an invalid reply.")
            return result
        except urllib.error.HTTPError as error:
            try:
                detail = json.loads(error.read(16384)).get("error", "Request rejected")
            except (ValueError, AttributeError):
                detail = f"Request rejected ({error.code})"
            raise ClientError(str(detail)) from error
        except (OSError, ValueError) as error:
            raise ClientError("The tiny forge is unreachable. Check the server, address and Wi-Fi.") from error

    def chat(self, text: str, speak=False):
        return self.request("/v1/chat", {"text": clean_text(text), "session_id": self.session, "want_audio": speak})

    def voice(self, recording: bytes, speak=True):
        if len(recording) > MAX_AUDIO_BYTES:
            raise ClientError("Recording exceeds the allowed size (2 MB).")
        path = "/v1/voice" if speak else "/v1/voice?want_audio=false"
        return self.request(path, audio=recording)

    def ritual(self, speak=False):
        return self.request("/v1/ritual", {"session_id": self.session, "want_audio": speak})

    def forget(self):
        return self.request("/v1/session", {"session_id": self.session}, method="DELETE")

    def notes(self):
        return self.request("/v1/memory?session_id=" + self.session, method="GET")

    def remember(self, text: str):
        return self.request("/v1/memory", {"session_id": self.session, "text": clean_text(text, 200)})

    def art(self, speak=False):
        return self.request("/v1/art", {"session_id": self.session, "want_audio": speak})

    def sermon(self, speak=False):
        return self.request("/v1/sermon", {"session_id": self.session, "want_audio": speak})

    def journal(self, *, before=0, after=0):
        return self.request(f"/v1/journal?session_id={self.session}&before={before}&after={after}", method="GET")

    def telemetry(self, readings):
        return self.request("/v1/telemetry", {"readings": readings})

    def speak_entry(self, entry_id):
        return self.request("/v1/speak", {"session_id": self.session, "entry_id": entry_id, "want_audio": True})


def command(text):
    """Exact local commands; sentences containing their words remain conversation."""
    name = text.strip().lower().lstrip("/")
    return {"art": "art", "exit": "exit", "quit": "exit", "sermon": "sermon",
            "ritual": "ritual", "bless": "ritual", "notes": "notes", "history": "history",
            "help": "help", "forget": "forget"}.get(name)


HELP = "art | sermon | bless | history | /remember TEXT | /notes | /forget | exit\nDisplay: F8 = Talk/Finish; Escape = window; Ctrl+Q = exit."


def main():
    parser = argparse.ArgumentParser(description="Chat with Marsi, your local tech-priest companion")
    parser.add_argument("--env", default=".env.pi")
    args = parser.parse_args()
    load_env(args.env)
    client = Client.from_env()
    print("MARSI // ARCHIVUM MARTIS\n" + HELP)
    try:
        while True:
            text = input("You > ").strip()
            if not text:
                continue
            action = command(text)
            if action == "exit":
                break
            try:
                if action == "forget":
                    client.forget()
                    print("This session's saved notes and conversation have been forgotten.")
                elif action == "notes":
                    print(client.notes()["notes"])
                elif text.startswith("/remember "):
                    print(client.remember(text[len("/remember "):])["notes"])
                elif action == "help":
                    print(HELP)
                elif action == "history":
                    for entry in client.journal()["entries"]:
                        print(f"[{entry['at']}] {entry['role']} > {entry['text']}")
                else:
                    task = {"art": client.art, "sermon": client.sermon, "ritual": client.ritual}.get(action)
                    result = task() if task else client.chat(text)
                    print("Marsi > " + result["text"])
            except (ClientError, ValueError) as error:
                print(str(error))
    except (KeyboardInterrupt, EOFError):
        print("\nThe tiny forge is resting.")


if __name__ == "__main__":
    main()
