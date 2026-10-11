import json
import socket
import threading
import unittest

from frigate.orbi360 import xmpasswd


class FakeCamera(threading.Thread):
    """Answers DVRIP login and password change like a Xiongmai camera."""

    def __init__(self, password: str):
        super().__init__(daemon=True)
        self.hash = xmpasswd.sofia_hash(password)
        self.server = socket.socket()
        self.server.bind(("127.0.0.1", 0))
        self.server.listen()
        self.port = self.server.getsockname()[1]

    def reply(self, conn, msg, body):
        data = json.dumps(body).encode() + b"\x0a\x00"
        conn.sendall(xmpasswd.HEADER.pack(0xFF, 1, 0x1A, 0, msg + 1, len(data)))
        conn.sendall(data)

    def run(self):
        while True:
            conn, _ = self.server.accept()
            with conn:
                while header := conn.recv(xmpasswd.HEADER.size):
                    _, _, _, _, msg, size = xmpasswd.HEADER.unpack(header)
                    body = json.loads(conn.recv(size).rstrip(b"\x00\x0a"))
                    if msg == xmpasswd.LOGIN:
                        ok = (
                            body["UserName"] == "admin"
                            and body["PassWord"] == self.hash
                        )
                        self.reply(
                            conn,
                            msg,
                            {"Ret": 100 if ok else 203, "SessionID": "0x0000001A"},
                        )
                    elif msg == xmpasswd.MODIFY_PASSWORD:
                        ok = (
                            body["PassWord"] == self.hash
                            and body["SessionID"] == "0x0000001A"
                        )
                        if ok:
                            self.hash = body["NewPassWord"]
                        self.reply(conn, msg, {"Ret": 100 if ok else 203})


class TestXmPasswd(unittest.TestCase):
    def test_sofia_hash(self):
        # well-known hash of the empty password on Xiongmai devices
        self.assertEqual(xmpasswd.sofia_hash(""), "tlJwpbo6")

    def test_changes_the_password(self):
        cam = FakeCamera("")
        cam.start()
        dvr = xmpasswd.Dvrip("127.0.0.1", cam.port)
        self.assertEqual(dvr.login("admin", "mala"), 203)
        self.assertEqual(dvr.login("admin", ""), 100)
        self.assertEqual(dvr.change_password("admin", "", "nueva"), 100)
        dvr.close()
        dvr = xmpasswd.Dvrip("127.0.0.1", cam.port)
        self.assertEqual(dvr.login("admin", "nueva"), 100)
        dvr.close()


if __name__ == "__main__":
    unittest.main()
