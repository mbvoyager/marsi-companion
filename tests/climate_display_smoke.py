"""Exercise the real Tk climate tab with a synthetic live feed."""
import queue
import time
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

from marsi_local.display import Display


NOW = 1_800_000_000_000


def sample_snapshot(temperature=21.5):
    sensors = []
    for index, name in enumerate(("Forge", "Gate", "Workshop", "Archive")):
        at = NOW - 8_000_000 if index == 1 else NOW
        sensors.append({
            "id": f"demo-{index}", "name": name,
            "location": "outdoor" if index == 1 else "indoor", "color": None,
            "status": "stale" if index == 1 else "fresh", "last_measurement_ms": at,
            "readings": {
                "temperature": {"value": temperature - 5 * index, "observed_ms": at},
                "humidity": {"value": 50 + 7 * index, "observed_ms": at},
            },
        })
    return {"sensors": sensors, "stale_after_ms": 7_200_000, "generated_ms": NOW}


class ClimatePreviewClient:
    session = "climate-preview"

    def __init__(self):
        self.snapshots = queue.Queue()
        self.voice = Mock(return_value={"text": "The tiny vox received you. ^^", "source": "system"})

    def climate_events(self, stop):
        yield sample_snapshot()
        while not stop.is_set():
            try:
                yield self.snapshots.get(timeout=.05)
            except queue.Empty:
                pass

    def climate_history(self, period):
        hours, bucket = {"3h": (3, 0), "24h": (24, 300_000), "7d": (168, 1_800_000)}[period]
        start = NOW - hours * 3_600_000
        sensors = []
        for index, sensor in enumerate(sample_snapshot()["sensors"]):
            series = {}
            for metric, offset in (("temperature", 15 + index), ("humidity", 48 + index * 5)):
                series[metric] = [[start + 100_000, offset], [start + 1_800_000, offset + 2],
                                  [NOW - 500_000, offset + 1]]
            sensors.append({**sensor, "series": series})
        return {"range": period, "from_ms": start, "to_ms": NOW, "bucket_ms": bucket, "sensors": sensors}


class ClimateDisplaySmoke(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.client = ClimatePreviewClient()
        self.display = Display(self.root, self.client, windowed=True)
        self.addCleanup(self.display.close)
        self.display.polling = self.display.link_online = True
        self.root.geometry("800x480-20000+0")
        self.root.deiconify()
        self.root.update()
        self.panel = self.display.climate

    def pump_until(self, condition):
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            self.root.update()
            if condition():
                return
            time.sleep(.01)
        self.fail("Climate view did not update")

    def labels(self):
        c = self.panel.canvas
        return [c.itemcget(item, "text") for item in c.find_all() if c.type(item) == "text"]

    def check_text_fits(self):
        c = self.panel.canvas
        for item in c.find_all():
            if c.type(item) == "text":
                x1, y1, x2, y2 = c.bbox(item)
                self.assertTrue(0 <= x1 <= x2 <= c.winfo_width(), c.itemcget(item, "text"))
                self.assertTrue(0 <= y1 <= y2 <= c.winfo_height(), c.itemcget(item, "text"))

    def test_cards_and_three_history_views_fit_both_display_sizes(self):
        self.display.tab_buttons["climate"].invoke()
        self.pump_until(lambda: "[AUSSEN]" in self.labels())
        for width, height in ((800, 480), (480, 320)):
            self.root.geometry(f"{width}x{height}-20000+0")
            self.root.update()
            self.panel.tabs["now"].invoke()
            self.pump_until(lambda: not self.panel.dirty and len(self.panel.canvas.find_withtag("climate-card")) >= 2)
            self.assertIn("[AUSSEN]", self.labels())
            self.assertIn("SIGNAL ALT", self.labels())
            self.check_text_fits()
            for period in ("3h", "24h", "7d"):
                self.panel.tabs[period].invoke()
                self.pump_until(lambda: self.panel.history and not self.panel.dirty)
                self.assertEqual(self.panel.history["range"], period)
                self.assertIn("TEMPERATUR [°C]", self.labels())
                self.assertIn("LUFTFEUCHTE [% rF]", self.labels())
                self.assertIn("AUSSEN ALT / Gate", self.labels())
                self.assertGreaterEqual(len(self.panel.canvas.find_withtag("climate-trace")), 8)
                self.check_text_fits()

    def test_live_updates_and_f8_keep_the_chat_draft(self):
        self.display.show_text("An archived line.")
        self.display.input.insert(0, "Unsent draft")
        self.display.tab_buttons["climate"].invoke()
        self.pump_until(lambda: "21,5 °C" in self.labels())
        self.client.snapshots.put(sample_snapshot(23.4))
        self.pump_until(lambda: "23,4 °C" in self.labels())
        with patch("marsi_local.pi.record", return_value=b"test audio"):
            self.display.hotkey(None)
            self.pump_until(lambda: not self.display.busy)
        self.assertEqual(self.display.tab, "chat")
        self.client.voice.assert_called_once()
        self.assertTrue(self.display.talk.winfo_viewable())
        self.assertEqual(self.display.input.get(), "Unsent draft")
        self.assertIn("An archived line.", self.display.reply.get("1.0", "end"))
