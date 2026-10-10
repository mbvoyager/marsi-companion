"""Execute the installer's actual profile editor against a temporary home."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from marsi_local.config import ROOT


class StartupTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.home = Path(self.folder.name)
        source = (ROOT / "scripts" / "install-pi-autostart.sh").read_text(encoding="utf-8")
        self.editor = source.split("python3 - <<'PY'\n", 1)[1].split("\nPY", 1)[0]
        self.profile = self.home / ".profile"

    def install(self):
        with patch("pathlib.Path.home", return_value=self.home):
            exec(compile(self.editor, "install-pi-autostart.sh:profile-editor", "exec"), {})

    def test_repeat_install_preserves_profile_and_first_backup(self):
        original = "# My settings\nexport EDITOR=nano\n"
        self.profile.write_text(original)
        self.install()
        first = self.profile.read_text()
        self.install()
        self.assertEqual(self.profile.read_text(), first)
        self.assertIn("export EDITOR=nano", first)
        self.assertEqual(first.count("# BEGIN MARSI DISPLAY"), 1)
        self.assertIn('"$(tty)" = /dev/tty1', first)
        self.assertEqual((self.home / ".profile.before-marsi").read_text(), original)

    def test_exact_legacy_entry_is_replaced_without_duplicate_startx(self):
        old = '''# Existing setting
if [ -z "$DISPLAY" ] && [ "$(tty)" = /dev/tty1 ]; then
    startx "$HOME/marsi-companion/deploy/marsi-xsession.sh" -- -nocursor
fi
'''
        self.profile.write_text(old)
        self.install()
        self.assertEqual(self.profile.read_text().count("startx "), 1)
        self.assertIn("# Existing setting", self.profile.read_text())
        self.assertEqual((self.home / ".profile.before-marsi").read_text(), old)

    def test_custom_entry_and_malformed_markers_are_left_for_inspection(self):
        for original in ('startx ~/marsi-companion/deploy/marsi-xsession.sh -- :1\n',
                         '# BEGIN MARSI DISPLAY\nmissing end marker\n'):
            self.profile.write_text(original)
            with self.assertRaises(SystemExit):
                self.install()
            self.assertEqual(self.profile.read_text(), original)

    def test_empty_home_gets_a_single_guarded_entry(self):
        self.install()
        self.assertEqual(self.profile.read_text().count("startx "), 1)
        self.assertIn('[ -z "$DISPLAY" ]', self.profile.read_text())


@unittest.skipUnless(sys.platform == "linux" and os.geteuid() != 0, "Needs a normal Linux user and Bash")
class StartupShellTests(unittest.TestCase):
    def test_lite_installer_enables_autologin_only_when_requested(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            project = home / "marsi-companion"
            (project / "scripts").mkdir(parents=True)
            (project / "deploy").mkdir()
            script = project / "scripts" / "install-pi-autostart.sh"
            shutil.copy2(ROOT / "scripts" / script.name, script)
            (project / "deploy" / "marsi-xsession.sh").write_text("#!/bin/sh\nexit 0\n")
            commands = home / "bin"
            commands.mkdir()
            log = home / "calls.txt"
            for name in ("sudo", "raspi-config"):
                stub = commands / name
                stub.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$MARSI_TEST_CALLS"\n')
                stub.chmod(0o700)
            env = {**os.environ, "HOME": str(home), "PATH": str(commands) + ":" + os.environ["PATH"],
                   "MARSI_TEST_CALLS": str(log)}
            subprocess.run(["bash", str(script), "--lite"], env=env, check=True, capture_output=True)
            self.assertFalse(log.exists(), "Default install must leave OS login settings alone")
            subprocess.run(["bash", str(script), "--lite", "--enable-autologin"],
                           env=env, check=True, capture_output=True)
            self.assertEqual(log.read_text().splitlines(), ["raspi-config nonint do_boot_behaviour B2"])
            self.assertEqual((home / ".profile").read_text().count("# BEGIN MARSI DISPLAY"), 1)


if __name__ == "__main__":
    unittest.main()
