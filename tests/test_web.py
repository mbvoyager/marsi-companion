"""Serve the local browser shell through the normal Marsi API process."""
from pathlib import Path
import tempfile
import threading
import unittest

from marsi_local.client import Client, ClientError
from marsi_local.config import ServerConfig
from marsi_local.core import Companion
from marsi_local.server import Server, WEB_ASSETS


class BrowserRoutes(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        config = ServerConfig(demo=True, token="test-web-token-" * 3, database=Path(folder.name) / "archive.db")
        app = Companion(config)
        app.memory.remember_turn("pi", "A test signal", "The forge hears you.")
        server = Server(("127.0.0.1", 0), app)
        self.addCleanup(server.server_close)
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 2)
        self.addCleanup(server.shutdown)
        self.api = Client(f"http://127.0.0.1:{server.server_port}", token=config.token, timeout=3)

    def test_web_assets_load_without_credentials_and_keep_same_origin_policy(self):
        for route, (_name, mime) in WEB_ASSETS.items():
            with self.subTest(route=route), self.api.http.open(self.api.url + route, timeout=3) as response:
                self.assertEqual(response.headers["Content-Type"], mime)
                self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])
                self.assertEqual(response.headers["Referrer-Policy"], "no-referrer")
                body = response.read()
                self.assertNotIn(self.api.token.encode(), body)
                self.assertGreater(len(body), 0)
                if route == "/":
                    self.assertIn(b'id="gate-form"', body)
                    self.assertIn(b'id="climate"', body)

    def test_journal_remains_authenticated_and_files_outside_allowlist_are_inaccessible(self):
        with self.assertRaises(ClientError) as rejected:
            Client(self.api.url, timeout=3).journal()
        self.assertEqual(rejected.exception.status, 401)
        self.assertEqual(self.api.journal()["entries"][0]["text"], "A test signal")
        for path in ("/.env.server", "/web/../server.py", "/web/%2e%2e/server.py"):
            with self.assertRaises(ClientError) as missing:
                self.api.request(path, method="GET")
            self.assertEqual(missing.exception.status, 404)
