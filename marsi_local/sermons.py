"""An authored, persistent shuffle bag; no model, invented readings or repeats."""
from datetime import datetime
from functools import lru_cache
import json
import math
from pathlib import Path
import random
from string import Formatter

from .interludes import climate_context


@lru_cache(maxsize=1)
def pool():
    entries = json.loads(Path(__file__).with_name("sermons.json").read_text(encoding="utf-8"))
    return tuple(entries)


def context(readings, climate, now):
    # strftime depends on the system locale; Marsi's text is always English.
    values = {"weekday": ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")[now.weekday()]}
    server_temp = ((readings or {}).get("server") or {}).get("temperature_c")
    if type(server_temp) in (int, float) and math.isfinite(server_temp):
        values["server_temp"] = f"{server_temp:.1f}"
    for sensor in climate_context(climate, now):
        if sensor["temperature"] is None or sensor["connection"] == "lost":
            continue
        key = "outdoor_temp" if sensor["location"] == "outdoor" else "indoor_temp"
        if key not in values:
            values[key] = f"{sensor['temperature']:.1f}"
            if key == "indoor_temp":
                values["room_name"] = sensor["name"]
    return values


def required(entry):
    return {field for line in entry["lines"] for _, field, _, _ in Formatter().parse(line) if field}


def choose(db, session, values):
    eligible = [entry for entry in pool() if required(entry) <= values.keys()]
    used = dict(db.execute("SELECT sermon_id, cycle FROM sermon_usage WHERE session=?", (session,)))
    cycle = max(used.values(), default=0)
    available = [entry for entry in eligible if used.get(entry["id"], -1) != cycle]
    if not available:
        cycle += 1
        available = eligible
    selected = random.choice(available)
    db.execute("INSERT INTO sermon_usage VALUES (?,?,?) ON CONFLICT(session,sermon_id) DO UPDATE SET cycle=excluded.cycle",
               (session, selected["id"], cycle))
    body = "\n".join(line.format_map(values) for line in selected["lines"])
    return {"text": "++ SERMO MINOR // " + selected["title"] + " ++\n\n" + body,
            "spoken_text": body, "source": "sermon", "animation": "blessing"}


def daily_sermon(memory, session, readings, climate=None, now=None, *, scheduled=False, db=None):
    now = now or datetime.now().astimezone()
    if db is None:
        with memory.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            return daily_sermon(memory, session, readings, climate, now, scheduled=scheduled, db=connection)
    day = now.date().isoformat()
    row = db.execute("SELECT j.id,j.role,j.kind,j.text,j.at,j.spoken,j.scheduled FROM journal j "
                     "JOIN sermon_days d ON d.entry_id=j.id WHERE d.session=? AND d.day=?", (session, day)).fetchone()
    if row:
        result = {"text": row[3], "spoken_text": row[5], "source": "sermon", "animation": "blessing"}
    else:
        result = choose(db, session, context(readings, climate, now))
        entry_id = memory.insert_entry(db, session, "marsi", "sermon", result["text"], result["spoken_text"], scheduled=scheduled)
        db.execute("INSERT OR REPLACE INTO sermon_days VALUES (?,?,?)", (session, day, entry_id))
        row = db.execute("SELECT id,role,kind,text,at,spoken,scheduled FROM journal WHERE id=?", (entry_id,)).fetchone()
    result["entries"] = [dict(zip(("id", "role", "kind", "text", "at", "spoken_text", "scheduled"), row))]
    return result
