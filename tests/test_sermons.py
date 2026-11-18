from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from marsi_local.core import Memory
from marsi_local.observances import Observances
from marsi_local.sermons import choose, context, daily_sermon, pool, required
from marsi_local.display import Display


class SermonTests(unittest.TestCase):
    def test_manual_speech_marker_prevents_a_second_automatic_playback(self):
        display = Display.__new__(Display)
        display.pending_spoken = {"id": 7}
        display.last_spoken = 7
        display.busy = False
        display.link_online = True
        display.scheduled_voice(100)
        self.assertIsNone(display.pending_spoken)
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "archive.db"
        self.memory = Memory(self.path)

    def test_pool_has_forty_original_short_sermons_and_no_repeat_until_exhausted(self):
        self.assertGreaterEqual(len(pool()), 40)
        self.assertEqual(len({entry["id"] for entry in pool()}), len(pool()))
        self.assertTrue(all(3 <= len(entry["lines"]) <= 6 for entry in pool()))
        values = dict(weekday="Wednesday", indoor_temp="21.4", outdoor_temp="4.8", room_name="Forge", server_temp="54.0")
        with self.memory.connect() as db:
            texts = [choose(db, "pi", values)["text"] for _ in pool()]
            self.assertEqual(len(set(texts)), len(pool()))
            self.assertIn(choose(db, "pi", values)["text"], texts)

    def test_missing_or_stale_values_do_not_unlock_sensor_templates(self):
        now = datetime(2026, 11, 18, 12, tzinfo=timezone.utc)
        values = context({}, None, now)
        self.assertEqual(values, {"weekday": "Wednesday"})
        with self.memory.connect() as db:
            count = sum(required(entry) <= values.keys() for entry in pool())
            texts = [choose(db, "pi", values)["text"] for _ in range(count)]
        self.assertEqual(len(set(texts)), count)
        self.assertTrue(all("{" not in text for text in texts))
        self.assertFalse(any("sensor reports" in text for text in texts))

    def test_manual_and_scheduled_requests_share_one_daily_entry_even_concurrently(self):
        now = datetime(2026, 11, 18, 12, tzinfo=timezone.utc)
        with ThreadPoolExecutor(max_workers=4) as executor:
            replies = list(executor.map(lambda _: daily_sermon(self.memory, "pi", {}, now=now), range(8)))
        self.assertEqual(len({reply["entries"][0]["id"] for reply in replies}), 1)
        self.assertEqual(Observances(self.memory).run(now, {}), [])
        self.assertEqual(len(self.memory.journal("pi")["entries"]), 1)
        reopened = Memory(self.path)
        self.assertEqual(daily_sermon(reopened, "pi", {}, now=now), replies[0])

    def test_quiet_hours_late_start_no_backlog_and_dst(self):
        schedule = Observances(self.memory)
        now = datetime(2026, 10, 24, 6, tzinfo=timezone(timedelta(hours=2)))
        with patch("marsi_local.observances.random.choice", side_effect=lambda seq: seq[0]):
            self.assertEqual(schedule.run(now, {}), [])
            self.assertEqual([r["source"] for r in schedule.run(now.replace(hour=7), {})], ["morning"])
            self.assertEqual([r["source"] for r in schedule.run(now.replace(hour=8), {})], ["sermon"])
            self.assertEqual(schedule.run(now.replace(hour=23), {}), [])
            late = datetime(2026, 10, 29, 21, tzinfo=timezone(timedelta(hours=1)))
            self.assertEqual([r["source"] for r in Observances(Memory(self.path)).run(late, {})], ["sermon"])
            self.assertEqual(schedule.run(late, {}), [])
        with self.memory.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM sermon_days").fetchone()[0], 2)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM journal WHERE kind='art'").fetchone()[0], 0)

    def test_forget_resets_only_its_session(self):
        for name in ("pi", "other"):
            daily_sermon(self.memory, name, {})
        self.memory.forget("pi")
        with self.memory.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM sermon_usage WHERE session='pi'").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM sermon_days WHERE session='other'").fetchone()[0], 1)
