"""Exercise the drawn reticle with real X11 pixels and mouse events."""
from ctypes import CDLL, c_int, c_uint, c_ulong, c_void_p
import os
import sys
import tkinter as tk
import unittest
from unittest.mock import patch

from marsi_local.drawn_pointer import load_xlib
from marsi_local.electoo import GREEN
from marsi_local.pointer import install_reticle


@unittest.skipUnless(sys.platform == "linux" and os.getenv("DISPLAY"), "Needs an X11 display")
class DrawnPointerTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {"WAYLAND_DISPLAY": "", "MARSI_CURSOR": ""})
        env.start()
        self.addCleanup(env.stop)
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)

    def test_drawn_pixels_follow_pointer_and_allow_clicks_and_selection(self):
        clicks = []
        button = tk.Button(self.root, text="A synthetic seal", command=lambda: clicks.append(True))
        button.pack(pady=8)
        entry = tk.Entry(self.root)
        entry.insert(0, "A synthetic transmission")
        entry.pack()
        self.assertEqual(install_reticle(self.root, drawn=True), "none")
        reticle = self.root.drawn_reticle
        self.root.geometry("320x140+30+40")
        self.root.deiconify()
        self.root.update()

        x11 = load_xlib()
        display = x11.XOpenDisplay(os.fsencode(self.root.winfo_screen()))
        self.assertTrue(display)
        self.addCleanup(x11.XCloseDisplay, display)
        xtest = CDLL("libXtst.so.6")
        xtest.XTestFakeMotionEvent.argtypes = [c_void_p, c_int, c_int, c_int, c_ulong]
        xtest.XTestFakeMotionEvent.restype = c_int
        xtest.XTestFakeButtonEvent.argtypes = [c_void_p, c_uint, c_int, c_ulong]
        xtest.XTestFakeButtonEvent.restype = c_int
        x11.XGetImage.argtypes = [c_void_p, c_ulong, c_int, c_int, c_uint, c_uint, c_ulong, c_int]
        x11.XGetImage.restype = c_void_p
        x11.XGetPixel.argtypes = [c_void_p, c_int, c_int]
        x11.XGetPixel.restype = c_ulong
        x11.XDestroyImage.argtypes = [c_void_p]
        x11.XDestroyImage.restype = c_int
        screen = x11.XDefaultScreen(display)
        parent = x11.XRootWindow(display, screen)

        def flush():
            x11.XSync(display, 0)
            self.root.update()
            reticle.x11.XSync(reticle.display, 0)

        def move(x, y):
            self.assertTrue(xtest.XTestFakeMotionEvent(display, screen, x, y, 0))
            flush()

        def press(down):
            self.assertTrue(xtest.XTestFakeButtonEvent(display, 1, down, 0))
            flush()

        def pixel(x, y):
            image = x11.XGetImage(display, parent, x, y, 1, 1, c_ulong(-1).value, 2)
            self.assertTrue(image)
            try:
                return x11.XGetPixel(image, 0, 0)
            finally:
                x11.XDestroyImage(image)

        x = button.winfo_rootx() + button.winfo_width() // 2
        y = button.winfo_rooty() + button.winfo_height() // 2
        corner = (x - reticle.hotspot[0], y - reticle.hotspot[1])
        background = pixel(*corner)
        move(x, y)
        self.assertTrue(reticle.visible)
        self.assertEqual(pixel(x, y), int(GREEN.lstrip("#"), 16), "The reticle must be painted on screen")
        self.assertEqual(pixel(*corner), background, "The reticle's transparent gaps must stay transparent")
        press(True)
        press(False)
        self.assertEqual(clicks, [True], "The drawn reticle must let a real click reach the button")

        start_x, start_y, _, height = entry.bbox(1)
        end_x, _, _, _ = entry.bbox(9)
        entry_y = entry.winfo_rooty() + start_y + height // 2
        move(entry.winfo_rootx() + start_x, entry_y)
        press(True)
        move(entry.winfo_rootx() + end_x, entry_y)
        press(False)
        self.assertTrue(entry.selection_present(), "Dragging through the reticle must select text")
        move(self.root.winfo_screenwidth() - 2, self.root.winfo_screenheight() - 2)
        self.assertFalse(reticle.visible, "Hide the reticle outside Marsi's windows")

    def test_missing_overlay_library_keeps_the_native_cursor(self):
        with patch("marsi_local.drawn_pointer.CDLL", side_effect=OSError("Synthetic missing library")):
            cursor = install_reticle(self.root, drawn=True)
        self.assertTrue(str(cursor).startswith("@"))
        self.assertFalse(hasattr(self.root, "drawn_reticle"))


if __name__ == "__main__":
    unittest.main()
