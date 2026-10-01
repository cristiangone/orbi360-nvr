"""SRT mosaic outputs.

Each mosaic tiles four go2rtc streams into a 2x2 grid and publishes it as an
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

# The encoder hands the stream to srt-live-transmit over a local UDP port derived
# from the SRT port, so every mosaic needs its own pair
INTERNAL_PORT_OFFSET = 10000
MIN_PORT = 1024
MAX_PORT = 65535 - INTERNAL_PORT_OFFSET
RESERVED_PORTS = {1984, 5000, 8554, 8555, 8971}

ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
STREAM_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

RESOLUTIONS = {"1920x1080": (960, 540), "1280x720": (640, 360)}


class Mosaic(BaseModel):
    id: str = Field(description="Unique identifier, used in the systemd unit name")
    name: str = Field(min_length=1, max_length=64)
    enabled: bool = True
    streams: list[str] = Field(
        description="Four go2rtc stream names: top-left, top-right, bottom-left, bottom-right"
    )
    srt_port: int = Field(ge=MIN_PORT, le=MAX_PORT)
    latency_ms: int = Field(default=5000, ge=20, le=60000)
    bitrate_kbps: int = Field(default=2500, ge=300, le=20000)
    fps: int = Field(default=15, ge=1, le=30)
    resolution: Literal["1920x1080", "1280x720"] = "1920x1080"
    encoder: Literal["auto", "vaapi", "x264"] = "auto"

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
        if len(value) != 4:
            raise ValueError("a 2x2 mosaic needs exactly 4 streams")
        for stream in value:
            if not STREAM_PATTERN.match(stream):
                raise ValueError(f"invalid stream name: {stream!r}")
        return value

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
    tile_w, tile_h = RESOLUTIONS[mosaic.resolution]
    return "\n".join(
        [
            f"# Generado por Orbi360 NVR (Ajustes > Mosaico SRT): {mosaic.name}",
            "# No editar a mano: los cambios se pierden al guardar desde la interfaz",
            f'CAMS="{" ".join(mosaic.streams)}"',
            "SOURCE=direct",
            f"SRT_PORT={mosaic.srt_port}",
            f"UDP_PORT={mosaic.srt_port + INTERNAL_PORT_OFFSET}",
            f"SRT_LATENCY={mosaic.latency_ms}",
            f"BITRATE={mosaic.bitrate_kbps}",
            f"FPS={mosaic.fps}",
            f"TILE_W={tile_w}",
            f"TILE_H={tile_h}",
            f"ENCODER={mosaic.encoder}",
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
