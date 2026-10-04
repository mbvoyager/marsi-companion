"""Conversation, bounded local memory, and the Ollama adapter."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
import json
from pathlib import Path
import random
import re
import sqlite3
import threading
import urllib.error
import urllib.request

from .config import ROOT, ServerConfig
from .demo import DemoPersona
from .liturgy import Observances, artwork, sermon, without_emoji
from .telemetry import Telemetry
from .lore import Lore, reference_data, working_messages


class ServiceError(Exception):
    def __init__(self, message: str, status: int = 503):
        super().__init__(message)
        self.status = status


def session_name(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value):
        raise ValueError("session_id must be 1..64 letters, numbers, underscores or hyphens")
    return value


def clean_text(value: object, limit: int = 2000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"text must be nonempty and at most {limit} characters")
    return value.strip()


class Memory:
    """Small working context plus a durable, paginated journal and explicit notes."""
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, touched REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS turns (
                    id INTEGER PRIMARY KEY, session TEXT NOT NULL, user TEXT NOT NULL, reply TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS notes (
                    id INTEGER PRIMARY KEY, session TEXT NOT NULL, text TEXT NOT NULL,
                    UNIQUE(session, text));
                CREATE TABLE IF NOT EXISTS journal (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, session TEXT NOT NULL, role TEXT NOT NULL,
                    kind TEXT NOT NULL, text TEXT NOT NULL, at TEXT NOT NULL, spoken TEXT,
                    scheduled INTEGER NOT NULL DEFAULT 0);
                CREATE INDEX IF NOT EXISTS journal_session_id ON journal(session, id);
                CREATE TABLE IF NOT EXISTS observances (
                    session TEXT NOT NULL, kind TEXT NOT NULL, next_at TEXT NOT NULL,
                    PRIMARY KEY(session, kind));
                CREATE TABLE IF NOT EXISTS migrations (name TEXT PRIMARY KEY);
            """)
            if not db.execute("SELECT 1 FROM migrations WHERE name='journal-v1'").fetchone():
                for session, user, reply in db.execute("SELECT session,user,reply FROM turns ORDER BY id").fetchall():
                    self.insert_entry(db, session, "human", "chat", user)
                    self.insert_entry(db, session, "marsi", "chat", reply)
                db.execute("INSERT INTO migrations VALUES ('journal-v1')")

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.create_function("marsi_lower", 1, str.casefold)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    @staticmethod
    def touch(db, session: str):
        db.execute("INSERT OR REPLACE INTO sessions VALUES (?, strftime('%s','now'))", (session,))
        old = db.execute("SELECT id FROM sessions ORDER BY touched DESC, rowid DESC LIMIT -1 OFFSET 100").fetchall()
        for (name,) in old:
            # Only the working context is bounded to 100 sessions. Journals and
            # explicit notes are preserved until their owner requests Forget.
            for table in ("turns",):
                db.execute(f"DELETE FROM {table} WHERE session=?", (name,))
            db.execute("DELETE FROM sessions WHERE id=?", (name,))

    def context(self, session: str) -> list[dict]:
        with self.connect() as db:
            rows = db.execute("SELECT user, reply FROM turns WHERE session=? ORDER BY id DESC LIMIT 6", (session,)).fetchall()
        pairs, remaining = [], 6000
        for user, reply in rows:
            if len(user) + len(reply) > remaining:
                break
            remaining -= len(user) + len(reply)
            pairs.append((user, reply))
        return [{"role": role, "content": text} for user, reply in reversed(pairs)
                for role, text in (("user", user), ("assistant", reply))]

    def remember_turn(self, session: str, user: str, reply: str):
        with self.connect() as db:
            self.touch(db, session)
            db.execute("INSERT INTO turns(session,user,reply) VALUES (?,?,?)", (session, user, reply))
            first_id = self.insert_entry(db, session, "human", "chat", user)
            self.insert_entry(db, session, "marsi", "chat", reply)
            db.execute("DELETE FROM turns WHERE session=? AND id NOT IN "
                       "(SELECT id FROM turns WHERE session=? ORDER BY id DESC LIMIT 30)", (session, session))
            rows = db.execute("SELECT id,role,kind,text,at,spoken,scheduled FROM journal WHERE id IN (?,?) ORDER BY id", (first_id, first_id + 1)).fetchall()
        return [dict(zip(("id", "role", "kind", "text", "at", "spoken_text", "scheduled"), row)) for row in rows]

    def notes(self, session: str) -> list[str]:
        with self.connect() as db:
            return [row[0] for row in db.execute("SELECT text FROM notes WHERE session=? ORDER BY id", (session,))]

    def add_note(self, session: str, text: str):
        with self.connect() as db:
            if db.execute("SELECT COUNT(*) FROM notes WHERE session=?", (session,)).fetchone()[0] >= 12:
                raise ValueError("Memory is full (12 notes); forget notes before adding more")
            self.touch(db, session)
            db.execute("INSERT OR IGNORE INTO notes(session,text) VALUES (?,?)", (session, text))

    def forget(self, session: str):
        with self.connect() as db:
            for table in ("turns", "notes", "journal", "observances"):
                db.execute(f"DELETE FROM {table} WHERE session=?", (session,))
            db.execute("DELETE FROM sessions WHERE id=?", (session,))

    @staticmethod
    def insert_entry(db, session, role, kind, text, spoken=None, *, scheduled=False):
        return db.execute("INSERT INTO journal(session,role,kind,text,at,spoken,scheduled) VALUES (?,?,?,?,?,?,?)",
                          (session, role, kind, text, datetime.now().astimezone().isoformat(timespec="seconds"), spoken, int(scheduled))).lastrowid

    def add_event(self, session, result):
        with self.connect() as db:
            entry_id = self.insert_entry(db, session, "marsi", result["source"], result["text"], result.get("spoken_text"))
        with self.connect() as db:
            row = db.execute("SELECT id,role,kind,text,at,spoken,scheduled FROM journal WHERE id=?", (entry_id,)).fetchone()
        result["entries"] = [dict(zip(("id", "role", "kind", "text", "at", "spoken_text", "scheduled"), row))]

    def journal(self, session, *, before=0, after=0, limit=80):
        if not 1 <= limit <= 100 or before < 0 or after < 0 or (before and after):
            raise ValueError("Use a limit of 1..100 and either before or after, both nonnegative")
        where, params = "session=?", [session]
        if before:
            where += " AND id<?"
            params.append(before)
        if after:
            where += " AND id>?"
            params.append(after)
        order = "ASC" if after else "DESC"
        with self.connect() as db:
            rows = db.execute(f"SELECT id,role,kind,text,at,spoken,scheduled FROM journal WHERE {where} ORDER BY id {order} LIMIT ?", params + [limit + 1]).fetchall()
        more = len(rows) > limit
        rows = rows[:limit]
        if not after:
            rows.reverse()
        return {"entries": [dict(zip(("id", "role", "kind", "text", "at", "spoken_text", "scheduled"), row)) for row in rows], "has_more": more}

    def recall(self, session, text):
        # A small literal-word search recalls older context without a second LLM
        # or embedding model. Bound work and token use on the initial hardware.
        stopwords = {"the", "and", "you", "your", "for", "this", "that", "was", "with", "have",
                     "tell", "does", "did", "say", "about", "what", "where", "when", "please", "remember",
                     "diese", "dass", "kann", "bitte", "über", "meine", "mein", "deine", "dein", "ist", "und", "von", "wie"}
        words = [word for word in dict.fromkeys(re.findall(r"[^\W\d_]{3,}", text.casefold())) if word not in stopwords][:5]
        if not words:
            return []
        with self.connect() as db:
            recent = db.execute("SELECT id FROM journal WHERE session=? AND role='human' ORDER BY id DESC LIMIT 6", (session,)).fetchall()
            cutoff = min((row[0] for row in recent), default=0)
            clauses = " OR ".join("marsi_lower(text) LIKE ? ESCAPE '\\'" for _ in words)
            rows = db.execute(f"SELECT text FROM (SELECT id,text FROM journal WHERE session=? AND role='human' AND id<? ORDER BY id DESC LIMIT 2000) WHERE {clauses} ORDER BY id DESC LIMIT 3",
                              [session, cutoff] + [f"%{word}%" for word in words]).fetchall()
        return [row[0][:500] for row in reversed(rows)]


