"""Hold the Lite/X11 display awake while Marsi runs, then restore its settings."""
import logging
import os
import re
import subprocess


LOG = logging.getLogger(__name__)
LUMEN_WARNING = ("[LUMEN] The screen ward needs attention, little keeper. "
                 "See the screen-awake steps in docs/raspberry-pi.md.")


class ScreenAwake:
    def __init__(self):
        self.saver = self.dpms = None

    @staticmethod
    def xset(*arguments):
        return subprocess.run(["xset", *arguments], capture_output=True, text=True,
                              env={**os.environ, "LC_ALL": "C"}, timeout=2, check=True).stdout

    def start(self, backend):
        if backend != "x11":
            return None
        if os.getenv("WAYLAND_DISPLAY"):
            # Xwayland's settings cannot control the compositor's idle policy.
            LOG.warning("Screen ward: configure screen blanking in the Wayland desktop settings")
            return LUMEN_WARNING
        try:
            state = self.xset("q")
            saver = re.search(r"timeout:\s*(\d+)\s+cycle:\s*(\d+)", state)
            if saver is None:
                raise ValueError("Unknown xset screen-saver report")
            self.saver = saver.groups()
            dpms = re.search(r"DPMS is (Enabled|Disabled)", state)
            self.dpms = dpms.group(1) if dpms else None
            self.xset("s", "off")
            self.xset("s", "reset")
            if self.dpms is not None:
                if self.dpms == "Enabled":
                    self.xset("dpms", "force", "on")
                self.xset("-dpms")
            LOG.info("Screen ward: X11 blanking disabled while Marsi runs")
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            LOG.warning("Screen ward unavailable (%s); check x11-xserver-utils and X11 session access",
                        type(error).__name__)
            return LUMEN_WARNING
        return None

    def close(self):
        if self.saver is None:
            return
        try:
            self.xset("s", *self.saver)
            if self.dpms is not None:
                self.xset("+dpms" if self.dpms == "Enabled" else "-dpms")
        except (OSError, subprocess.SubprocessError) as error:
            LOG.warning("Could not restore X11 screen settings (%s)", type(error).__name__)
        finally:
            self.saver = self.dpms = None
