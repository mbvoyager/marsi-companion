"""Exercise real Tk widgets without audio devices or a network connection."""
from datetime import datetime
import os
from pathlib import Path
import tempfile
import time
import tkinter as tk
from tkinter import font as tkfont
from unittest.mock import Mock, patch

from marsi_local.liturgy import BLACK, GREEN, RED, artwork
from marsi_local.electoo import BONE, BRASS
from marsi_local.pi import Display
from marsi_local.audio import AudioError


class PreviewClient:
    session = "display-test"

    def __init__(self):
        self.chat = Mock(return_value={"text": "A kind little cog. ^^", "source": "system"})
        self.art = Mock(return_value=artwork({"server": {"load1": 0.42, "temperature_c": 43.0}}, "preview"))
        self.sermon = self.ritual = self.art

    def telemetry(self, readings):
        return {"pi": readings, "server": None}

    def journal(self, **kwargs):
        return {"entries": [], "has_more": False}


def canvas_image(canvas):
    """Render the test canvas's actual cached items, including hidden eyelids."""
    from PIL import Image, ImageDraw, ImageFont
    layer = Image.new("RGB", (canvas.winfo_width(), canvas.winfo_height()), canvas.cget("bg"))
    draw = ImageDraw.Draw(layer)
    for item in canvas.find_all():
        if canvas.itemcget(item, "state") == "hidden":
            continue
        coords = canvas.coords(item)
        kind = canvas.type(item)
        color = canvas.itemcget(item, "fill")
        outline = canvas.itemcget(item, "outline") if kind in ("rectangle", "oval", "polygon") else ""
        if kind == "rectangle":
            draw.rectangle(coords, fill=color or None, outline=outline or None)
        elif kind == "oval":
            draw.ellipse(coords, fill=color or None, outline=outline or None,
                         width=max(1, round(float(canvas.itemcget(item, "width")))))
        elif kind == "line":
            draw.line(list(zip(coords[::2], coords[1::2])), fill=color,
                      width=max(1, round(float(canvas.itemcget(item, "width")))))
        elif kind == "polygon":
            draw.polygon(list(zip(coords[::2], coords[1::2])), fill=color or None, outline=outline or None)
        elif kind == "text":
            actual = tkfont.Font(font=canvas.itemcget(item, "font")).actual()
            pixels = round(canvas.winfo_fpixels(f"{actual['size']}p"))
            face = ImageFont.truetype("C:/Windows/Fonts/cour.ttf", max(6, pixels))
            draw.multiline_text(canvas.bbox(item)[:2], canvas.itemcget(item, "text"),
                                fill=color, font=face, spacing=0)
    return layer


def render_windows(root, destination):
    """Render this off-screen test window alone; never capture the desktop."""
    import ctypes
    from ctypes import wintypes
    from PIL import Image, ImageDraw, ImageFont
    user, gdi = ctypes.windll.user32, ctypes.windll.gdi32
    user.GetDC.argtypes, user.GetDC.restype = [wintypes.HWND], wintypes.HDC
    user.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    user.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
    gdi.CreateCompatibleDC.argtypes, gdi.CreateCompatibleDC.restype = [wintypes.HDC], wintypes.HDC
    gdi.CreateCompatibleBitmap.argtypes, gdi.CreateCompatibleBitmap.restype = [wintypes.HDC, ctypes.c_int, ctypes.c_int], wintypes.HANDLE
    gdi.SelectObject.argtypes, gdi.SelectObject.restype = [wintypes.HDC, wintypes.HANDLE], wintypes.HANDLE
    gdi.GetBitmapBits.argtypes = [wintypes.HANDLE, ctypes.c_long, ctypes.c_void_p]
    gdi.DeleteObject.argtypes = [wintypes.HANDLE]
    gdi.DeleteDC.argtypes = [wintypes.HDC]
    handle = root.winfo_id()
    width, height = root.winfo_width(), root.winfo_height()
    dc = user.GetDC(handle)
    memory = gdi.CreateCompatibleDC(dc)
    bitmap = gdi.CreateCompatibleBitmap(dc, width, height)
    old = gdi.SelectObject(memory, bitmap)
    try:
        assert user.PrintWindow(handle, memory, 1), "Could not render test window"
        buffer = ctypes.create_string_buffer(width * height * 4)
        assert gdi.GetBitmapBits(bitmap, len(buffer), buffer), "Could not read test rendering"
        image = Image.frombytes("RGB", (width, height), buffer.raw, "raw", "BGRX", 0, 1)
        # Off-screen Tk Text/Canvas do not implement WM_PRINTCLIENT on Windows.
        # Render their real laid-out glyphs/items into the window preview.
        def visit(widget):
            if isinstance(widget, (tk.Text, tk.Canvas)):
                layer = Image.new("RGB", (widget.winfo_width(), widget.winfo_height()), widget.cget("bg"))
                draw = ImageDraw.Draw(layer)
                def font(spec):
                    actual = tkfont.Font(font=spec).actual()
                    pixels = round(root.winfo_fpixels(f"{actual['size']}p"))
                    return ImageFont.truetype("C:/Windows/Fonts/cour.ttf", max(6, pixels))
                if isinstance(widget, tk.Text):
                    face = font(widget.cget("font"))
                    index = "1.0"
                    while widget.compare(index, "<", "end-1c"):
                        box = widget.bbox(index)
                        character = widget.get(index)
                        if box and character not in "\n\t":
                            tags = widget.tag_names(index)
                            color = GREEN if "human" in tags else BRASS if "system" in tags else BONE
                            draw.text(box[:2], character, fill=color, font=face)
                        index = widget.index(index + "+1c")
                else:
                    layer = canvas_image(widget)
                image.paste(layer, (widget.winfo_rootx() - root.winfo_rootx(), widget.winfo_rooty() - root.winfo_rooty()))
            for child in widget.winfo_children():
                visit(child)
        visit(root)
        image.save(destination)
    finally:
        gdi.SelectObject(memory, old)
        gdi.DeleteObject(bitmap)
        gdi.DeleteDC(memory)
        user.ReleaseDC(handle, dc)


