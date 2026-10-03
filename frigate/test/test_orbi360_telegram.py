import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

from frigate.orbi360 import telegram

TOKEN = "123456789:AAH-abcdefghijklmnopqrstuvwxyz012345"


class TestTelegramSettings(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.patches = [
            patch.object(telegram, "SETTINGS_DIR", base),
            patch.object(telegram, "SETTINGS_FILE", base / "telegram.json"),
            patch.object(telegram, "ENV_FILE", base / "telegram.env"),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_validation(self):
        telegram.TelegramSettings(bot_token=TOKEN, chat_id="-1001234567890")
        telegram.TelegramSettings(bot_token=TOKEN, chat_id="@orbi360_avisos")
        for bad in (
            {"bot_token": "abc"},
            {"bot_token": TOKEN + "'; reboot"},
            {"chat_id": "12 34"},
            {"chat_id": "$(id)"},
            {"alert_after_s": 5},
        ):
            with self.assertRaises(ValidationError, msg=bad):
                telegram.TelegramSettings(**bad)

    def test_save_is_private_and_public_hides_token(self):
        settings = telegram.TelegramSettings(
            enabled=True, bot_token=TOKEN, chat_id="42", alert_after_s=90
        )
        telegram.save(settings)
        env = telegram.ENV_FILE.read_text()
        self.assertIn("TELEGRAM_ENABLED=1", env)
        self.assertIn(f"TELEGRAM_BOT_TOKEN='{TOKEN}'", env)
        self.assertIn("ALERT_AFTER=90", env)
        if os.name == "posix":
            for path in (telegram.ENV_FILE, telegram.SETTINGS_FILE):
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(telegram.load(), settings)
        public = settings.public()
        self.assertTrue(public["token_set"])
        self.assertNotIn(TOKEN, str(public))

    def test_empty_token_keeps_the_stored_one(self):
        telegram.save(telegram.TelegramSettings(bot_token=TOKEN, chat_id="42"))
        merged = telegram.merge({"enabled": True, "chat_id": "99", "bot_token": ""})
        self.assertEqual(merged.bot_token, TOKEN)
        self.assertEqual(merged.chat_id, "99")
        self.assertTrue(merged.enabled)

    def test_send_requires_settings(self):
        self.assertIsNotNone(telegram.send(telegram.TelegramSettings(), "hola"))


if __name__ == "__main__":
    unittest.main()