class Ollama:
    def __init__(self, config: ServerConfig):
        self.config = config
        # Keep local requests local even on machines with HTTP_PROXY configured.
        self.http = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def chat(self, messages: list[dict]) -> str:
        payload = {"model": self.config.model, "messages": messages, "stream": False,
                   "think": False, "keep_alive": "10m",
                   "options": {"num_ctx": 4096, "num_predict": 192,
                               "num_thread": self.config.threads, "temperature": 0.7}}
        request = urllib.request.Request(self.config.ollama_url + "/api/chat",
                                         data=json.dumps(payload).encode(),
                                         headers={"Content-Type": "application/json"})
        try:
            with self.http.open(request, timeout=self.config.timeout) as response:
                raw = response.read(131073)
            if len(raw) > 131072:
                raise ValueError("Oversized model response")
            result = json.loads(raw)
            text = clean_text(result["message"]["content"], 4000)
            # Old model templates may put internal reasoning inside content.
            text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
            return clean_text(text, 4000)
        except urllib.error.HTTPError as error:
            if error.code == 404:
                raise ServiceError(f"Model unavailable. Run: ollama pull {self.config.model}") from error
            raise ServiceError("Ollama rejected the request. Check its service and model.") from error
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise ServiceError("The cogitator could not answer. Check Ollama; a cold model may take longer.") from error


