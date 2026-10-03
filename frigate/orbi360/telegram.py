"""Telegram alerts for Orbi360 NVR.

Settings live in /config/orbi360/telegram.json. The mosaic services read a
shell version of them, /config/orbi360/telegram.env, each time they need to
send an alert, so changes apply without restarting them. Both files hold the
bot token and are written with mode 600.
"""

import json
import logging
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from pydantic import BaseModel, Field, field_validator

from frigate.const import CONFIG_DIR

logger = logging.getLogger(__name__)

SETTINGS_DIR = Path(CONFIG_DIR) / "orbi360"
SETTINGS_FILE = SETTINGS_DIR / "telegram.json"
ENV_FILE = SETTINGS_DIR / "telegram.env"

TOKEN_PATTERN = re.compile(r"^\d{5,15}:[A-Za-z0-9_-]{30,64}$")
# Numeric chat id (negative for groups) or a public @channel name
CHAT_ID_PATTERN = re.compile(r"^(-?\d{1,20}|@[A-Za-z0-9_]{5,32})$")


class TelegramSettings(BaseModel):
    enabled: bool = False
    bot_token: str | None = None
    chat_id: str | None = None
    alert_after_s: int = Field(
        default=60,
        ge=10,
        le=3600,
        description="How long a problem must last before alerting",
    )

    @field_validator("bot_token")
    @classmethod
    def validate_token(cls, value: str | None) -> str | None:
        if value in (None, ""):
            return None
        if not TOKEN_PATTERN.match(value):
            raise ValueError(
                "the bot token does not look valid (format 123456789:ABC..., from @BotFather)"
            )
        return value

    @field_validator("chat_id")
    @classmethod
    def validate_chat_id(cls, value: str | None) -> str | None:
        if value in (None, ""):
            return None
        if not CHAT_ID_PATTERN.match(value):
            raise ValueError(
                "the chat ID must be a number (e.g. 123456789) or @channel"
            )
        return value

    def public(self) -> dict:
        """Settings for the web UI: never includes the token itself."""
        return {
            "enabled": self.enabled,
            "chat_id": self.chat_id,
            "alert_after_s": self.alert_after_s,
            "token_set": self.bot_token is not None,
        }


def load() -> TelegramSettings:
    if not SETTINGS_FILE.exists():
        return TelegramSettings()
    return TelegramSettings.model_validate_json(SETTINGS_FILE.read_text())


def merge(body: dict) -> TelegramSettings:
    """Apply changes from the UI. An empty bot_token keeps the stored one, so the
    token never has to travel back to the browser."""
    current = load()
    data = {**current.model_dump(), **body}
    if not body.get("bot_token"):
        data["bot_token"] = current.bot_token
    return TelegramSettings.model_validate(data)


def _write_private(path: Path, content: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(content)
    os.chmod(tmp, 0o600)
    tmp.replace(path)


def render_env(settings: TelegramSettings) -> str:
    """Shell file sourced by orbi360-mosaico. Values are validated, so safe to quote."""
    return "\n".join(
        [
            "# Generado por Orbi360 NVR (Ajustes > Mosaico SRT > Avisos por Telegram)",
            f"TELEGRAM_ENABLED={1 if settings.enabled else 0}",
            f"TELEGRAM_BOT_TOKEN='{settings.bot_token or ''}'",
            f"TELEGRAM_CHAT_ID='{settings.chat_id or ''}'",
            f"ALERT_AFTER={settings.alert_after_s}",
            "",
        ]
    )


def save(settings: TelegramSettings) -> None:
    SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    _write_private(SETTINGS_FILE, settings.model_dump_json(indent=2))
    _write_private(ENV_FILE, render_env(settings))


def send(settings: TelegramSettings, text: str) -> str | None:
    """Send a message. Returns None on success or the reason it failed."""
    if not settings.bot_token or not settings.chat_id:
        return "the bot token and the chat ID are required"
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{settings.bot_token}/sendMessage",
        data=urllib.parse.urlencode(
            {"chat_id": settings.chat_id, "text": text}
        ).encode(),
    )
    try:
        with urllib.request.urlopen(request, timeout=15):
            return None
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read()).get("description") or str(e)
        except ValueError:
            return str(e)
    except (urllib.error.URLError, TimeoutError) as e:
        # never include the request URL: it carries the token
        return f"no connection to Telegram ({getattr(e, 'reason', e)})"
