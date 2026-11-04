"""Verify real X11 settings under xvfb, including restoration after the app."""
import os
import re
import shutil
import sys
import unittest

from marsi_local.screen import ScreenAwake


@unittest.skipUnless(sys.platform == "linux" and os.getenv("DISPLAY") and shutil.which("xset"),
                     "Needs Linux, an X11 display and xset")
class ScreenSmokeTests(unittest.TestCase):
    def test_actual_x11_settings_are_disabled_and_restored(self):
        screen = ScreenAwake()
        def saver(report):
            return re.search(r"timeout:\s*(\d+)\s+cycle:\s*(\d+)", report).groups()
        original = screen.xset("q")
        try:
            self.assertIsNone(screen.start("x11"))
            active = screen.xset("q")
            self.assertEqual(saver(active)[0], "0")
            self.assertNotIn("DPMS is Enabled", active)
        finally:
            screen.close()
        restored = screen.xset("q")
        self.assertEqual(saver(restored), saver(original))
        for state in ("DPMS is Enabled", "DPMS is Disabled"):
            self.assertEqual(state in restored, state in original)


if __name__ == "__main__":
    unittest.main()
