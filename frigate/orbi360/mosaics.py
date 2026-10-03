"""SRT mosaic outputs.

Each mosaic tiles 1 to 9 go2rtc streams into a grid and publishes it as an
SRT listener. Mosaics are stored in /config/orbi360/mosaics.json and run as
instances of the systemd template unit ``orbi360-mosaico@<id>.service``
(installed by orbi360/lxc/install.sh), each reading its own shell config from
/config/orbi360/mosaics/<id>.conf.

Usage from the installer::

    python3 -m frigate.orbi360.mosaics migrate   # import /etc/orbi360-mosaico.conf once
    python3 -m frigate.orbi360.mosaics apply     # sync systemd units with mosaics.json
"""

import logging
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from frigate.const import CONFIG_DIR

logger = logging.getLogger(__name__)

MOSAICS_DIR = Path(CONFIG_DIR) / "orbi360"
MOSAICS_FILE = MOSAICS_DIR / "mosaics.json"
CONF_DIR = MOSAICS_DIR / "mosaics"
LEGACY_CONF = Path("/etc/orbi360-mosaico.conf")
UNIT_TEMPLATE = "orbi360-mosaico@{}.service"
# Live state written by orbi360-mosaico: <id>.srt and <id>.enc hold
# "<state> <since epoch> [restarts]"
STATE_DIR = Path("/run/orbi360-mosaico")

# The encoder hands the stream to srt-live-transmit over a local UDP port derived
# from the SRT port, so every mosaic needs its own pair
INTERNAL_PORT_OFFSET = 10000
MIN_PORT = 1024
MAX_PORT = 65535 - INTERNAL_PORT_OFFSET
RESERVED_PORTS = {1984, 5000, 8554, 8555, 8971}

ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
STREAM_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
# SRT passphrases are 10 to 79 characters; limited to URL safe ones so the
# value can go into the srt:// URL and the shell config without quoting issues
PASSPHRASE_PATTERN = re.compile(r"^[A-Za-z0-9._~-]{10,79}$")
# Caller mode target. Stream IDs keep the characters servers use, such as
# Nimble's '#!::r=live/cam,m=publish', but never quotes, spaces, '&' or '$'
HOST_PATTERN = re.compile(r"^[A-Za-z0-9.-]{1,253}$")
STREAM_ID_PATTERN = re.compile(r"^[A-Za-z0-9#!:,=/._~@+-]{1,512}$")

RESOLUTIONS = {"1920x1080": (1920, 1080), "1280x720": (1280, 720)}
MAX_STREAMS = 9


class Mosaic(BaseModel):
    id: str = Field(description="Unique identifier, used in the systemd unit name")
    name: str = Field(min_length=1, max_length=64)
    enabled: bool = True
    streams: list[str] = Field(
        description="1 to 9 go2rtc stream names in reading order (left to right, top to bottom)"
    )
    mode: Literal["listener", "caller"] = Field(
        default="listener",
        description="listener waits for clients on srt_port; caller pushes to target_host:target_port",
    )
    srt_port: int = Field(
        ge=MIN_PORT,
        le=MAX_PORT,
        description="Listening port; in caller mode it only reserves the internal relay port",
    )
    target_host: str | None = None
    target_port: int | None = Field(default=None, ge=1, le=65535)
    stream_id: str | None = None
    latency_ms: int = Field(default=5000, ge=20, le=60000)
    bitrate_kbps: int = Field(default=2500, ge=300, le=20000)
    fps: int = Field(default=15, ge=1, le=30)
    resolution: Literal["1920x1080", "1280x720"] = "1920x1080"
    encoder: Literal["auto", "vaapi", "x264"] = "auto"
    passphrase: str | None = Field(
        default=None,
        description="SRT passphrase (AES-128). Clients must use the same one",
    )

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        if not ID_PATTERN.match(value):
            raise ValueError(
                "id must be lowercase letters, numbers, '-' or '_' (max 32)"
            )
        return value

    @field_validator("streams")
    @classmethod
    def validate_streams(cls, value: list[str]) -> list[str]:
        if not 1 <= len(value) <= MAX_STREAMS:
            raise ValueError(f"a mosaic needs between 1 and {MAX_STREAMS} streams")
        for stream in value:
            if not STREAM_PATTERN.match(stream):
                raise ValueError(f"invalid stream name: {stream!r}")
        return value

    @field_validator("passphrase")
    @classmethod
    def validate_passphrase(cls, value: str | None) -> str | None:
        if value in (None, ""):
            return None
        if not PASSPHRASE_PATTERN.match(value):
            raise ValueError(
                "the SRT passphrase needs 10 to 79 characters: letters, numbers, '.', '_', '~' or '-'"
            )
        return value

    @field_validator("target_host")
    @classmethod
    def validate_target_host(cls, value: str | None) -> str | None:
        if value in (None, ""):
            return None
        if not HOST_PATTERN.match(value) or value.startswith(("-", ".")):
            raise ValueError(f"invalid server address: {value!r}")
        return value

    @field_validator("stream_id")
    @classmethod
    def validate_stream_id(cls, value: str | None) -> str | None:
        if value in (None, ""):
            return None
        if not STREAM_ID_PATTERN.match(value):
            raise ValueError(
                "the stream ID can only use letters, numbers and # ! : , = / . _ ~ @ + -"
            )
        return value

    @model_validator(mode="after")
    def validate_target(self) -> "Mosaic":
        if self.mode == "caller" and (not self.target_host or not self.target_port):
            raise ValueError(
                f"'{self.name}' sends to a server: it needs the server address and port"
            )
        return self

    @field_validator("srt_port")
    @classmethod
    def validate_port(cls, value: int) -> int:
        if value in RESERVED_PORTS or value + INTERNAL_PORT_OFFSET in RESERVED_PORTS:
            raise ValueError(f"port {value} is reserved by Orbi360 NVR")
        return value


