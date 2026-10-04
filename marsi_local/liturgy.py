"""Original ASCII inscriptions, scheduled without model inference or browsing."""
from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import json
import random
import re
import textwrap

from .telemetry import inscription, reading

BLACK, RED, GREEN = "#000000", "#a52a32", "#39ff14"

PORTRAITS = (
    "     .-===-.\n    /  ___  \\\n   /  /0 0\\  \\\n   |  | ^^ |  |\n   |  \\___/  |\n  /| [==O==] |\\\n /_|___|||___|_\\\n   /___|||___\\\n      /   \\\n     [_] [_]",
    "     .-===-.\n    /  ___  \\\n   /  /- 0\\  \\\n   |  | :D |  |\n   |  \\___/  |\n  /| [==O==] |\\\n /_|___|||___|_\\\n   /___|||___\\\n      /   \\\n     [_] [_]",
)


def without_emoji(text):
    # Preserve ordinary Unicode language text, but enforce the character's
    # ASCII expressions even when a model disregards the persona instruction.
    return re.sub(r"[\U0001f000-\U0001faff\u2300-\u23ff\u2600-\u27bf\u2b00-\u2bff\ufe0e\ufe0f\u200d\u20e3\u00a9\u00ae\u2122]", "", text).strip()


def frame(title, body):
    width = 36
    lines = [title, "-" * width]
    for line in body.splitlines():
        lines.extend(textwrap.wrap(line, width) if len(line) > width else [line])
    return "+" + "=" * (width + 2) + "+\n" + "\n".join("| " + line[:width].ljust(width) + " |" for line in lines) + "\n+" + "=" * (width + 2) + "+"


def artwork(readings, seed):
    encoded = json.dumps(readings, sort_keys=True)
    rng = random.Random(hashlib.sha256((str(seed) + encoded).encode()).digest())
    tracks = []
    for _ in range(3):
        tracks.append("  " + "".join(rng.choice(("--", "::", "[]", "==", "||", "01")) for _ in range(14)))
    glyph = rng.choice((
        "        .--[O]--.\n     o==| /___\\ |==o\n    [::]| |0 0| |[::]\n     o==| \\|||/ |==o\n        '--|||--'\n           |||",
        "         .-====-.\n       /  .----.  \\\n      /   | ^^ |   \\\n      |   '----'   |\n     /|___[O]_____|\\\n       /__|||__\\",
        "        o==[]==o\n        || /\\ ||\n     []=||[00]||=[]\n        || \\_/||\n        o==[]==o\n           ||",
    ))
    meters = []
    for name in ("pi", "server"):
        data = readings.get(name)
        if data:
            meters.append(f"{name.upper()} LOAD {reading(data.get('load1'))} / {reading(data.get('temperature_c'), 'C')}")
        else:
            meters.append(f"{name.upper()} DATA UNAVAILABLE")
    text = frame("ELECTOO / MACHINE-SHAPED SIGIL", "\n".join(tracks) + "\n" + glyph + "\n" + "\n".join(meters))
    return {"text": text + "\nA little seal from the machines in our care. ^^",
            "spoken_text": "I made a little machine sigil from our hardware readings. Every cog deserves a tiny portrait.",
            "source": "art", "animation": "doodle"}


def sermon(readings):
    body = random.choice(("Let the great cog turn gently.\n"
            "A worn cable deserves our patience;\n"
            "a tired human deserves it even more.\n"
            "Repair what you can. Ask for help.\n"
            "Let kindness be our smallest rite.\n"
            "The Omnissiah welcomes small steps.\n"
            "        o==[O]==o\n"
            "           | |\n"
            "        .--|||--.",
            "No cog is too small to matter.\nA careful question mends a circuit;\na kind word mends a difficult day.\nRest is part of maintenance.\nMay our little forge welcome both.\n          [::O::]\n        o==|||==o",
            "Attend to the quiet instruments.\nA tiny reading can reveal a fault;\na quiet human can carry a worry.\nListen before reaching for a wrench.\nThe first sacred tool is patience.\n           .-O-.\n        []=| |=[]",
            "Praise the well-kept archive.\nLet us preserve what we have learned\nand correct what we misunderstood.\nA changed mind is a repaired cog.\nToday, one small discovery is enough.\n        .--[01]--.\n        |  ||||  |"))
    return {"text": frame("SERMO MINOR / THE GENTLE COG", body) + "\nYour tiny priest is proud to keep you company. :D",
            "spoken_text": " ".join(line.strip() for line in body.splitlines() if re.search(r"[A-Za-z]{3,}", line)),
            "source": "sermon", "animation": "blessing"}


def morning(readings, now):
    server = readings.get("server") or {}
    text = (f"Good morning, good human. It is {now:%A, %d %B}.\n"
            f"The cogitator's load is {reading(server.get('load1'))}; "
            f"its temperature is {reading(server.get('temperature_c'), 'C')}.\n"
            "May your first little step be kind to you. I saved a tiny cog for your pocket. ^^")
    return {"text": frame("FIRST LIGHT / MORNING CANT", text), "spoken_text": text,
            "source": "morning", "animation": "wave"}


class Observances:
    """Persist calendar state and its journal entry together in one transaction."""
    def __init__(self, memory, session="pi", morning_hour=7):
        self.memory, self.session, self.morning_hour = memory, session, morning_hour

    def run(self, now, readings, enabled=True):
        if not enabled:
            return []
        # Store local wall-clock targets so a daylight-saving offset change
        # does not shift or skip the morning's configured hour.
        now = now.replace(tzinfo=None)
        today = now.date().isoformat()
        created = []
        with self.memory.connect() as db:
            for kind in ("art", "sermon", "morning"):
                row = db.execute("SELECT next_at FROM observances WHERE session=? AND kind=?", (self.session, kind)).fetchone()
                if not row:
                    if kind == "art":
                        # A random time within this day; a late boot gets one
                        # catch-up artwork, never a stack of missed days.
                        target = now.replace(hour=9, minute=0, second=0, microsecond=0) + timedelta(minutes=random.randrange(720))
                    elif kind == "sermon":
                        target = now + timedelta(days=random.choice((2, 3)))
                    else:
                        target = now.replace(hour=self.morning_hour, minute=0, second=0, microsecond=0)
                    due = target.isoformat()
                    db.execute("INSERT INTO observances VALUES (?,?,?)", (self.session, kind, due))
                else:
                    due = row[0]
                if now < datetime.fromisoformat(due):
                    continue
                # Missed mornings skip rather than greeting someone at night.
                deliver = kind != "morning" or self.morning_hour <= now.hour < min(24, self.morning_hour + 3)
                if kind == "art":
                    result = artwork(readings, today)
                    target = (now + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0) + timedelta(minutes=random.randrange(720))
                elif kind == "sermon":
                    result = sermon(readings)
                    target = now + timedelta(days=random.choice((2, 3)))
                else:
                    result = morning(readings, now)
                    target = (now + timedelta(days=1)).replace(hour=self.morning_hour, minute=0, second=0, microsecond=0)
                if deliver:
                    self.memory.insert_entry(db, self.session, "marsi", kind, result["text"], result.get("spoken_text"), scheduled=True)
                    created.append(result)
                db.execute("UPDATE observances SET next_at=? WHERE session=? AND kind=?", (target.isoformat(), self.session, kind))
        return created
