import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from urllib.request import Request

from marsi_local.climate import ClimateConfig, HOUR_MS, STALE_AFTER_MS, _check_archive
from marsi_local.client import Client, ClientError
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
        self.app = Companion(ServerConfig(database=path / "archive.db", climate_config=self.settings,
                                          demo=True, token="x" * 32))
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

    def measure(self, sensor_id, observed_ms, **values):
        self.deliver(json.dumps({"last_seen": observed_ms, **values}).encode(), sensor_id)

    def http_api(self):
        thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 2)
        self.addCleanup(self.server.shutdown)
        return Client(f"http://127.0.0.1:{self.server.server_port}", token=self.app.config.token, timeout=2)

    def next_snapshot(self, stream):
        for _ in range(12):
            if stream.readline() == b"event: climate\n":
                data = stream.readline()
                self.assertTrue(data.startswith(b"data: "))
                self.assertEqual(stream.readline(), b"\n")
                return json.loads(data.removeprefix(b"data: "))
        self.fail("Climate snapshot did not arrive")

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

    def test_current_climate_requires_token_and_keeps_each_measurement_time(self):
        now = 1_800_000_000_000
        self.measure("test-forge", now - 1000, temperature=22.5)
        self.measure("test-forge", now - 998, humidity=44.75)
        self.measure("test-forge", now + 1000, temperature=99)
        self.measure("sim-exterior", now - STALE_AFTER_MS, temperature=-2)
        self.measure("sim-exterior", now - 20, linkquality=180)
        api = self.http_api()
        for path in ("now", "history", "events"):
            with self.assertRaises(ClientError) as denied:
                Client(api.url, timeout=2).request(f"/v1/climate/{path}", method="GET")
            self.assertEqual(denied.exception.status, 401)
        with patch("marsi_local.climate.time.time_ns", return_value=now * 1_000_000):
            result = api.request("/v1/climate/now", method="GET")
        forge, exterior = result["sensors"]
        self.assertEqual(forge["status"], "fresh")
        self.assertEqual(forge["readings"]["temperature"], {"value": 22.5, "observed_ms": now - 1000})
        self.assertEqual(forge["readings"]["humidity"], {"value": 44.75, "observed_ms": now - 998})
        self.assertEqual(exterior["location"], "outdoor")
        self.assertEqual(exterior["color"], "#9fbf97")
        self.assertEqual(exterior["status"], "stale")
        self.assertEqual(exterior["last_report_ms"], now - 20)

    def test_history_filters_windows_and_aggregates_each_series_separately(self):
        boundary = 1_800_000_000_000
        now = boundary + 123_000
        for offset, value in ((-1_200_000, 10), (-290_000, 20), (-120_000, 24)):
            self.measure("test-forge", boundary + offset, temperature=value)
        self.measure("test-forge", boundary - 120_000, humidity=80)
        self.measure("sim-exterior", now - 3 * HOUR_MS - 1, temperature=-2)
        self.measure("sim-exterior", now - 25 * HOUR_MS, humidity=90)
        self.measure("sim-exterior", now - 8 * 24 * HOUR_MS, temperature=-20)
        api = self.http_api()
        with patch("marsi_local.climate.time.time_ns", return_value=now * 1_000_000):
            raw, day, week = (api.request(f"/v1/climate/history?range={period}", method="GET")
                              for period in ("3h", "24h", "7d"))
        self.assertEqual([result["bucket_ms"] for result in (raw, day, week)], [0, 300_000, 1_800_000])
        self.assertEqual(raw["sensors"][0]["series"]["temperature"], [
            [boundary - 1_200_000, 10], [boundary - 290_000, 20], [boundary - 120_000, 24],
        ])
        self.assertEqual(raw["sensors"][1]["series"]["temperature"], [])
        self.assertEqual(day["sensors"][0]["series"]["temperature"], [[boundary - 1_200_000, 10], [boundary - 300_000, 22]])
        self.assertEqual(day["sensors"][0]["series"]["humidity"], [[boundary - 300_000, 80]])
        self.assertEqual(week["sensors"][0]["series"]["temperature"], [[boundary - 1_800_000, 18]])
        self.assertEqual([point[1] for point in week["sensors"][1]["series"]["temperature"]], [-2])
        self.assertEqual([point[1] for point in week["sensors"][1]["series"]["humidity"]], [90])
        for period in ("", "1y"):
            with self.assertRaises(ClientError) as invalid:
                api.request(f"/v1/climate/history?range={period}", method="GET")
            self.assertEqual(invalid.exception.status, 400)

    def test_stream_pushes_new_reading_and_later_freshness_change(self):
        now = 1_800_000_000_000
        api = self.http_api()
        request = Request(api.url + "/v1/climate/events", headers={"Authorization": "Bearer " + api.token})
        with patch("marsi_local.server.CLIMATE_HEARTBEAT_SECONDS", 0.1), \
                patch("marsi_local.climate.time.time_ns", return_value=now * 1_000_000) as clock, \
                api.http.open(request, timeout=2) as stream:
            self.assertEqual(stream.headers.get_content_type(), "text/event-stream")
            self.assertEqual(self.next_snapshot(stream)["sensors"][0]["status"], "waiting")
            self.measure("test-forge", now, temperature=22)
            current = self.next_snapshot(stream)["sensors"][0]
            self.assertEqual(current["status"], "fresh")
            self.assertEqual(current["readings"]["temperature"]["value"], 22)
            self.measure("test-forge", now, temperature=22)
            self.assertEqual(self.server.climate.archive.revision, 1)
            clock.return_value = (now + STALE_AFTER_MS) * 1_000_000
            self.assertEqual(self.next_snapshot(stream)["sensors"][0]["status"], "stale")