class MosaicList(BaseModel):
    mosaics: list[Mosaic] = []

    @model_validator(mode="after")
    def validate_unique(self) -> "MosaicList":
        ids = [m.id for m in self.mosaics]
        if len(ids) != len(set(ids)):
            raise ValueError("mosaic ids must be unique")

        used: set[int] = set()
        for mosaic in self.mosaics:
            ports = {mosaic.srt_port, mosaic.srt_port + INTERNAL_PORT_OFFSET}
            if ports & used:
                raise ValueError(
                    f"port {mosaic.srt_port} of '{mosaic.name}' collides with another mosaic"
                )
            used |= ports
        return self


def load() -> MosaicList:
    if not MOSAICS_FILE.exists():
        return MosaicList()
    return MosaicList.model_validate_json(MOSAICS_FILE.read_text())


def save(mosaics: MosaicList) -> None:
    MOSAICS_DIR.mkdir(parents=True, exist_ok=True)
    tmp = MOSAICS_FILE.with_suffix(".tmp")
    tmp.write_text(mosaics.model_dump_json(indent=2))
    tmp.replace(MOSAICS_FILE)


def render_conf(mosaic: Mosaic) -> str:
    """Shell config read by orbi360-mosaico. Values are validated, so safe to quote."""
    out_w, out_h = RESOLUTIONS[mosaic.resolution]
    return "\n".join(
        [
            f"# Generado por Orbi360 NVR (Ajustes > Mosaico SRT): {mosaic.name}",
            "# No editar a mano: los cambios se pierden al guardar desde la interfaz",
            f"NAME={shlex.quote(mosaic.name)}",
            f'CAMS="{" ".join(mosaic.streams)}"',
            "SOURCE=direct",
            f"SRT_PORT={mosaic.srt_port}",
            f"UDP_PORT={mosaic.srt_port + INTERNAL_PORT_OFFSET}",
            f"SRT_LATENCY={mosaic.latency_ms}",
            f"BITRATE={mosaic.bitrate_kbps}",
            f"FPS={mosaic.fps}",
            f"OUT_W={out_w}",
            f"OUT_H={out_h}",
            f"ENCODER={mosaic.encoder}",
            f"SRT_PASSPHRASE={mosaic.passphrase or ''}",
            f"MODE={mosaic.mode}",
            f"TARGET_HOST={mosaic.target_host or ''}",
            f"TARGET_PORT={mosaic.target_port or ''}",
            # single quotes: the stream ID may contain '#' or '!'
            f"STREAM_ID='{mosaic.stream_id or ''}'",
            "",
        ]
    )


def systemd_available() -> bool:
    return (
        shutil.which("systemctl") is not None and Path("/run/systemd/system").is_dir()
    )


def _systemctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["systemctl", *args], capture_output=True, text=True, timeout=30
    )


def unit_status(mosaic_id: str) -> str:
    if not systemd_available():
        return "unsupported"
    result = _systemctl("is-active", UNIT_TEMPLATE.format(mosaic_id))
    return result.stdout.strip() or "unknown"


