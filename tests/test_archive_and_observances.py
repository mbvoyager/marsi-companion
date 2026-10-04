"""Durable archive, offline observances, privacy and command routing."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from marsi_local.client import Client, ClientError, command
from marsi_local.config import ServerConfig
from marsi_local.core import Companion, Memory
from marsi_local.display import Display
from marsi_local.liturgy import Observances, artwork, without_emoji
from marsi_local.telemetry import FIELDS, Telemetry, numeric_readings
from tests import test_local_companion as fixtures


class DatabaseFixture(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "db"
        self.memory = Memory(self.path)



class ArchiveTests(DatabaseFixture):
    def test_complete_journal_survives_working_context_eviction_and_reopen(self):
        for n in range(40):
            self.memory.remember_turn("pi", f"Human {n}", f"Marsi {n}")
        memory = Memory(self.path)
        last = memory.journal("pi", limit=10)
        self.assertEqual(last["entries"][-1]["text"], "Marsi 39")
        self.assertTrue(last["has_more"])
        older = memory.journal("pi", before=last["entries"][0]["id"], limit=100)
        self.assertEqual(len(older["entries"]), 70)
        self.assertEqual(older["entries"][0]["text"], "Human 0")
        after = memory.journal("pi", after=older["entries"][-1]["id"], limit=10)
        self.assertEqual(after["entries"], last["entries"])

    def test_old_database_migrates_once_without_losing_notes(self):
        old = Path(self.folder.name) / "legacy"
        with sqlite3.connect(old) as db:
            db.execute("CREATE TABLE turns(id INTEGER PRIMARY KEY,session TEXT,user TEXT,reply TEXT)")
            db.execute("INSERT INTO turns VALUES(1,'pi','Old question','Old reply')")
        db.close()
        memory = Memory(old)
        memory.add_note("pi", "An old preference")
        reopened = Memory(old)
        self.assertEqual([e["text"] for e in reopened.journal("pi")["entries"]], ["Old question", "Old reply"])
        self.assertEqual(reopened.notes("pi"), ["An old preference"])

    def test_recall_finds_older_human_context_only_in_its_session(self):
        self.memory.remember_turn("pi", "My telescope is named Little Cog", "Lovely telescope")
        self.memory.remember_turn("other", "My telescope is private", "Private")
        for n in range(10):
            self.memory.remember_turn("pi", f"Other subject {n}", "Next cog")
        self.assertEqual(self.memory.recall("pi", "What is my telescope called?"), ["My telescope is named Little Cog"])
        self.assertEqual(self.memory.recall("pi", "hi"), [])

    def test_forget_clears_journal_and_schedule_without_reusing_ids(self):
        self.memory.remember_turn("pi", "Hello", "Hi")
        previous = self.memory.journal("pi")["entries"][-1]["id"]
        Observances(self.memory).run(datetime(2026, 10, 4, 7), {})
        self.memory.forget("pi")
        self.assertEqual(self.memory.journal("pi")["entries"], [])
        with self.memory.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM observances").fetchone()[0], 0)
        self.memory.remember_turn("pi", "New", "New")
        self.assertGreater(self.memory.journal("pi")["entries"][0]["id"], previous)

    def test_persona_enforces_ascii_expressions_and_preserves_language(self):
        llm = fixtures.FakeLLM()
        llm.chat = Mock(return_value="Guten Morgen, müder Mensch! 😀 ⭐ ☕ ^^ :D")
        app = Companion(ServerConfig(database=self.path), llm=llm)
        reply = app.chat("pi", "Hallo")["text"]
        self.assertIn("müder Mensch", reply)
        self.assertIn("^^ :D", reply)
        self.assertNotIn("😀", reply)
        self.assertEqual(without_emoji("💚"), "")


class ObservanceTests(DatabaseFixture):
    def test_calendar_survives_restart_and_prevents_duplicates(self):
        scheduler = Observances(self.memory)
        now = datetime(2026, 10, 4, 6)
        with patch("marsi_local.liturgy.random.randrange", return_value=0), patch("marsi_local.liturgy.random.choice", return_value=2):
            self.assertEqual(scheduler.run(now, {}), [])
            self.assertEqual([r["source"] for r in scheduler.run(now.replace(hour=7), {})], ["morning"])
            self.assertEqual(scheduler.run(now.replace(hour=7), {}), [])
            self.assertEqual([r["source"] for r in scheduler.run(now.replace(hour=9), {})], ["art"])
        reopened = Observances(Memory(self.path))
        self.assertEqual(reopened.run(now.replace(hour=9), {}), [])
        result = reopened.run(now + timedelta(days=2), {})
        self.assertEqual({r["source"] for r in result}, {"art", "sermon"})
        self.assertEqual(reopened.run(now + timedelta(days=2), {}), [])
        self.assertTrue(all(entry["scheduled"] for entry in self.memory.journal("pi")["entries"]))

    def test_late_morning_skips_without_backlog_and_dst_keeps_local_hour(self):
        scheduler = Observances(self.memory)
        scheduler.run(datetime(2026, 10, 24, 6, tzinfo=timezone(timedelta(hours=2))), {})
        late = scheduler.run(datetime(2026, 10, 24, 23, tzinfo=timezone(timedelta(hours=2))), {})
        self.assertNotIn("morning", [r["source"] for r in late])
        next_day = scheduler.run(datetime(2026, 10, 25, 7, tzinfo=timezone(timedelta(hours=1))), {})
        self.assertIn("morning", [r["source"] for r in next_day])
        self.assertEqual(scheduler.run(datetime(2026, 10, 25, 7, tzinfo=timezone(timedelta(hours=1))), {}), [])

    def test_art_is_ascii_and_shaped_by_real_readings(self):
        one = {"server": {"load1": 1, "temperature_c": 40}, "pi": None}
        two = {"server": {"load1": 3, "temperature_c": 60}, "pi": None}
        a = artwork(one, "today")["text"]
        self.assertTrue(a.isascii())
        self.assertEqual(a, artwork(one, "today")["text"])
        self.assertNotEqual(a, artwork(two, "today")["text"])
        self.assertIn("40C", a)
        self.assertIn("PI DATA UNAVAILABLE", a)

    def test_disabled_schedule_creates_no_entries(self):
        self.assertEqual(Observances(self.memory).run(datetime.now(), {}, enabled=False), [])
        self.assertEqual(self.memory.journal("pi")["entries"], [])


class TerminalAPITests(unittest.TestCase):
    setUpClass = classmethod(fixtures.APITests.setUpClass.__func__)
    tearDownClass = classmethod(fixtures.APITests.tearDownClass.__func__)
    setUp = fixtures.APITests.setUp

    def test_journal_and_telemetry_require_authentication_even_while_busy(self):
        visitor = Client(self.url)
        for route in ("/v1/journal", "/v1/telemetry"):
            with self.assertRaisesRegex(ClientError, "token"):
                visitor.request(route, method="GET")
        with self.app.exclusive():
            self.assertEqual(self.client.journal()["entries"], [])
            readings = self.client.telemetry({"load1": 2, "hostname": "private", "token": "private"})
            self.assertEqual(readings["pi"]["load1"], 2)
            self.assertNotIn("private", str(readings))

    def test_art_and_sermon_are_saved_without_inference_or_ascii_synthesis(self):
        with patch.object(self.app.llm, "chat", side_effect=AssertionError("No model for authored observances")):
            with patch.object(self.speech, "synthesize", wraps=self.speech.synthesize) as synthesize:
                result = self.client.art(speak=True)
                self.assertNotIn("+==", synthesize.call_args.args[0])
            self.client.sermon()
        journal = self.client.journal()["entries"]
        self.assertEqual([entry["kind"] for entry in journal], ["art", "sermon"])
        self.assertFalse(any(entry["scheduled"] for entry in journal))
        self.assertEqual(result["entries"][0], journal[0])
        self.assertEqual(self.app.memory.context("pi"), [])
        spoken = self.client.speak_entry(journal[-1]["id"])
        self.assertEqual(spoken["entry_id"], journal[-1]["id"])
        self.assertIn("audio_base64", spoken)

    def test_journal_cursors_are_checked_and_sessions_are_separate(self):
        self.client.chat("A private conversation")
        other = Client(self.url, self.token, "other-journal")
        self.assertEqual(other.journal()["entries"], [])
        with self.assertRaisesRegex(ClientError, "nonnegative"):
            self.client.journal(before=-1)
        with self.assertRaisesRegex(ClientError, "unavailable"):
            other.speak_entry(self.client.journal()["entries"][-1]["id"])


class InterfaceRulesTests(unittest.TestCase):
    def test_commands_are_exact_and_normal_sentences_remain_conversation(self):
        self.assertEqual(command(" art "), "art")
        self.assertEqual(command("/exit"), "exit")
        self.assertEqual(command("/sermon"), "sermon")
        self.assertIsNone(command("Tell me about art"))

    def test_numeric_telemetry_discards_identity_and_rejects_invalid_numbers(self):
        self.assertEqual(set(numeric_readings({"load1": 0, "ip": "private"})), set(FIELDS))
        for number in (float("nan"), float("inf"), -1, "private", True):
            with self.assertRaises(ValueError):
                numeric_readings({"load1": number})
        telemetry = Telemetry()
        telemetry.receive_pi({"load1": 3})
        self.assertEqual(telemetry.pair()["pi"]["load1"], 3)
        telemetry.pi_at = -1000
        self.assertIsNone(telemetry.pair()["pi"])

    def test_morning_can_speak_during_quiet_hours_and_defers_when_busy(self):
        display = Display.__new__(Display)
        now = datetime(2026, 10, 4, 7, tzinfo=timezone.utc)
        display.pending_spoken = {"id": 7, "kind": "morning", "at": now.isoformat()}
        display.busy = True
        display.speak = display.rituals = SimpleNamespace(get=lambda: True)
        display.observance_speech = display.morning_override = True
        display.ambient = SimpleNamespace(quiet_start=22, quiet_end=8)
        display.last_interaction = 0
        display.client = SimpleNamespace(speak_entry=Mock(return_value={}))
        display.start_task = Mock()
        with patch("marsi_local.display.datetime", wraps=datetime) as clock:
            clock.now.return_value = now
            display.scheduled_voice(100)
            display.start_task.assert_not_called()
            display.busy = False
            display.scheduled_voice(100)
        display.start_task.assert_called_once()
        display.start_task.call_args.args[0]()
        display.client.speak_entry.assert_called_once_with(7)


if __name__ == "__main__":
    unittest.main()
