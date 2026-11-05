import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from marsi_local.climate import ClimateConfig, _check_archive
from marsi_local.config import ServerConfig
from marsi_local.core import Companion
from marsi_local.server import Server


class ClimateTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name)
        self.settings = path / "climate.json"
        self.settings.write_text(json.dumps({"sensors": {
            "test-forge": {"name": "Forge", "location": "indoor"},
            "sim-exterior": {"name": "Exterior", "location": "outdoor", "color": "#9fbf97"},
        }}), encoding="utf-8")
        self.app = Companion(ServerConfig(database=path / "archive.db", climate_config=self.settings, demo=True))
        self.client = Mock()
        self.server = Server(("127.0.0.1", 0), self.app)
        self.addCleanup(self.server.server_close)
        with patch("marsi_local.climate._mqtt_client", return_value=self.client):
            self.server.start_climate()

    def deliver(self, payload, sensor_id="test-forge", *, retained=False):
        message = SimpleNamespace(topic=f"zigbee2mqtt/{sensor_id}", payload=payload, retain=retained)
        self.client.on_message(self.client, None, message)

    def rows(self):
        with self.app.memory.connect() as db:
            return db.execute("""
                SELECT sensor_id, metric, observed_ms, value FROM climate_readings
                ORDER BY sensor_id, metric, observed_ms
            """).fetchall()

    def test_subscribes_again_after_reconnect(self):
        self.client.connect_async.assert_called_once_with("127.0.0.1", 1883, keepalive=30)
        self.client.loop_start.assert_called_once()
        for _ in range(2):
            self.client.on_connect(self.client, None, None, SimpleNamespace(is_failure=False), None)
            self.client.subscribe.assert_called_with([("zigbee2mqtt/test-forge", 1), ("zigbee2mqtt/sim-exterior", 1)])
        self.assertEqual(self.client.subscribe.call_count, 2)

    def test_split_sensor_reports_keep_their_values_and_millisecond_timestamps(self):
        temperature = b'{"last_seen":"2026-01-01T00:00:00.051Z","temperature":22.5,"linkquality":190}'
        humidity = b'{"last_seen":"2026-01-01T00:00:00.058Z","humidity":44.8,"linkquality":191}'
        self.deliver(temperature)
        self.deliver(humidity)
        self.deliver(temperature)
        self.deliver(b'{"last_seen":"2026-01-01T00:00:00.058Z","pressure":1019.6,"linkquality":191}')
        self.app.memory.remember_turn("pi", "A synthetic conversation", "A synthetic reply")
        self.app.memory.forget("pi")
        self.assertEqual(self.rows(), [
            ("test-forge", "humidity", 1767225600058, 44.8),
            ("test-forge", "linkquality", 1767225600051, 190.0),
            ("test-forge", "linkquality", 1767225600058, 191.0),
            ("test-forge", "temperature", 1767225600051, 22.5),
        ])

    def test_invalid_retained_and_unlisted_reports_do_not_enter_archive(self):
        self.deliver(b'{"temperature":24}', retained=True)
        self.deliver(b'{"temperature":24}', "unlisted")
        self.deliver(b'{"temperature":true,"humidity":150,"battery":NaN,"linkquality":1e999}')
        self.deliver(b'{"temperature":24,"last_seen":"2026-01-01T00:00:00"}')
        self.deliver(b'\xffbroken')
        self.assertEqual(self.rows(), [])
        self.deliver(b'{"temperature":-4.5,"humidity":70,"last_seen":1767225600058}', "sim-exterior")
        output = io.StringIO()
        with redirect_stdout(output):
            _check_archive(self.app.config.database, ClimateConfig.load(self.settings))
        self.assertIn("Forge\n  temperature: waiting for first reading", output.getvalue())
        self.assertIn("Exterior\n  temperature: -4.5  [2026-01-01T00:00:00.058+00:00]", output.getvalue())
