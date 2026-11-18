"""English authored greetings; daily sermons use the persistent pool."""
from __future__ import annotations
import re
from .telemetry import reading
from .theme import BLACK, RED, GREEN
from .observances import Observances

def without_emoji(text):
    # Preserve ordinary Unicode language text, but enforce the character's
    # ASCII expressions even when a model disregards the persona instruction.
    return re.sub(r"[\U0001f000-\U0001faff\u2300-\u23ff\u2600-\u27bf\u2b00-\u2bff\ufe0e\ufe0f\u200d\u20e3\u00a9\u00ae\u2122]", "", text).strip()


def frame(title, body):
    return "++ " + title + " ++\n\n" + body


def morning(readings, now):
    weekdays = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
    months = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December")
    server = readings.get("server") or {}
    text = (f"Good morning, good human. It is {weekdays[now.weekday()]}, {now.day:02d} {months[now.month-1]}.\n"
            f"The cogitator's load is {reading(server.get('load1'))}; "
            f"its temperature is {reading(server.get('temperature_c'), 'C')}.\n"
            "May your first little step be kind to you. I saved a tiny cog for your pocket. ^^")
    return {"text": frame("FIRST LIGHT / MORNING CANT", text), "spoken_text": text,
            "source": "morning", "animation": "wave"}
