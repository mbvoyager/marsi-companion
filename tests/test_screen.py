"""Screen settings are temporary, and unavailable power controls are nonfatal."""
import os
import subprocess
import unittest
from unittest.mock import call, patch

from marsi_local.screen import LUMEN_WARNING, ScreenAwake


class ScreenTests(unittest.TestCase):
    def test_x11_disables_blanking_and_dpms_and_restores_exact_previous_saver(self):
        for dpms in ("Enabled", "Disabled", None):
            with self.subTest(dpms=dpms), patch.dict(os.environ, {}, clear=True):
                screen = ScreenAwake()
                state = "Screen Saver:\n timeout: 600 cycle: 300\n"
                state += "DPMS is " + dpms if dpms else "Server does not have the DPMS Extension"
                with patch.object(screen, "xset", side_effect=[state] + [""] * 8) as xset:
                    self.assertIsNone(screen.start("x11"))
                    screen.close()
                    screen.close()
                expected = [call("q"), call("s", "off"), call("s", "reset")]
                if dpms == "Enabled":
                    expected += [call("dpms", "force", "on")]
                if dpms:
                    expected += [call("-dpms")]
                expected += [call("s", "600", "300")]
                if dpms:
                    expected += [call("+dpms" if dpms == "Enabled" else "-dpms")]
                self.assertEqual(xset.call_args_list, expected)

    def test_missing_xset_and_unknown_query_do_not_modify_settings(self):
        for failure in (FileNotFoundError(), subprocess.TimeoutExpired("xset", 2), "unknown report"):
            screen = ScreenAwake()
            with self.subTest(failure=type(failure).__name__), patch.dict(os.environ, {}, clear=True), \
                    patch.object(screen, "xset") as xset:
                if isinstance(failure, str):
                    xset.return_value = failure
                else:
                    xset.side_effect = failure
                self.assertEqual(screen.start("x11"), LUMEN_WARNING)
                screen.close()
                xset.assert_called_once_with("q")

    def test_partial_failure_can_still_restore_screensaver_on_exit(self):
        screen = ScreenAwake()
        with patch.dict(os.environ, {}, clear=True), \
                patch.object(screen, "xset", side_effect=["timeout: 600 cycle: 300", "",
                                                        subprocess.CalledProcessError(1, "xset"), ""]) as xset:
            self.assertEqual(screen.start("x11"), LUMEN_WARNING)
            screen.close()
        self.assertEqual(xset.call_args_list[-1], call("s", "600", "300"))

    def test_wayland_needs_its_own_idle_settings_and_non_x11_development_is_unchanged(self):
        with patch.object(ScreenAwake, "xset") as xset:
            self.assertIsNone(ScreenAwake().start("win32"))
            self.assertIsNone(ScreenAwake().start("aqua"))
            with patch.dict(os.environ, {"WAYLAND_DISPLAY": "wayland-test"}):
                self.assertEqual(ScreenAwake().start("x11"), LUMEN_WARNING)
        xset.assert_not_called()


if __name__ == "__main__":
    unittest.main()
