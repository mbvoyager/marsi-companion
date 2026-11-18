"""Local calendar observances, atomically recorded once per day in SQLite."""
from datetime import datetime, timedelta
import random

from .ambient import quiet_hour
from .sermons import daily_sermon


class Observances:
    def __init__(self, memory, session="pi", morning_hour=7, quiet_start=22, quiet_end=8):
        self.memory, self.session, self.morning_hour = memory, session, morning_hour
        self.quiet_start, self.quiet_end = quiet_start, quiet_end
        self.minutes = tuple(minute for minute in range(morning_hour*60+1, 1440)
                             if not quiet_hour(minute//60, quiet_start, quiet_end))
        if not self.minutes:
            raise ValueError("Sermons need waking time after the morning hour")

    def run(self, now, readings, enabled=True, climate=None):
        if not enabled:
            return []
        from .liturgy import morning
        # Calendar targets are local wall time; DST does not shift their hour.
        wall = now.replace(tzinfo=None)
        today = wall.date().isoformat()
        created = []
        with self.memory.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM observances WHERE session=? AND kind='art'", (self.session,))
            row = db.execute("SELECT next_at FROM observances WHERE session=? AND kind='morning'", (self.session,)).fetchone()
            due = datetime.fromisoformat(row[0]) if row else wall.replace(hour=self.morning_hour, minute=0, second=0, microsecond=0)
            if wall >= due:
                if self.morning_hour <= wall.hour < min(24, self.morning_hour+3):
                    result = morning(readings, now)
                    self.memory.insert_entry(db, self.session, "marsi", "morning", result["text"], result["spoken_text"], scheduled=True)
                    created.append(result)
                due = (wall+timedelta(days=1)).replace(hour=self.morning_hour, minute=0, second=0, microsecond=0)
            db.execute("INSERT OR REPLACE INTO observances VALUES (?,?,?)", (self.session, "morning", due.isoformat()))
            if db.execute("SELECT 1 FROM sermon_days WHERE session=? AND day=?", (self.session, today)).fetchone():
                return created
            row = db.execute("SELECT next_at FROM observances WHERE session=? AND kind='sermon'", (self.session,)).fetchone()
            target = datetime.fromisoformat(row[0]) if row else None
            if (target is None or target.date() != wall.date()
                    or target.hour*60+target.minute not in self.minutes):
                target = wall.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(minutes=random.choice(self.minutes))
                db.execute("INSERT OR REPLACE INTO observances VALUES (?,?,?)", (self.session, "sermon", target.isoformat()))
            if wall >= target and wall.hour*60+wall.minute in self.minutes:
                created.append(daily_sermon(self.memory, self.session, readings, climate, now, scheduled=True, db=db))
        return created