with tempfile.TemporaryDirectory() as state:
    with patch.dict(os.environ, {"MARSI_PI_STATE_DIR": state}):
        root = tk.Tk()
        root.withdraw()
        client = PreviewClient()
        display = Display(root, client, windowed=True)
        root.geometry("800x480-20000+0")
        root.deiconify()
        readings = {"cpu_percent": 12, "load1": 0.42, "ram_used_mb": 220, "ram_total_mb": 920,
                    "temperature_c": 43, "disk_used_percent": 21, "cpu_count": 4}
        display.readings = {"pi": readings, "server": dict(readings, ram_total_mb=7800, ram_used_mb=2100)}
        now = datetime.now().astimezone().isoformat()
        display.receive_entries([
            {"id": 1, "at": now, "kind": "chat", "role": "human", "text": "Where are you, MARSI?"},
            {"id": 2, "at": now, "kind": "chat", "role": "marsi", "text": "Beneath a forge cathedral on Mars, little keeper. The machine flow carries your Terra's words into my reliquary. What have you observed today?"},
            {"id": 3, "at": now, "kind": "art", "role": "marsi", "text": client.art()["text"]},
        ], initial=True)
        display.polling = True
        for width, height in ((800, 480), (480, 320)):
            root.geometry(f"{width}x{height}-20000+0")
            root.update()
            display.status.set("[PREVIEW] Sample data / ARCHIVUM MARTIS / F8 = TALK")
            for mode in ("idle", "listening", "thinking", "speaking"):
                display.mode = mode
                display.draw(123.4)
                root.update()
                # Updating readings and mode labels can resize the canvas during
                # Tk's layout pass. Repaint at that settled size before checking
                # that subsequent animation frames reuse the static artwork.
                display.draw(123.4)
                assert display.electoos[-1].key == (display.canvas.winfo_width(), display.canvas.winfo_height())
                assert display.canvas.find_all(), "ASCII character should be visible"
                assert display.reply.winfo_height() > 100, "Archive must remain useful"
                assert display.talk.winfo_viewable(), "Talk must be visible"
                assert display.meter_label.winfo_rooty() + display.meter_label.winfo_height() <= root.winfo_rooty() + height - 40, "Readings should fit above controls"
                assert display.talk.winfo_rootx() + display.talk.winfo_width() <= root.winfo_rootx() + width, "Talk must fit horizontally"
                font = tkfont.Font(font=display.reply.cget("font"))
                assert font.measure("+" + "=" * 38 + "+") < display.reply.winfo_width() - 16, "ASCII art should not wrap"
                assert display.reply.cget("bg") == BLACK
                assert display.reply.tag_cget("human", "foreground") == GREEN
                assert display.reply.tag_cget("marsi", "foreground") == BONE
                ids = display.canvas.find_all()
                signals = [display.canvas.coords(item) for item in display.electoos[-1].signals]
                display.draw(124.4)
                assert display.canvas.find_all() == ids, "Static artwork should be cached on the Pi"
                assert signals != [display.canvas.coords(item) for item in display.electoos[-1].signals], "Signals should move"
            adept = display.electoos[-1]
            adept.draw(11.3, "idle")
            assert all(display.canvas.itemcget(eye["items"][0], "state") == "hidden" for eye in adept.eyes), "The lenses must actually blink"
            adept.draw(12.3, "idle")
            assert all(display.canvas.itemcget(eye["items"][0], "state") == "normal" for eye in adept.eyes), "The lenses must reopen"
            adept.draw(12.3, "listening")
            listening = display.canvas.coords(adept.eyes[0]["items"][0])
            adept.draw(12.3, "thinking")
            assert display.canvas.coords(adept.eyes[0]["items"][0]) != listening, "Gaze must respond to the conversation state"
            render_dir = os.getenv("MARSI_RENDER_DIR")
            if render_dir and os.name == "nt":
                destination = Path(render_dir)
                destination.mkdir(parents=True, exist_ok=True)
                display.reply.yview_moveto(0)
                root.update()
                display.mode = "idle"
                display.draw(124.4)
                render_windows(root, destination / f"terminal-{width}x{height}.png")
        if os.getenv("MARSI_RENDER_DIR") and os.name == "nt":
            from marsi_local.electoo import Electoo
            portrait = tk.Toplevel(root)
            portrait.withdraw()
            portrait.geometry("320x370-20000+0")
            canvas = tk.Canvas(portrait, width=320, height=370, bg=BLACK, highlightthickness=0)
            canvas.pack(fill="both", expand=True)
            portrait.deiconify()
            root.update()
            adept = Electoo(canvas, display.mono, "effigy")
            frames = []
            for i in range(56):
                mode = ("idle", "listening", "thinking", "speaking")[i//14]
                adept.draw(1+i*.2, mode)
                frames.append(canvas_image(canvas))
            frames[0].save(destination / "marsi-effigy.gif", save_all=True, append_images=frames[1:],
                           duration=200, loop=0, disposal=2)
            adept.draw(2.4, "idle")
            canvas_image(canvas).save(destination / "marsi-effigy.png")
            portrait.destroy()
        display.show_text("One archived line.")
        display.show_text("Another archived line.")
        assert "One archived line." in display.reply.get("1.0", "end")
        display.receive_entries([{"id": 4, "at": now, "kind": "sermon", "role": "marsi",
                                  "text": "A manual little sermon.", "spoken_text": "A manual little sermon.", "scheduled": 0}])
        assert display.pending_spoken is None, "Manual sermons must not be automatically replayed"
        display.events.put(("audio_status", ["Microphone route unavailable."]))
        display.tick()
        assert "Microphone route unavailable" in display.reply.get("1.0", "end")
        with patch("marsi_local.pi.play", side_effect=AudioError("ALSA test playback failure")):
            display.worker(lambda: {"text": "A little reply.", "audio_base64": "AA=="}, True)
        display.tick()
        assert "ALSA test playback failure" in display.reply.get("1.0", "end"), "Playback diagnostics must remain visible"
        display.worker(Mock(side_effect=AudioError("PortAudio test capture failure")), False)
        display.tick()
        assert "PortAudio test capture failure" in display.reply.get("1.0", "end"), "Capture errors must identify the audio layer"
        client.art.reset_mock()
        display.start_task = Mock()
        display.input.insert(0, "art")
        display.send_text()
        display.start_task.call_args.args[0]()
        client.art.assert_called_once()
        client.chat.assert_not_called()
        display.start_task.reset_mock()
        display.input.insert(0, "Tell me about art")
        display.send_text()
        display.start_task.call_args.args[0]()
        client.chat.assert_called_once()
        with patch.object(display, "toggle_record") as toggle:
            display.hotkey(None)
            display.hotkey(None)
            toggle.assert_called_once()
            display.release_hotkey(None)
            time.sleep(0.05)
            root.update()
            display.hotkey(None)
            assert toggle.call_count == 2
        display.input.insert(0, "exit")
        display.send_text()
        assert display.closed, "Exit must close locally"
print("Pi archive display passed at 800x480 and 480x320, including commands and F8.")
