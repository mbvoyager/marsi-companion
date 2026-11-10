from contextlib import closing
import json
from pathlib import Path
import shutil
import sqlite3
import ssl
import subprocess
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from marsi_local.config import ServerConfig
from marsi_local.core import Companion, ServiceError
from marsi_local.server import Server


DEVICE = "0x00158d0000000042"
DETAILS = {"name": "Exterior", "location": "outdoor", "room": "Porch", "color": "#9fbf97"}


class ClimateAdministration(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        settings = self.root / "climate.json"
        settings.write_text(json.dumps({"sensors": {"test-forge": {"name": "Forge", "location": "indoor"}}}),
                            encoding="utf-8")
        self.app = Companion(ServerConfig(database=self.root / "archive.sqlite3", climate_config=settings,
                                          demo=True, token="r" * 32, admin_token="a" * 32))
        self.mqtt = Mock()
        self.server = Server(("127.0.0.1", 0), self.app)
        self.addCleanup(self.server.server_close)
        with patch("marsi_local.climate._mqtt_client", return_value=self.mqtt):
            self.server.start_climate()
        self.admin = self.server.climate_admin
        self.now = time.time_ns() // 1_000_000 - 60_000
        self.mqtt.on_connect(self.mqtt, None, None, SimpleNamespace(is_failure=False), None)
        self.deliver("bridge/state", {"state": "online"}, retained=True)
        self.mqtt.publish.side_effect = self.bridge_response

    def deliver(self, suffix, data, *, retained=False):
        self.mqtt.on_message(self.mqtt, None, SimpleNamespace(topic="zigbee2mqtt/" + suffix,
                                                              payload=json.dumps(data).encode(), retain=retained))

    def bridge_response(self, topic, raw, **options):
        action = topic.removeprefix("zigbee2mqtt/bridge/request/")
        request = json.loads(raw)
        self.assertEqual(options, {"qos": 0, "retain": False})
        self.deliver("bridge/response/" + action, {"transaction": "another-request", "status": "error"})
        self.deliver("bridge/response/" + action, {"transaction": request["transaction"], "status": "ok", "data": {}})
        return SimpleNamespace(rc=0)

    def discover_exterior(self):
        self.deliver("bridge/devices", [
            {"ieee_address": "0x0000000000000000", "type": "Coordinator"},
            {"ieee_address": DEVICE, "type": "EndDevice", "friendly_name": "simulated-exterior",
             "interview_completed": True, "supported": True, "definition": {"model": "WSDCGQ11LM", "exposes": [
                 {"property": "temperature"}, {"property": "humidity"},
             ]}},
        ], retained=True)

    def adopt_exterior(self):
        self.discover_exterior()
        return self.admin.save_sensor({"device_id": DEVICE, **DETAILS})

    def confirm(self, preview):
        return self.admin.confirm({"preview_id": preview["preview_id"], "confirm": True})

    def test_pair_discover_adopt_and_rename_second_sensor(self):
        started = self.admin.pairing({"open": True})
        topic, raw = self.mqtt.publish.call_args.args
        self.assertEqual(topic, "zigbee2mqtt/bridge/request/permit_join")
        self.assertEqual(json.loads(raw)["time"], 120)
        self.assertEqual(json.loads(raw)["device"], "coordinator")
        self.assertGreater(started["pairing_until_ms"], self.now)

        self.discover_exterior()
        self.assertEqual([device["ieee_address"] for device in self.admin.status()["discoveries"]], [DEVICE])
        self.deliver("simulated-exterior", {"temperature": 6, "last_seen": self.now})
        self.assertEqual(self.admin.readings({})["rows"], [])
        added = self.adopt_exterior()
        self.assertEqual(added["saved_id"], DEVICE)
        self.assertEqual(added["discoveries"], [])
        self.mqtt.subscribe.assert_called_with([("zigbee2mqtt/simulated-exterior", 1)])
        self.deliver("test-forge", {"temperature": 21, "last_seen": self.now})
        self.deliver("simulated-exterior", {"temperature": 8, "humidity": 60, "last_seen": self.now})
        self.admin.save_sensor({"id": DEVICE, **DETAILS, "name": "Garden", "color": "#da7769"})
        forge, exterior = self.server.climate.archive.history("3h")["sensors"]
        self.assertEqual(forge["series"]["temperature"], [[self.now, 21]])
        self.assertEqual((exterior["name"], exterior["room"], exterior["color"]), ("Garden", "Porch", "#da7769"))
        self.assertEqual(exterior["series"]["temperature"], [[self.now, 8]])
        self.assertIsNone(self.admin.pairing({"open": False})["pairing_until_ms"])

    def test_hide_keeps_ingestion_and_unpair_keeps_history_after_confirmation(self):
        self.adopt_exterior()
        self.deliver("simulated-exterior", {"temperature": 8, "last_seen": self.now})
        hidden = self.confirm(self.admin.preview({"action": "hide", "id": DEVICE}))
        self.assertEqual(hidden["readings_deleted"], 0)
        self.assertTrue((self.root / "climate-backups" / hidden["backup"]).is_file())
        self.assertEqual([sensor["id"] for sensor in self.server.climate.current()["sensors"]], ["test-forge"])
        self.deliver("simulated-exterior", {"temperature": 9, "last_seen": self.now + 1})
        self.assertEqual(len(self.admin.readings({"filters": {"sensor_id": DEVICE}})["rows"]), 2)
        self.admin.save_sensor({"id": DEVICE, **DETAILS, "show": True})
        self.assertEqual(self.server.climate.current()["sensors"][1]["id"], DEVICE)

        def reject(topic, raw, **_options):
            self.deliver("bridge/response/device/remove", {"transaction": json.loads(raw)["transaction"],
                                                            "status": "error"})
            return SimpleNamespace(rc=0)

        self.mqtt.publish.side_effect = reject
        with self.assertRaisesRegex(ServiceError, "rejected"):
            self.confirm(self.admin.preview({"action": "unpair", "id": DEVICE}))
        self.assertFalse(self.server.climate.archive.registered()[DEVICE].detached)
        self.mqtt.publish.side_effect = self.bridge_response
        removed = self.confirm(self.admin.preview({"action": "unpair", "id": DEVICE}))
        self.assertTrue(removed["status"]["sensors"][1]["detached"])
        self.assertEqual(json.loads(self.mqtt.publish.call_args.args[1])["force"], False)
        self.mqtt.unsubscribe.assert_called_with(["zigbee2mqtt/simulated-exterior"])
        self.deliver("simulated-exterior", {"temperature": 10, "last_seen": self.now + 2})
        self.assertEqual(len(self.admin.readings({"filters": {"sensor_id": DEVICE}})["rows"]), 2)
        self.adopt_exterior()
        self.assertEqual(self.server.climate.current()["sensors"][1]["id"], DEVICE)

    def test_exact_and_range_deletion_have_backups_and_audit_records(self):
        self.adopt_exterior()
        self.app.memory.remember_turn("pi", "Synthetic note", "Synthetic answer")
        self.deliver("test-forge", {"temperature": 99, "humidity": 50, "last_seen": self.now})
        self.deliver("simulated-exterior", {"temperature": 8, "last_seen": self.now})
        self.deliver("simulated-exterior", {"temperature": 9, "last_seen": self.now + 1})
        filters = {"sensor_id": "test-forge", "metric": "temperature", "observed_ms": self.now}
        preview = self.admin.preview({"action": "delete", "filters": filters})
        self.assertEqual(preview["count"], 1)
        with self.assertRaises(ValueError):
            self.admin.confirm({"preview_id": preview["preview_id"], "confirm": False})
        result = self.confirm(preview)
        self.assertEqual(result["readings_deleted"], 1)
        backup = self.root / "climate-backups" / result["backup"]
        with closing(sqlite3.connect(backup.as_uri() + "?mode=ro", uri=True)) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM climate_readings").fetchone(), (4,))
            self.assertEqual(db.execute("SELECT count(*) FROM journal").fetchone(), (2,))
        with self.assertRaisesRegex(ServiceError, "expired"):
            self.confirm(preview)
        range_filters = {"from_ms": self.now, "to_ms": self.now + 1}
        self.assertEqual(self.admin.preview({"action": "delete", "filters": range_filters})["count"], 2)
        range_filters["sensor_id"] = DEVICE
        self.assertEqual(self.confirm(self.admin.preview({"action": "delete", "filters": range_filters}))["readings_deleted"], 1)
        self.assertEqual({(row["sensor_id"], row["value"]) for row in self.admin.readings({})["rows"]},
                         {("test-forge", 50), (DEVICE, 9)})
        with self.app.memory.connect() as db:
            rows = db.execute("SELECT at_ms, action, scope, readings_deleted, backup FROM climate_admin_log ORDER BY id").fetchall()
        self.assertEqual([(action, json.loads(scope), count) for _, action, scope, count, _ in rows],
                         [("delete", filters, 1), ("delete", range_filters, 1)])
        self.assertTrue(all(at >= self.now and (backup.parent / filename).is_file() for at, _, _, _, filename in rows))

    def test_changed_preview_or_failed_backup_keeps_data(self):
        self.deliver("test-forge", {"temperature": 21, "last_seen": self.now})
        action = {"action": "delete", "filters": {"sensor_id": "test-forge"}}
        preview = self.admin.preview(action)
        self.deliver("test-forge", {"temperature": 22, "last_seen": self.now})
        with self.assertRaisesRegex(ServiceError, "selection changed"):
            self.confirm(preview)
        (self.root / "climate-backups").write_text("simulate a failed backup directory", encoding="utf-8")
        with self.assertRaisesRegex(ServiceError, "backup"):
            self.confirm(self.admin.preview(action))
        self.assertEqual([row["value"] for row in self.admin.readings({})["rows"]], [22])
        with self.app.memory.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM climate_admin_log").fetchone(), (0,))

    def serve(self, server):
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 2)
        self.addCleanup(server.shutdown)

    @unittest.skipUnless(shutil.which("openssl"), "OpenSSL is required for the HTTPS test")
    def test_management_requires_https_and_both_tokens(self):
        key, cert = self.root / "test.key", self.root / "test.crt"
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                        "-subj", "/CN=localhost", "-addext", "subjectAltName=IP:127.0.0.1",
                        "-keyout", str(key), "-out", str(cert)], check=True, capture_output=True)
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.load_cert_chain(cert, key)
        secure = Server(("127.0.0.1", 0), self.app, shared=self.server, tls=tls)
        self.addCleanup(secure.server_close)
        self.serve(self.server)
        self.serve(secure)
        context = ssl.create_default_context(cafile=str(cert))

        def request(path, server=secure, *, read=True, admin=False, body=None):
            headers = {}
            if read:
                headers["Authorization"] = "Bearer " + self.app.config.token
            if admin:
                headers["X-Marsi-Admin-Token"] = self.app.config.admin_token
            if body is not None:
                headers["Content-Type"] = "application/json"
                body = json.dumps(body).encode()
            scheme = "https" if server.tls else "http"
            with urlopen(Request(f"{scheme}://127.0.0.1:{server.server_port}{path}", body, headers),
                         context=context, timeout=5) as response:
                return json.load(response)

        for path, body in (("status", None), ("pairing", {"open": True}), ("sensors", DETAILS),
                           ("readings", {}), ("preview", {}), ("confirm", {"confirm": True})):
            route = "/v1/climate/admin/" + path
            with self.subTest(path=path), self.assertRaises(HTTPError) as denied:
                request(route, body=body)
            self.assertEqual(denied.exception.code, 403)
        self.mqtt.publish.assert_not_called()
        with self.assertRaises(HTTPError) as plaintext:
            request("/v1/climate/admin/status", self.server, admin=True)
        self.assertEqual(plaintext.exception.code, 403)
        with self.assertRaises(HTTPError) as missing_read:
            request("/v1/climate/admin/status", read=False, admin=True)
        self.assertEqual(missing_read.exception.code, 401)
        self.assertEqual(request("/v1/climate/now")["sensors"][0]["name"], "Forge")
        self.assertEqual(request("/v1/climate/admin/status", admin=True)["sensors"][0]["name"], "Forge")
        self.assertIsNotNone(request("/v1/climate/admin/pairing", admin=True, body={"open": True})["pairing_until_ms"])
