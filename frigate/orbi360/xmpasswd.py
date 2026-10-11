"""Set the local password of a Xiongmai (iCSee/XMEye) camera over DVRIP.

Newer iCSee firmware (2026) applies the app's "device password" only to the
cloud account: the local user ``admin`` that RTSP/DVRIP clients use stays
without a password. This sets it, by default to FRIGATE_RTSP_PASSWORD so the
camera works with the same config.yml variable as the others.

Usage::

    python3 -m frigate.orbi360.xmpasswd <ip> [--user admin]

The current password is asked for (Enter when there is none); nothing is
printed or logged.
"""

import getpass
import hashlib
import json
import socket
import struct
import sys

from frigate.orbi360.camlocator import DVRIP_PORT, _env_vars

HEADER = struct.Struct("<BB2xII2xHI")
LOGIN = 1000
MODIFY_PASSWORD = 1488
RET_OK = 100
RET_TEXT = {
    203: "clave incorrecta",
    205: "usuario inexistente",
    206: "usuario bloqueado por intentos fallidos (reinicia la camara)",
}


def sofia_hash(password: str) -> str:
    """Xiongmai's password hash: MD5 folded to 8 alphanumeric characters."""
    digest = hashlib.md5(password.encode("utf-8")).digest()
    chars = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    return "".join(chars[(a + b) % 62] for a, b in zip(digest[::2], digest[1::2]))


class Dvrip:
    def __init__(self, ip: str, port: int = DVRIP_PORT, timeout: float = 10):
        self.sock = socket.create_connection((ip, port), timeout=timeout)
        self.session = 0
        self.seq = 0

    def close(self) -> None:
        self.sock.close()

    def _recv(self, size: int) -> bytes:
        data = b""
        while len(data) < size:
            chunk = self.sock.recv(size - len(data))
            if not chunk:
                raise ConnectionError("la camara cerro la conexion")
            data += chunk
        return data

    def send(self, msg: int, body: dict) -> dict:
        data = json.dumps(body).encode() + b"\x0a\x00"
        self.sock.sendall(HEADER.pack(0xFF, 0, self.session, self.seq, msg, len(data)))
        self.sock.sendall(data)
        self.seq += 1
        _, _, session, _, _, size = HEADER.unpack(self._recv(HEADER.size))
        reply = self._recv(size).rstrip(b"\x00\x0a ")
        self.session = session or self.session
        return json.loads(reply.decode("utf-8", "replace")) if reply else {}

    def login(self, user: str, password: str) -> int:
        reply = self.send(
            LOGIN,
            {
                "EncryptType": "MD5",
                "LoginType": "DVRIP-Web",
                "PassWord": sofia_hash(password),
                "UserName": user,
            },
        )
        if reply.get("SessionID"):
            self.session = int(str(reply["SessionID"]), 16)
        return int(reply.get("Ret", 0))

    def change_password(self, user: str, old: str, new: str) -> int:
        reply = self.send(
            MODIFY_PASSWORD,
            {
                "EncryptType": "MD5",
                "NewPassWord": sofia_hash(new),
                "PassWord": sofia_hash(old),
                "SessionID": "0x%08X" % self.session,
                "UserName": user,
            },
        )
        return int(reply.get("Ret", 0))


def _ret(code: int) -> str:
    return f"Ret {code}" + (f" ({RET_TEXT[code]})" if code in RET_TEXT else "")


def main(argv: list[str]) -> int:
    args = argv[1:]
    user = "admin"
    if "--user" in args:
        i = args.index("--user")
        user = args[i + 1]
        del args[i : i + 2]
    if len(args) != 1:
        print(__doc__.split("Usage::")[1].strip().splitlines()[0], file=sys.stderr)
        return 2
    ip = args[0]
    new = _env_vars().get("FRIGATE_RTSP_PASSWORD")
    if not new:
        print("Falta FRIGATE_RTSP_PASSWORD en /etc/orbi360-nvr.env", file=sys.stderr)
        return 2
    old = getpass.getpass(f"Clave actual de {user} en {ip} (Enter si no tiene): ")

    cam = Dvrip(ip)
    try:
        code = cam.login(user, old)
        if code != RET_OK:
            print(f"No se pudo entrar con la clave actual: {_ret(code)}")
            return 1
        code = cam.change_password(user, old, new)
        if code != RET_OK:
            print(f"La camara rechazo el cambio: {_ret(code)}. No se cambio nada.")
            return 1
    finally:
        cam.close()

    check = Dvrip(ip)
    try:
        code = check.login(user, new)
    finally:
        check.close()
    if code != RET_OK:
        print(f"Cambio aceptado, pero la clave nueva no entra: {_ret(code)}")
        return 1
    print(f"Listo: {user}@{ip} usa ahora la clave de Orbi360 (FRIGATE_RTSP_PASSWORD).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
