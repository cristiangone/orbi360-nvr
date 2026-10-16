"""Camera password (FRIGATE_RTSP_PASSWORD) set from Ajustes > Red de cámaras.

On the lab NVR it was written by hand into /etc/orbi360-nvr.env; a new client
NVR needs it before "Agregar cámara" can detect anything. The value is kept
only in that file (mode 600) and never returned by the API. config.yml refers
to it as {FRIGATE_RTSP_PASSWORD}, so the NVR must restart to use a new one.
"""

import os
import re
from pathlib import Path

from frigate.orbi360 import camlocator

VAR = "FRIGATE_RTSP_PASSWORD"
# It goes inside URLs (".../user=admin&password=X&channel=1" and
# "dvrip://admin:X@ip"): characters like @ & # ? / : would break them
PASSWORD_PATTERN = re.compile(r"^[A-Za-z0-9._~!*+-]{4,64}$")


class PasswordError(ValueError):
    """Message shown to the user as is."""


def _env_file() -> Path:
    return Path(camlocator.ENV_FILE)


def is_set() -> bool:
    try:
        lines = _env_file().read_text().splitlines()
    except OSError:
        return False
    return any(
        line.startswith(f"{VAR}=") and len(line) > len(VAR) + 1 for line in lines
    )


def set_password(password: str) -> None:
    if not PASSWORD_PATTERN.match(password):
        raise PasswordError(
            "La clave debe tener entre 4 y 64 caracteres: letras, números y . _ ~ ! * + -"
        )
    path = _env_file()
    try:
        lines = path.read_text().splitlines()
    except FileNotFoundError:
        lines = []
    lines = [line for line in lines if not line.startswith(f"{VAR}=")]
    lines.append(f"{VAR}={password}")
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write("\n".join(lines) + "\n")
    os.chmod(tmp, 0o600)
    tmp.replace(path)
