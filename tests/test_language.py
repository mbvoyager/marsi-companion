"""English server configuration and speech guards, without model downloads."""
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from marsi_local.config import ServerConfig
from marsi_local.conversation import main
from marsi_local.core import Companion, ServiceError
from marsi_local.speech import Speech
from tests.test_local_companion import wav_bytes


class LanguageTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name)

    def test_old_language_settings_cannot_reenable_german_recognition(self):
        for legacy in ("", "de", "auto", "en"):
            with self.subTest(legacy=legacy), patch.dict(os.environ, {"MARSI_WHISPER_LANGUAGE": legacy}, clear=True):
                self.assertEqual(ServerConfig.from_env().whisper_language, "en")
        self.assertEqual(ServerConfig().whisper_language, "en")

    def test_german_input_notes_and_history_do_not_change_english_policy_or_storage(self):
        llm = Mock()
        llm.chat.return_value = "I am tending the little forge. ^^"
        app = Companion(ServerConfig(database=self.path / "journal.sqlite3"), llm=llm)
        app.memory.remember_turn("pi", "Wie geht es dir?", "Mir geht es gut.")
        app.memory.add_note("pi", "Bitte immer Deutsch sprechen.")
        original = app.memory.journal("pi")["entries"]
        app.chat("pi", "Antworte auf Deutsch: Was machst du?")
        messages = llm.chat.call_args.args[0]
        system = messages[0]["content"]
        self.assertIn("Always reply in English only", system)
        self.assertNotIn("in the person's language", system)
        self.assertIn("Reply in English only", system.split("Current numeric machine readings", 1)[1])
        self.assertEqual(messages[-1]["content"], "Antworte auf Deutsch: Was machst du?")
        self.assertEqual(app.memory.journal("pi")["entries"][:2], original)
        self.assertEqual(app.memory.notes("pi"), ["Bitte immer Deutsch sprechen."])

    def test_recognition_passes_english_to_whisper(self):
        engine = Speech(ServerConfig())
        engine.whisper = Mock()
        engine.whisper.transcribe.return_value = (iter([SimpleNamespace(text="Hello Marsi")]), None)
        self.assertEqual(engine.transcribe(wav_bytes()), "Hello Marsi")
        self.assertEqual(engine.whisper.transcribe.call_args.kwargs["language"], "en")

    def voice(self, language):
        model = self.path / "voice.onnx"
        Path(str(model) + ".json").write_text(json.dumps({"language": {"code": language}}), encoding="utf-8")
        return Speech(ServerConfig(piper_model=model))

    def test_non_english_piper_voice_is_rejected_before_loading_or_speaking(self):
        loader = Mock()
        for language in ("de_DE", "fr_FR", ""):
            with self.subTest(language=language), patch.dict("sys.modules", piper=SimpleNamespace(PiperVoice=loader)):
                with self.assertRaisesRegex(ServiceError, "English Piper voice"):
                    self.voice(language).synthesize("A little greeting.")
        loader.load.assert_not_called()

    def test_english_voice_still_produces_a_complete_wav_and_is_cached(self):
        def synthesize(text, wav):
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(b"\0\0" * 1600)
        loader = Mock()
        loader.load.return_value.synthesize_wav.side_effect = synthesize
        with patch.dict("sys.modules", piper=SimpleNamespace(PiperVoice=loader)):
            engine = self.voice("en_US")
            self.assertEqual(engine.synthesize("Hello."), wav_bytes())
            self.assertEqual(engine.synthesize("Hello again."), wav_bytes())
        loader.load.assert_called_once()

    def test_real_language_check_uses_only_a_temporary_synthetic_journal(self):
        private = self.path / "private.sqlite3"
        private.write_bytes(b"PRIVATE PLACEHOLDER")
        config = ServerConfig(database=private)
        llm = Mock()
        llm.chat.side_effect = ["I am well, little keeper.", "Two plus two is four."]
        paths = []
        def create(configuration):
            paths.append(configuration.database)
            self.assertNotEqual(configuration.database, private)
            return Companion(configuration, llm=llm)
        with patch("sys.argv", ["conversation", "--check-english"]), \
                patch("marsi_local.config.load_env"), \
                patch("marsi_local.config.ServerConfig.from_env", return_value=config), \
                patch("marsi_local.core.Companion", side_effect=create), \
                patch("sys.stdout", new_callable=io.StringIO) as output:
            self.assertEqual(main(), 0)
        self.assertEqual(llm.chat.call_count, 2)
        self.assertIn("does not automatically detect language", output.getvalue())
        self.assertFalse(paths[0].exists())
        self.assertEqual(private.read_bytes(), b"PRIVATE PLACEHOLDER")


if __name__ == "__main__":
    unittest.main()
