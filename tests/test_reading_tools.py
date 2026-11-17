from dataclasses import replace
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from marsi_local.climate import ClimateArchive, ClimateConfig, HOUR_MS, Sensor
from marsi_local.config import ServerConfig
from marsi_local.core import Companion
from marsi_local.reading_tools import ClimateIntent, climate_intent, format_now


class ClimateReadingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        model = Mock()
        self.app = Companion(ServerConfig(database=Path(temporary.name) / "marsi.db"), llm=model)
        sensors = {"forge": Sensor("Forge", "indoor"), "gate": Sensor("Gate", "outdoor"),
                   "removed": Sensor("Removed", "outdoor")}
        self.archive = ClimateArchive(self.app.memory, ClimateConfig(sensors))
        self.app.tools.climate = SimpleNamespace(archive=self.archive, current=self.snapshot)
        with self.app.memory.connect() as connection:
            connection.execute("UPDATE climate_sensors SET hidden=1 WHERE id='removed'")
        self.now = time.time_ns() // 1_000_000

    def snapshot(self):
        data = self.archive.current()
        for sensor in data["sensors"]:
            sensor["connection"] = "connected"
        return data

    def record(self, sensor, offset_ms, **metrics):
        self.archive.record(sensor, json.dumps({"last_seen": self.now + offset_ms, **metrics}).encode())

    def test_router_describes_local_and_historical_queries(self):
        cases = {
            "Wie warm ist es draußen?": ClimateIntent(location="outdoor", metric="temperature"),
            "Außentemperatur gerade?": ClimateIntent(location="outdoor", metric="temperature"),
            "How humid is it indoors?": ClimateIntent(location="indoor", metric="humidity"),
            "Show the average humidity for the last 24 hours": ClimateIntent("24h", metric="humidity"),
            "Temperaturverlauf der letzten 7 Tage": ClimateIntent("7d", metric="temperature"),
            "What's the temperature?": ClimateIntent(metric="temperature"),
            "What is relative humidity?": None,
            "Why does temperature affect evaporation?": None,
            "How hot is the oven?": None,
            "Wie warm wird es draußen morgen?": None,
            "Wie warm ist es auf dem Mars?": None,
            "Can you write me a joke about robots?": None,
        }
        for question, expected in cases.items():
            with self.subTest(question=question):
                self.assertEqual(climate_intent(question), expected)

    def test_current_context_and_answer_stay_grounded(self):
        self.record("forge", -1000, temperature=20.5, humidity=61)
        self.record("gate", -1000, temperature=8.25, humidity=68)
        self.record("removed", -1000, temperature=99)
        self.app.llm.chat.return_value = "It is 8.25 °C outside, little keeper."
        reply = self.app.chat("pi", "Wie warm ist es draußen?")
        sent = self.app.llm.chat.call_args.args[0]
        self.assertIn("Gate (outdoor)", sent[0]["content"])
        self.assertNotIn("Forge (indoor)", sent[0]["content"])
        self.assertNotIn("Removed", sent[0]["content"])
        self.assertEqual(reply["text"], self.app.llm.chat.return_value)
        self.assertEqual(self.app.memory.context("pi"), [])
        self.app.llm.chat.return_value = "It is 15 °C outside, little keeper."
        self.assertIn("8.25 °C", self.app.chat("pi", "How warm is it outside?")["text"])

    def test_missing_stale_and_disabled_data(self):
        self.record("gate", -3 * HOUR_MS, temperature=-2)
        reading = self.app.tools.climate_now()
        self.assertIn("last recorded temperature -2 °C", reading.text)
        self.assertIn("(stale)", reading.text)
        self.assertIn("humidity missing", reading.text)
        self.assertNotIn("Removed", reading.text)
        with self.app.memory.connect() as connection:
            connection.execute("UPDATE climate_sensors SET detached=1 WHERE id='gate'")
        self.assertIn("no visible outdoor", self.app.chat("pi", "Wie warm ist es draußen?")["text"])
        self.app.tools.config = replace(self.app.config, climate_now=False, climate_summary=False)
        self.assertIn("disabled", self.app.tools.climate_now().text)
        self.assertIn("disabled", self.app.tools.climate_summary("3h").text)
        self.app.llm.chat.assert_not_called()

    def test_summary_uses_raw_samples_and_ignores_out_of_window_samples(self):
        self.record("gate", -1_500_000, temperature=-6)
        self.record("gate", -1_499_999, temperature=12)
        self.record("gate", -1000, temperature=3)
        self.record("gate", -25 * HOUR_MS, temperature=100)
        data = self.archive.history("24h", summary=True)["sensors"][1]["statistics"]["temperature"]
        self.assertEqual(data, {"min": -6, "max": 12, "mean": 3, "samples": 3})
        readout = self.app.tools.climate_summary("24h", ClimateIntent("24h", "outdoor", "temperature"))
        self.assertIn("-6 °C / 12 °C / 3 °C", readout.text)
        with self.assertRaisesRegex(ValueError, "3h, 24h or 7d"):
            self.app.tools.climate_summary("30d")

    def test_large_registry_keeps_every_sensor_in_direct_report(self):
        data = self.snapshot()
        data["sensors"] = [{"name": f"Probe {i}", "location": "indoor", "connection": "connected",
                            "last_measurement_ms": self.now,
                            "readings": {"temperature": {"observed_ms": self.now, "value": 20},
                                         "humidity": {"observed_ms": self.now, "value": 50}}}
                           for i in range(30)]
        report = format_now(data)
        self.assertTrue(report.direct_reply)
        self.assertFalse(report.certain_reply)
        self.assertEqual(len(report.text.splitlines()), 30)
        self.assertIn("Probe 29", report.text)
