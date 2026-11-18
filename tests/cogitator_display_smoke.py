"""Real Tk scenes, bounded animation and typing; run under xvfb on Linux."""
from datetime import datetime, timezone
import os
import json
from pathlib import Path
import tempfile
import time
import tkinter as tk
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from marsi_local.display import Display
from marsi_local.interludes import TYPES, build_interlude
from marsi_local.lore import Lore
from tests.test_interludes import fixture, NOW


class CogitatorDisplaySmoke(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        env = patch.dict(os.environ, {"MARSI_PI_STATE_DIR": folder.name, "MARSI_RITUALS": "false",
                                     "MARSI_SPEAK": "false", "MARSI_TYPEWRITER": "true", "MARSI_REDUCED_MOTION": "false"})
        env.start(); self.addCleanup(env.stop)
        self.root = tk.Tk(); self.root.withdraw()
        self.display = Display(self.root, SimpleNamespace(session="scene-test"), windowed=True)
        self.addCleanup(self.display.close)
        self.display.polling = self.display.link_online = True
        self.root.geometry("800x480-20000+0"); self.root.deiconify(); self.root.update()

    def packet(self, kind):
        packets = json.loads(Path(__file__).with_name("fixtures").joinpath("interludes.json").read_text(encoding="utf-8"))
        return next(packet for packet in packets if packet["type"] == kind)

    def test_six_scenes_fit_both_sizes_and_reuse_canvas_items(self):
        for width,height in ((800,480),(480,320)):
            self.root.geometry(f"{width}x{height}-20000+0"); self.root.update()
            for kind in TYPES:
                with self.subTest(size=(width,height),kind=kind):
                    self.display.show_interlude(self.packet(kind)); self.root.update()
                    view = self.display.interlude; view.draw(view.started+1)
                    canvas = self.display.interlude_canvas
                    items = canvas.find_all()
                    for frame in range(2,200):
                        view.draw(view.started+frame/15)
                        self.assertEqual(canvas.find_all(), items)
                    for item in items:
                        if canvas.type(item) != "text": continue
                        x1,y1,x2,y2 = canvas.bbox(item)
                        self.assertTrue(-1 <= x1 <= x2 <= canvas.winfo_width()+1, canvas.itemcget(item,"text"))
                        self.assertTrue(-1 <= y1 <= y2 <= canvas.winfo_height()+1, canvas.itemcget(item,"text"))
                    render_dir = os.getenv("MARSI_RENDER_DIR")
                    if render_dir and os.name == "nt":
                        # Import helpers without running the older module's smoke routine.
                        import ast
                        source = Path(__file__).with_name("pi_display_smoke.py").read_text(encoding="utf-8")
                        helper_tree = ast.Module(body=[node for node in ast.parse(source).body if isinstance(node,(ast.Import,ast.ImportFrom,ast.FunctionDef))],type_ignores=[])
                        helpers = {}; exec(compile(helper_tree,"screenshot-helpers","exec"),helpers)
                        destination = Path(render_dir); destination.mkdir(parents=True,exist_ok=True)
                        helpers["render_windows"](self.root,destination/f"pi-{kind}-{width}x{height}.png")
                    self.display.dismiss_interlude()

    def test_touch_dismissal_and_lenses_return_to_their_original_colour(self):
        self.display.show_interlude(self.packet("vox")); self.root.update()
        self.display.draw(time.monotonic())
        eye = self.display.effigy.eyes[0]["items"][0]
        self.assertEqual(self.display.canvas.itemcget(eye,"fill"),"#ffb000")
        self.display.interlude_canvas.event_generate("<ButtonPress-1>",x=20,y=20)
        self.root.update()
        self.assertIsNone(self.display.interlude)
        # Restoring controls may resize the portrait. Its renderer correctly
        # rebuilds on resize, so inspect the current lens rather than a deleted ID.
        self.root.update_idletasks()
        self.display.draw(time.monotonic())
        eye = self.display.effigy.eyes[0]["items"][0]
        self.assertEqual(self.display.canvas.itemcget(eye,"fill"),"#63d8df")

    def test_typewriter_reveals_only_new_marsi_text_and_restores_complete_text(self):
        at = datetime.now(timezone.utc).isoformat()
        text = ("A kind little answer from the machine archive. "*3).rstrip()
        self.display.receive_entries([{"id":1,"role":"human","kind":"chat","at":at,"text":"Hello"},
                                      {"id":2,"role":"marsi","kind":"chat","at":at,"text":text}])
        self.assertTrue(self.display.typer.jobs)
        for _ in range(40): self.display.typer.tick()
        self.assertFalse(self.display.typer.jobs)
        self.assertIn(text,self.display.reply.get("1.0","end"))
        self.assertNotIn("▌",self.display.reply.get("1.0","end"))
        self.display.receive_entries([{"id":3,"role":"marsi","kind":"chat","at":at,"text":"Old history."}],initial=True)
        self.assertFalse(self.display.typer.jobs)
        self.display.typer.reduced = True
        self.display.show_text("Reduced motion reply.","marsi")
        self.assertFalse(self.display.typer.jobs)
