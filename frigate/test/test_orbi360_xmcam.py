import json
import socket
import threading
import unittest

from frigate.orbi360 import xmcam


class FakeCamera(threading.Thread):
    """Answers DVRIP login and password change like a Xiongmai camera."""

    def __init__(self, password: str):
        super().__init__(daemon=True)
        self.hash = xmcam.sofia_hash(password)
        self.server = socket.socket()
        self.server.bind(("127.0.0.1", 0))
        self.server.listen()
        self.port = self.server.getsockname()[1]

    def reply(self, conn, msg, body):
        data = json.dumps(body).encode() + b"\x0a\x00"
        conn.sendall(xmcam.HEADER.pack(0xFF, 1, 0x1A, 0, msg + 1, len(data)))
        conn.sendall(data)

    def run(self):
        while True:
            conn, _ = self.server.accept()
            with conn:
                while header := conn.recv(xmcam.HEADER.size):
                    _, _, _, _, msg, size = xmcam.HEADER.unpack(header)
                    body = json.loads(conn.recv(size).rstrip(b"\x00\x0a"))
                    if msg == xmcam.LOGIN:
                        ok = (
                            body["UserName"] == "admin"
                            and body["PassWord"] == self.hash
                        )
                        self.reply(
                            conn,
                            msg,
                            {"Ret": 100 if ok else 203, "SessionID": "0x0000001A"},
                        )
                    elif msg == xmcam.MODIFY_PASSWORD:
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
        self.assertEqual(xmcam.sofia_hash(""), "tlJwpbo6")

    def test_changes_the_password(self):
        cam = FakeCamera("")
        cam.start()
        dvr = xmcam.Dvrip("127.0.0.1", cam.port)
        self.assertEqual(dvr.login("admin", "mala"), 203)
        self.assertEqual(dvr.login("admin", ""), 100)
        self.assertEqual(dvr.change_password("admin", "", "nueva"), 100)
        dvr.close()
        dvr = xmcam.Dvrip("127.0.0.1", cam.port)
        self.assertEqual(dvr.login("admin", "nueva"), 100)
        dvr.close()

    def test_to_h264(self):
        # Simplify.Encode as read from the Garaje camera on 2026-10-11
        video = {"Compression": "H.265", "GOP": 4, "FPS": 12, "VirtualGOP": 1}
        encode = [
            {
                "MainFormat": {"Video": dict(video)},
                "ExtraFormat": {"Video": dict(video)},
            }
        ]
        result = xmcam.to_h264(encode)
        for fmt in ("MainFormat", "ExtraFormat"):
            self.assertEqual(result[0][fmt]["Video"]["Compression"], "H.264")
            self.assertEqual(result[0][fmt]["Video"]["GOP"], 2)
            self.assertEqual(result[0][fmt]["Video"]["FPS"], 12)


class TestXmStaticIp(unittest.TestCase):
    def setUp(self):
        self.common = {
            "HostIP": xmcam.ip_to_hex("192.168.1.10"),
            "Submask": xmcam.ip_to_hex("255.255.255.0"),
            "GateWay": xmcam.ip_to_hex("192.168.1.1"),
        }
        self.wifi = {
            "Enable": True,
            "Keys": "secreta",
            "HostIP": xmcam.ip_to_hex("192.168.1.37"),
            "Submask": xmcam.ip_to_hex("255.255.255.0"),
            "GateWay": xmcam.ip_to_hex("192.168.1.254"),
        }
        self.dhcp = [
            {"Enable": True, "Interface": "eth0"},
            {"Enable": True, "Interface": "eth2"},
        ]

    def test_hex_round_trip(self):
        self.assertEqual(xmcam.ip_to_hex("192.168.1.100"), "0x6401A8C0")
        self.assertEqual(xmcam.hex_to_ip("0x6401A8C0"), "192.168.1.100")

    def test_fixes_the_wifi_interface(self):
        iface, configs = xmcam.plan_static(
            self.common, self.wifi, self.dhcp, "192.168.1.37", "192.168.1.231"
        )
        self.assertEqual(iface, "eth2")
        wifi = configs[xmcam.NET_WIFI]
        self.assertEqual(xmcam.hex_to_ip(wifi["HostIP"]), "192.168.1.231")
        self.assertEqual(wifi["Keys"], "secreta")
        self.assertEqual(
            configs[xmcam.NET_DHCP],
            [
                {"Enable": True, "Interface": "eth0"},
                {"Enable": False, "Interface": "eth2"},
            ],
        )
        self.assertEqual(
            xmcam.hex_to_ip(configs[xmcam.NET_DNS]["Address"]), "192.168.1.254"
        )
        self.assertNotIn(xmcam.NET_COMMON, configs)
        self.assertTrue(self.dhcp[1]["Enable"])

    def test_fixes_the_cable_interface(self):
        self.wifi["Enable"] = False
        iface, configs = xmcam.plan_static(
            self.common, self.wifi, self.dhcp, "192.168.1.10", "192.168.1.232"
        )
        self.assertEqual(iface, "eth0")
        self.assertIn(xmcam.NET_COMMON, configs)
        self.assertFalse(configs[xmcam.NET_DHCP][0]["Enable"])

    def test_refuses_unsafe_changes(self):
        for current, new in (
            ("192.168.1.99", "192.168.1.231"),  # camera doesn't report this IP
            ("192.168.1.37", "192.168.2.231"),  # other subnet
            ("192.168.1.37", "192.168.1.254"),  # the gateway
            ("192.168.1.37", "192.168.1.255"),  # broadcast
        ):
            with self.assertRaises(xmcam.NetError):
                xmcam.plan_static(self.common, self.wifi, self.dhcp, current, new)


if __name__ == "__main__":
    unittest.main()
