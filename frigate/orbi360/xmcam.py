"""Xiongmai (iCSee/XMEye) camera setup over DVRIP (port 34567).

Newer iCSee cameras (2026 firmware, e.g. the Garaje camera) ship with RTSP
off, a local ``admin`` user without password (the app's "device password"
only protects the cloud account) and an H.265 stream ffmpeg cannot decode.
go2rtc reads them as ``dvrip://``; this tool prepares them:

    python3 -m frigate.orbi360.xmcam passwd <ip> [--user admin]
        set admin's password to FRIGATE_RTSP_PASSWORD (asks the current one,
        Enter when there is none)
    python3 -m frigate.orbi360.xmcam info <ip>
        show the video encoding of both streams
    python3 -m frigate.orbi360.xmcam h264 <ip>
        switch both streams to H.264 with a key frame every 2 s, then reboot
    python3 -m frigate.orbi360.xmcam reboot <ip>

Every command but passwd logs in with FRIGATE_RTSP_PASSWORD. Passwords are
never printed.
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
CONFIG_SET = 1040
CONFIG_GET = 1042
OP_MACHINE = 1450
ENCODE = "Simplify.Encode"
RET_SAVED_NEEDS_REBOOT = 603
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
                "SessionID": self._sid(),
                "UserName": user,
            },
        )
        return int(reply.get("Ret", 0))

    def get_config(self, name: str):
        reply = self.send(CONFIG_GET, {"Name": name, "SessionID": self._sid()})
        return reply.get(name)

    def set_config(self, name: str, value) -> int:
        reply = self.send(
            CONFIG_SET, {"Name": name, "SessionID": self._sid(), name: value}
        )
        return int(reply.get("Ret", 0))

    def reboot(self) -> None:
        try:
            self.send(
                OP_MACHINE,
                {
                    "Name": "OPMachine",
                    "SessionID": self._sid(),
                    "OPMachine": {"Action": "Reboot"},
                },
            )
        except (OSError, ValueError):
            pass  # the camera may drop the connection while rebooting

    def _sid(self) -> str:
        return "0x%08X" % self.session


def to_h264(encode: list) -> list:
    """Simplify.Encode with both streams in H.264, a key frame every 2 s."""
    for fmt in ("MainFormat", "ExtraFormat"):
        video = encode[0][fmt]["Video"]
        video["Compression"] = "H.264"
        video["GOP"] = 2
    return encode


def _ret(code: int) -> str:
    return f"Ret {code}" + (f" ({RET_TEXT[code]})" if code in RET_TEXT else "")


def _login(ip: str, user: str, password: str) -> Dvrip | None:
    cam = Dvrip(ip)
    code = cam.login(user, password)
    if code != RET_OK:
        cam.close()
        print(f"No se pudo entrar a {ip} como {user}: {_ret(code)}")
        return None
    return cam


def _passwd(ip: str, user: str, new: str) -> int:
    old = getpass.getpass(f"Clave actual de {user} en {ip} (Enter si no tiene): ")
    cam = _login(ip, user, old)
    if not cam:
        return 1
    try:
        code = cam.change_password(user, old, new)
    finally:
        cam.close()
    if code != RET_OK:
        print(f"La camara rechazo el cambio: {_ret(code)}. No se cambio nada.")
        return 1
    check = _login(ip, user, new)
    if not check:
        print("Cambio aceptado, pero la clave nueva no entra.")
        return 1
    check.close()
    print(f"Listo: {user}@{ip} usa ahora la clave de Orbi360 (FRIGATE_RTSP_PASSWORD).")
    return 0


def main(argv: list[str]) -> int:
    args = argv[1:]
    user = "admin"
    if "--user" in args:
        i = args.index("--user")
        user = args[i + 1]
        del args[i : i + 2]
    if len(args) != 2 or args[0] not in ("passwd", "info", "h264", "reboot"):
        usage = __doc__.split("this tool prepares them:")[1].split("Every command")[0]
        print("usage:" + usage.rstrip(), file=sys.stderr)
        return 2
    command, ip = args
    password = _env_vars().get("FRIGATE_RTSP_PASSWORD")
    if not password:
        print("Falta FRIGATE_RTSP_PASSWORD en /etc/orbi360-nvr.env", file=sys.stderr)
        return 2
    if command == "passwd":
        return _passwd(ip, user, password)

    cam = _login(ip, user, password)
    if not cam:
        return 1
    try:
        if command == "reboot":
            cam.reboot()
            print(f"Reinicio enviado a {ip}.")
            return 0
        encode = cam.get_config(ENCODE)
        if command == "info":
            for fmt in ("MainFormat", "ExtraFormat"):
                v = encode[0][fmt]["Video"]
                print(
                    f"{fmt:12} {v['Compression']} {v['Resolution']} {v['FPS']} fps, "
                    f"GOP {v['GOP']} s, {v['BitRate']} kbps {v['BitRateControl']}"
                )
            return 0
        code = cam.set_config(ENCODE, to_h264(encode))
        if code not in (RET_OK, RET_SAVED_NEEDS_REBOOT):
            print(f"La camara rechazo el cambio a H.264: {_ret(code)}")
            return 1
        cam.reboot()
        print(f"{ip}: H.264 con cuadro clave cada 2 s; reiniciando (1-2 minutos).")
        return 0
    finally:
        cam.close()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