def _read_state(path: Path) -> tuple[str, int, int] | None:
    try:
        parts = path.read_text().split()
        return parts[0], int(parts[1]), int(parts[2]) if len(parts) > 2 else 0
    except (OSError, IndexError, ValueError):
        return None


def runtime(mosaic_id: str) -> dict | None:
    """Live connection and encoder state of a running mosaic, if it reports one.

    srt: connected, connecting (caller retrying) or waiting (listener without a
    client). encoder: ok, starting, restarting or stalled.
    """
    srt = _read_state(STATE_DIR / f"{mosaic_id}.srt")
    enc = _read_state(STATE_DIR / f"{mosaic_id}.enc")
    if srt is None and enc is None:
        return None
    return {
        "srt": srt[0] if srt else "unknown",
        "srt_since": srt[1] if srt else None,
        "encoder": enc[0] if enc else "unknown",
        "encoder_since": enc[1] if enc else None,
        "restarts": enc[2] if enc else 0,
    }


def _running_instances() -> set[str]:
    result = _systemctl(
        "list-units", "--all", "--plain", "--no-legend", "orbi360-mosaico@*.service"
    )
    instances = set()
    for line in result.stdout.splitlines():
        unit = line.split()[0] if line.split() else ""
        match = re.match(r"^orbi360-mosaico@(.+)\.service$", unit)
        if match:
            instances.add(match.group(1))
    return instances


def apply(mosaics: MosaicList) -> dict[str, str]:
    """Write per-mosaic configs and start, restart or stop units as needed.

    Only mosaics whose config changed are restarted, so saving one output does
    not interrupt the others. Returns the resulting status per mosaic id.
    """
    CONF_DIR.mkdir(parents=True, exist_ok=True)
    wanted = {m.id: m for m in mosaics.mosaics}
    can_manage = systemd_available()

    for mosaic in mosaics.mosaics:
        conf_path = CONF_DIR / f"{mosaic.id}.conf"
        content = render_conf(mosaic)
        changed = not conf_path.exists() or conf_path.read_text() != content
        if changed:
            conf_path.write_text(content)

        if not can_manage:
            continue

        unit = UNIT_TEMPLATE.format(mosaic.id)
        if mosaic.enabled:
            _systemctl("enable", unit)
            if changed or unit_status(mosaic.id) != "active":
                _systemctl("restart", unit)
        else:
            _systemctl("disable", "--now", unit)

    # Remove mosaics that no longer exist
    for conf_path in CONF_DIR.glob("*.conf"):
        if conf_path.stem not in wanted:
            if can_manage:
                _systemctl("disable", "--now", UNIT_TEMPLATE.format(conf_path.stem))
            conf_path.unlink()
    if can_manage:
        for instance in _running_instances() - set(wanted):
            _systemctl("disable", "--now", UNIT_TEMPLATE.format(instance))

    return {m.id: unit_status(m.id) for m in mosaics.mosaics}


def migrate_legacy() -> bool:
    """Import the single mosaic from /etc/orbi360-mosaico.conf, once."""
    if MOSAICS_FILE.exists() or not LEGACY_CONF.exists():
        return False

    values: dict[str, str] = {}
    for line in LEGACY_CONF.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"')

    cams = values.get("CAMS", "").split()
    if len(cams) != 4 or cams[0] == "CAMARA1":
        return False
    if values.get("SOURCE", "sub") == "sub":
        cams = [f"{cam}_sub" for cam in cams]

    tile_w = int(values.get("TILE_W", "960"))
    mosaic = Mosaic(
        id="principal",
        name="Principal",
        streams=cams,
        srt_port=int(values.get("SRT_PORT", "9999")),
        latency_ms=int(values.get("SRT_LATENCY", "5000")),
        bitrate_kbps=int(values.get("BITRATE", "2500")),
        fps=int(values.get("FPS", "15")),
        resolution="1280x720" if tile_w == 640 else "1920x1080",
        encoder=values.get("ENCODER", "auto"),
    )
    save(MosaicList(mosaics=[mosaic]))
    return True


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    command = argv[1] if len(argv) > 1 else "apply"
    if command == "migrate":
        print("migrated" if migrate_legacy() else "nothing to migrate")
    elif command == "apply":
        for mosaic_id, status in apply(load()).items():
            print(f"{mosaic_id}: {status}")
    else:
        print(f"unknown command: {command}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    os.umask(0o022)
    sys.exit(main(sys.argv))
