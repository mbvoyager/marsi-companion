from datetime import datetime, timezone
import json
import unittest
from unittest.mock import patch

from marsi_local.interludes import TYPES, InterludeTimer, build_interlude
from marsi_local.lore import Lore
from marsi_local.client import Client, ClientError
from tests.test_web import BrowserRoutes


NOW = datetime(2026, 11, 18, 12, tzinfo=timezone.utc)


def fixture():
    at = int(NOW.timestamp()*1000)
    return {"generated_ms": at, "services": {"mqtt": "online", "zigbee2mqtt": "online"}, "sensors": [
        {"id": "indoor", "name": "Forge", "location": "indoor", "connection": "connected",
         "readings": {"temperature": {"value": 21.4, "observed_ms": at-60000}}},
        {"id": "outdoor", "name": "Exterior", "location": "outdoor", "connection": "lost",
         "readings": {"temperature": {"value": -2, "observed_ms": at-8_000_000}}},
    ]}


class InterludeTests(unittest.TestCase):
    def test_all_scenes_are_small_deterministic_json_with_truthful_missing_data(self):
        for kind in TYPES:
            with self.subTest(kind=kind):
                packet = build_interlude(kind, climate=fixture(), lore=Lore(), seed=12, now=NOW)
                self.assertEqual(packet, build_interlude(kind, climate=fixture(), lore=Lore(), seed=12, now=NOW))
                self.assertEqual(json.loads(json.dumps(packet)), packet)
                self.assertLess(len(json.dumps(packet)), 12000)
                self.assertEqual(set(packet), {"version", "type", "seed", "duration", "data"})
                self.assertEqual(packet["data"]["sensors"][0]["temperature"], 21.4)
                self.assertIsNone(packet["data"]["sensors"][1]["temperature"])
                self.assertIsNone(packet["data"]["machines"]["pi"])

    def test_missing_readings_are_honest_and_invalid_requests_rejected(self):
        self.assertIn("NO SIGNAL", " ".join(build_interlude("vox", now=NOW)["data"]["lines"]))
        for args in ({"kind": "art"}, {"duration": 14}, {"duration": True}, {"seed": -1}):
            with self.assertRaises(ValueError):
                build_interlude(**args)

    def test_timer_never_interrupts_interaction_voice_or_quiet_hours(self):
        timer = InterludeTimer()
        for enabled, busy, hour, last in ((True, True, 12, 0), (True, False, 23, 0),
                                           (True, False, 12, 950), (False, False, 12, 0)):
            timer.next_at = 999
            self.assertFalse(timer.due(1000, hour, last, busy, enabled))
            self.assertGreater(timer.next_at, 1000)
        timer.next_at = 999
        self.assertTrue(timer.due(1000, 12, 0, False, True))


class InterludeAPITests(unittest.TestCase):
    setUp = BrowserRoutes.setUp

    def test_authenticated_ephemeral_reads_work_during_inference(self):
        before = self.api.journal()
        with self.assertRaises(ClientError) as rejected:
            Client(self.api.url).interlude()
        self.assertEqual(rejected.exception.status, 401)
        for kind in TYPES:
            packet = self.api.interlude(kind, 15)
            self.assertEqual(packet["type"], kind)
        self.assertEqual(self.api.journal(), before)
        status = self.api.request("/v1/status", method="GET")
        self.assertIn("imperial_date", status)
        with self.assertRaises(ClientError) as rejected:
            self.api.interlude("unknown")
        self.assertEqual(rejected.exception.status, 400)
