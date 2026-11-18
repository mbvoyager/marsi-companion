"""Ephemeral local-data interludes: no inference, browsing or journal writes."""
from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import math
import random
import io
import struct
import wave

from .ambient import Ambient, quiet_hour
from .telemetry import FIELDS, numeric_readings
from .theme import imperial_date, sensor_style

LOG = logging.getLogger(__name__)
TYPES = ("auspex", "vox", "servitor", "hololith", "codex", "noosphere")
THOUGHTS = (
    "A labelled cable is a small act of mercy.",
    "A missing datum deserves a question, not an invented number.",
    "The smallest cog may still request a very large hat.",
    "Praise the backup. Then check that it opens.",
    "The archive welcomes a careful little observation.",
    "One tidy connector. A modest but magnificent victory.",
    "The sacred manual has acquired another useful annotation.",
    "A quiet sensor is not necessarily a broken sensor.",
)


def chirp():
    """A short optional servitor chirp, generated and held entirely in RAM."""
    rate = 16000
    frames = bytearray()
    for i in range(int(rate*.18)):
        t = i/rate
        envelope = min(1,t/.015,(.18-t)/.025)
        frequency = 740 if t < .09 else 990
        frames.extend(struct.pack("<h",int(2000*envelope*math.sin(math.tau*frequency*t))))
    buffer = io.BytesIO()
    with wave.open(buffer,"wb") as audio:
        audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(rate); audio.writeframes(frames)
    return buffer.getvalue()


def climate_context(climate, now=None):
    """Only fresh measurements may be used in authored factual sentences."""
    snapshot = climate or {}
    at = int((now or datetime.now(timezone.utc)).timestamp()*1000)
    stale = snapshot.get("stale_after_ms", 7_200_000)
    result = []
    for index, sensor in enumerate(snapshot.get("sensors", [])[:32]):
        readings = sensor.get("readings", {})
        def fresh(metric):
            item = readings.get(metric, {})
            value, stamp = item.get("value"), item.get("observed_ms")
            if (type(value) in (int, float) and math.isfinite(value)
                    and type(stamp) in (int, float) and 0 <= at-stamp < stale):
                return value
            return None
        result.append({"id": sensor["id"], "name": sensor["name"][:64],
                       "room": sensor.get("room", "")[:64], "location": sensor["location"],
                       "connection": sensor.get("connection", "unknown"),
                       "last_report_ms": sensor.get("last_report_ms"),
                       "temperature": fresh("temperature"), "humidity": fresh("humidity"),
                       "style": sensor.get("style") or sensor_style(sensor, index)})
    return result


def build_interlude(kind=None, *, readings=None, climate=None, lore=None, now=None, seed=None, duration=None):
    if kind is not None and kind not in TYPES:
        raise ValueError("Interlude type must be " + ", ".join(TYPES))
    seed = random.getrandbits(32) if seed is None else seed
    if type(seed) is not int or not 0 <= seed < 2**32:
        raise ValueError("Interlude seed must be an unsigned 32-bit integer")
    rng = random.Random(seed)
    kind = kind or rng.choice(TYPES)
    duration = rng.randint(15, 30) if duration is None else duration
    if type(duration) is not int or not 15 <= duration <= 30:
        raise ValueError("Interlude duration must be 15..30 seconds")
    now = now or datetime.now(timezone.utc)
    climate = climate or {}
    sensors = climate_context(climate, now)
    machines = {name: numeric_readings((readings or {}).get(name)) if (readings or {}).get(name) else None
                for name in ("server", "pi")}
    data = {"at": now.isoformat(), "imperial_date": imperial_date(now), "sensors": sensors,
            "machines": machines, "services": climate.get("services", {}),
            "thought": rng.choice(THOUGHTS)}
    if kind == "vox":
        usable = [sensor for sensor in sensors if sensor["temperature"] is not None]
        lost = [sensor for sensor in sensors if sensor["connection"] == "lost"]
        if lost:
            lines = [f"AUSPEX REPORTS NO SIGNAL FROM {lost[0]['name']}.",
                     "ITS PLACE IN THE LEDGER REMAINS OPEN.",
                     "I HAVE ADDED A VERY SMALL PRAYER. ^^"]
        elif usable:
            sensor = rng.choice(usable)
            lines = [f"{sensor['name']} REPORTS {sensor['temperature']:.1f} °C.",
                     "A LITTLE NUMBER HAS COMPLETED ITS JOURNEY.",
                     "THE ARCHIVE RECEIVES IT WITH DUE CEREMONY."]
        else:
            lines = ["CLIMATE MEASUREMENTS: NO SIGNAL.", "THE ARCHIVE WILL WAIT FOR A REAL OBSERVATION.",
                     "MY TINY DATASLATE IS READY."]
        data.update(origin="MARS RELIQUARY", channel="VERMILLION", lines=lines,
                    corrupted=rng.randrange(6) == 0)
    elif kind == "codex":
        records = lore.records if lore is not None else []
        record = rng.choice(records) if records else None
        data["codex"] = {"title": record["title"], "facts": record["facts"][:3]} if record else {
            "title": "NO SIGNAL", "facts": ["The local codex is unavailable."]}
    elif kind == "hololith":
        data["model"] = rng.choice(("cog", "skull", "planet"))
    return {"version": 1, "type": kind, "seed": seed, "duration": duration, "data": data}


@dataclass
class InterludeTimer(Ambient):
    minimum: float = 1800
    maximum: float = 5400
    idle_seconds: float = 120

    def __post_init__(self):
        super().__post_init__()
        if not 120 <= self.idle_seconds <= 86400:
            raise ValueError("Interlude idle time must be 120..86400 seconds")

    def due(self, now, hour, last_interaction, busy, enabled):
        if now < self.next_at:
            return False
        self.schedule(now)
        return enabled and not busy and now-last_interaction >= self.idle_seconds and not quiet_hour(
            hour, self.quiet_start, self.quiet_end)
