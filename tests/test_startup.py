"""Execute the installer's actual profile editor against a temporary home."""
from pathlib import Path
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


if __name__ == "__main__":
    unittest.main()
