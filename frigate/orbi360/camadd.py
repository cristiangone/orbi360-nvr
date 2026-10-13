"""Add a camera found on the LAN (Ajustes > Red de cámaras > Agregar).

Two kinds of camera are detected with the Orbi360 password
(FRIGATE_RTSP_PASSWORD):

* Xiongmai with RTSP: ``rtsp://IP:554/user=admin&password=...&channel=1&stream=0.sdp``
  (sala_gym, cocina, quincho, entrada).
* Xiongmai with DVRIP only (iCSee 2026 firmware, e.g. garaje): go2rtc reads
  ``dvrip://`` on port 34567. These are recorded without audio (the audio made
  the recording ffmpeg grow to ~6 GB on 2026-10-12) and decoded in software;
  an H.265 stream is switched to H.264 on request (ffmpeg cannot decode it).

Any other brand can be added with its own main and sub RTSP URLs. The camera
is written to config.yml like the existing ones (go2rtc restream, main stream
records, sub stream detects), its MAC is handed to the locator and the NVR is
restarted.
"""

import re
import shutil
import subprocess
import time
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from frigate.orbi360 import camlocator

CONFIG_FILE = camlocator.CONFIG_FILE
NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,30}$")
PASSWORD_VAR = "{FRIGATE_RTSP_PASSWORD}"


def xm_rtsp(ip: str, stream: int) -> str:
    return (
        f"rtsp://{ip}:554/user=admin&password={PASSWORD_VAR}"
        f"&channel=1&stream={stream}.sdp"
    )


def xm_dvrip(ip: str, stream: int) -> str:
    return f"dvrip://admin:{PASSWORD_VAR}@{ip}:34567?channel=0&subtype={stream}"


class AddError(ValueError):
    """Message shown to the user as is."""


def _yaml() -> YAML:
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.indent(mapping=2, sequence=4, offset=2)  # same style as config.yml
    return yaml


def slug(text: str) -> str:
    """Camera name for config.yml from a friendly name: "Patio Norte" -> patio_norte."""
    table = str.maketrans("áéíóúüñÁÉÍÓÚÜÑ", "aeiouunAEIOUUN")
    name = re.sub(r"[^a-z0-9]+", "_", text.translate(table).lower()).strip("_")
    if name and not name[0].isalpha():
        name = "cam_" + name
    return name[:30]


def _dvrip_login(ip: str) -> int:
    from frigate.orbi360 import xmcam

    password = camlocator._env_vars().get("FRIGATE_RTSP_PASSWORD", "")
    cam = xmcam.Dvrip(ip)
    try:
        return cam.login("admin", password)
    finally:
        cam.close()


def _dvrip_codec(ip: str) -> str | None:
    from frigate.orbi360 import xmcam

    password = camlocator._env_vars().get("FRIGATE_RTSP_PASSWORD", "")
    cam = xmcam.Dvrip(ip)
    try:
        if cam.login("admin", password) != xmcam.RET_OK:
            return None
        encode = cam.get_config(xmcam.ENCODE)
        return encode[0]["MainFormat"]["Video"]["Compression"]
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        return None
    finally:
        cam.close()


def probe(ip: str) -> dict:
    """How the camera at ip can be read with the Orbi360 password."""
    if camlocator.port_open(ip, camlocator.RTSP_PORT) and camlocator.stream_ok(
        xm_rtsp(ip, 0)
    ):
        return {"protocol": "xm_rtsp", "ip": ip}
    if camlocator.port_open(ip, camlocator.DVRIP_PORT):
        try:
            code = _dvrip_login(ip)
        except OSError as e:
            return {"protocol": None, "ip": ip, "message": f"DVRIP sin respuesta: {e}"}
        if code != 100:
            return {
                "protocol": None,
                "ip": ip,
                "message": (
                    "La cámara responde por DVRIP pero no acepta la clave de Orbi360 "
                    f"(código {code}). Ponle la clave con: "
                    f"python3 -m frigate.orbi360.xmcam passwd {ip}"
                ),
            }
        return {"protocol": "dvrip", "ip": ip, "codec": _dvrip_codec(ip)}
    return {
        "protocol": None,
        "ip": ip,
        "message": "No responde por RTSP de Xiongmai ni por DVRIP: usa URLs propias de su marca.",
    }