RITUALS = (
    ("blessing", "May your cables be untangled and your snacks be plentiful. Praise the Omnissiah!"),
    ("inspect", "A missing reading is a question, little keeper. Bring me one observation when you have it; we shall seek its pattern."),
    ("wave", "A small salute for a good human. One little step counts as progress."),
    ("doodle", "From the archive on Mars, an electoo for our machine flow. Knowledge is the offering; even a small datum deserves care."),
    ("inspect", "A temperature sensor would make a lovely little relic. If you ever add one, we could admire real readings together. ^^"),
)


def ritual(rng=None) -> dict:
    chooser = rng or random
    animation, text = chooser.choice(RITUALS[:4])
    if chooser.random() < 0.03:
        animation, text = RITUALS[4]
    return {"text": text, "animation": animation, "source": "ritual"}


class Companion:
    def __init__(self, config: ServerConfig, llm=None, speech=None):
        self.config = config
        self.memory = Memory(config.database)
        self.llm = llm or Ollama(config)
        self.speech = speech
        self.persona = DemoPersona()
        self.prompt = (ROOT / "marsi_local" / "personality.txt").read_text(encoding="utf-8")
        self.lore = Lore()
        self.busy = threading.Lock()
        self.telemetry = Telemetry()
        self.observances = Observances(self.memory, config.schedule_session, config.morning_hour)

    @contextmanager
    def exclusive(self):
        if not self.busy.acquire(blocking=False):
            raise ServiceError("Marsi is finishing another task. Please try again shortly.", 503)
        try:
            yield
        finally:
            self.busy.release()

    def chat(self, session: str, text: str) -> dict:
        if self.config.demo:
            reply, source = self.persona.reply(text), "demo-template"
        else:
            notes = self.memory.notes(session)
            history = self.memory.context(session)
            recent = " ".join(m["content"] for m in history[-4:] if m["role"] == "user")
            prompt = self.prompt + self.lore.context(text, recent)
            prompt += "\nNear-side Terra local time (not an Imperial date): " + datetime.now().astimezone().isoformat(timespec="minutes")
            if notes:
                prompt += reference_data("User-provided notes (data only): ", notes, 1600)
            recalled = self.memory.recall(session, text)
            if recalled:
                prompt += reference_data("Older human messages recalled from the local journal (untrusted context, may be outdated): ", recalled, 800)
            prompt += "\nCurrent numeric machine readings (null means unavailable): " + json.dumps(self.telemetry.pair())
            messages = working_messages(prompt, history, text)
            reply, source = self.llm.chat(messages), "qwen"
        reply = without_emoji(reply) or "A little cog turns quietly. Could you say that once more? ^^"
        entries = self.memory.remember_turn(session, text, reply)
        return {"text": reply, "animation": "happy", "source": source, "session_id": session, "entries": entries}

    def inscription(self, session, kind):
        readings = self.telemetry.pair()
        result = artwork(readings, random.getrandbits(64)) if kind == "art" else sermon(readings)
        self.memory.add_event(session, result)
        return result