def camera_entries(
    name: str,
    friendly_name: str,
    protocol: str,
    ip: str = "",
    main_url: str = "",
    sub_url: str = "",
) -> tuple[list[str], list[str], CommentedMap]:
    """go2rtc sources (main, sub) and the camera block for config.yml."""
    if protocol == "xm_rtsp":
        main, sub = xm_rtsp(ip, 0), xm_rtsp(ip, 1)
    elif protocol == "dvrip":
        main, sub = xm_dvrip(ip, 0), xm_dvrip(ip, 1)
    elif protocol == "custom":
        main, sub = main_url.strip(), (sub_url.strip() or main_url.strip())
        if not main.startswith(
            ("rtsp://", "rtsps://", "dvrip://", "http://", "https://")
        ):
            raise AddError(
                "La URL principal debe empezar con rtsp://, dvrip:// o http(s)://"
            )
    else:
        raise AddError(f"Protocolo desconocido: {protocol}")

    ffmpeg = CommentedMap()
    if protocol == "dvrip":
        ffmpeg["hwaccel_args"] = CommentedSeq()
        ffmpeg["output_args"] = CommentedMap(record="preset-record-generic")
    ffmpeg["inputs"] = CommentedSeq(
        [
            CommentedMap(
                path=f"rtsp://127.0.0.1:8554/{name}",
                input_args="preset-rtsp-restream",
                roles=CommentedSeq(["record"]),
            ),
            CommentedMap(
                path=f"rtsp://127.0.0.1:8554/{name}_sub",
                input_args="preset-rtsp-restream",
                roles=CommentedSeq(["detect"]),
            ),
        ]
    )
    cam = CommentedMap()
    cam["friendly_name"] = friendly_name
    cam["ffmpeg"] = ffmpeg
    cam["live"] = CommentedMap(
        streams=CommentedMap(Principal=name, Secundario=f"{name}_sub")
    )
    return [main], [sub], cam


def add_to_config(cfg, name: str, main: list[str], sub: list[str], cam) -> None:
    cameras = cfg.setdefault("cameras", CommentedMap())
    go2rtc = cfg.setdefault("go2rtc", CommentedMap())
    streams = go2rtc.setdefault("streams", CommentedMap())
    if name in cameras or name in streams or f"{name}_sub" in streams:
        raise AddError(f"Ya existe una cámara o stream llamado «{name}»")
    streams[name] = CommentedSeq(main)
    streams[f"{name}_sub"] = CommentedSeq(sub)
    cameras[name] = cam


def add_camera(
    name: str,
    friendly_name: str,
    protocol: str,
    ip: str = "",
    mac: str = "",
    main_url: str = "",
    sub_url: str = "",
    to_h264: bool = False,
    restart: bool = True,
) -> dict:
    """Write the camera to config.yml (with backup), learn its MAC and restart."""
    if not NAME_PATTERN.match(name):
        raise AddError(
            "Nombre interno inválido: minúsculas, números y _, empezando con una letra"
        )
    friendly_name = friendly_name.strip() or name
    # a device behind a repeater is reported as "<repeater mac>@<ip>"
    key = mac.lower()
    mac, _, behind = key.partition("@")
    if mac and not camlocator.MAC_PATTERN.match(mac):
        raise AddError(f"MAC inválida: {mac}")

    notes = []
    if mac and (behind or mac in camlocator.load_state().get("bridged", [])):
        # the repeater's MAC: following it would move the camera to the repeater
        mac = ""
        notes.append(
            "Está detrás de un repetidor WiFi que oculta su MAC: Orbi360 no puede "
            "seguirla si cambia de IP. Conéctala al router principal o fija su IP."
        )
    if protocol == "dvrip" and to_h264:
        from frigate.orbi360 import xmcam

        password = camlocator._env_vars().get("FRIGATE_RTSP_PASSWORD", "")
        cam = xmcam.Dvrip(ip)
        try:
            if cam.login("admin", password) == xmcam.RET_OK:
                code = cam.set_config(
                    xmcam.ENCODE, xmcam.to_h264(cam.get_config(xmcam.ENCODE))
                )
                if code in (xmcam.RET_OK, xmcam.RET_SAVED_NEEDS_REBOOT):
                    cam.reboot()
                    notes.append(
                        "Cámara pasada a H.264; se está reiniciando (1-2 minutos)."
                    )
        finally:
            cam.close()

    main, sub, block = camera_entries(
        name, friendly_name, protocol, ip, main_url, sub_url
    )
    yaml = _yaml()
    cfg = yaml.load(CONFIG_FILE.read_text()) or CommentedMap()
    add_to_config(cfg, name, main, sub, block)
    backup = CONFIG_FILE.with_name(f"config.yml.bak-add-{int(time.time())}")
    shutil.copy(CONFIG_FILE, backup)
    tmp = CONFIG_FILE.with_suffix(".yml.tmp")
    with tmp.open("w") as f:
        yaml.dump(cfg, f)
    tmp.replace(CONFIG_FILE)

    if mac:
        camlocator._with_saved_state(lambda state: camlocator.assign(state, name, mac))
    elif behind:

        def drop(state):
            state["discovered"].pop(key, None)

        camlocator._with_saved_state(drop)
    if restart and shutil.which("systemctl") and Path("/run/systemd/system").is_dir():
        # --no-block: the API answering this request runs inside orbi360-nvr
        # (its ExecStartPre also restarts go2rtc, which loads the new streams)
        subprocess.run(
            ["systemctl", "--no-block", "restart", "orbi360-nvr.service"],
            capture_output=True,
            timeout=30,
        )
    return {"name": name, "backup": backup.name, "notes": notes}
