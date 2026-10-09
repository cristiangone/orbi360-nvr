import unittest

from ruamel.yaml import YAML

from frigate.orbi360 import camlocator

# arp-scan of the lab on 2026-10-09: every Xiongmai camera also answers the
# factory address .10, the kitchen camera has two leases and the Wi-Fi
# repeater has its own address
ARP = """Interface: eth0, type: EN10MB, MAC: bc:24:11:00:00:01, IPv4: 192.168.1.241
Starting arp-scan 1.10.0 with 256 hosts (https://github.com/royhills/arp-scan)
192.168.1.5\tdc:29:19:e0:38:2f\tAltoBeam (Xiamen) Technology Ltd, Co.
192.168.1.6\tb4:fb:e3:37:3f:3d\tAltoBeam (China) Inc.
192.168.1.10\tdc:29:19:e0:2b:fc\tAltoBeam (Xiamen) Technology Ltd, Co. (DUP: 2)
192.168.1.10\tdc:29:19:e0:38:2f\tAltoBeam (Xiamen) Technology Ltd, Co. (DUP: 3)
192.168.1.10\tdc:29:19:e0:38:d0\tAltoBeam (Xiamen) Technology Ltd, Co. (DUP: 4)
192.168.1.11\tdc:29:19:e0:2b:fc\tAltoBeam (Xiamen) Technology Ltd, Co.
192.168.1.31\t10:27:f5:09:a5:67\tTP-Link Corporation Limited
192.168.1.103\tb4:fb:e3:37:3f:3d\tAltoBeam (China) Inc.
192.168.1.213\tdc:29:19:e0:38:d0\tAltoBeam (Xiamen) Technology Ltd, Co. (DUP: 2)

9 packets received by filter, 0 packets dropped by kernel
"""

CONFIG = """cameras:
  entrada:
    ffmpeg:
      inputs:
        - path: rtsp://127.0.0.1:8554/entrada
          roles: [record]
  salida_pieza:
    ffmpeg:
      inputs:
        - path: rtsp://admin:{FRIGATE_RTSP_PASSWORD}@192.168.1.12:554/0/av0
          roles: [record]
go2rtc:
  streams:
    sala_gym:
      - rtsp://192.168.1.5:554/user=admin&password={FRIGATE_RTSP_PASSWORD}&channel=1&stream=0.sdp
    sala_gym_sub:
      - rtsp://192.168.1.5:554/user=admin&password={FRIGATE_RTSP_PASSWORD}&channel=1&stream=1.sdp
    cocina:
      - rtsp://192.168.1.6:554/user=admin&password={FRIGATE_RTSP_PASSWORD}&channel=1&stream=0.sdp
    quincho:
      - rtsp://192.168.1.11:554/user=admin&password={FRIGATE_RTSP_PASSWORD}&channel=1&stream=0.sdp
    entrada:
      - rtsp://192.168.1.10:554/user=admin&password={FRIGATE_RTSP_PASSWORD}&channel=1&stream=0.sdp
    entrada_sub:
      - rtsp://192.168.1.10:554/user=admin&password={FRIGATE_RTSP_PASSWORD}&channel=1&stream=1.sdp
"""


def empty_state():
    return {
        "cameras": {},
        "discovered": {},
        "ignored": [],
        "events": [],
        "last_scan": None,
    }


def load_cfg(text=CONFIG):
    return YAML().load(text)


class TestParsing(unittest.TestCase):
    def test_parse_arp_scan(self):
        entries = camlocator.parse_arp_scan(ARP)
        self.assertEqual(len(entries), 9)
        self.assertIn(
            (
                "192.168.1.10",
                "dc:29:19:e0:38:d0",
                "AltoBeam (Xiamen) Technology Ltd, Co.",
            ),
            entries,
        )

    def test_camera_hosts(self):
        hosts = camlocator.camera_hosts(load_cfg())
        self.assertEqual(hosts["sala_gym"], {"192.168.1.5"})
        self.assertEqual(hosts["entrada"], {"192.168.1.10"})
        self.assertEqual(hosts["salida_pieza"], {"192.168.1.12"})
        self.assertNotIn("127.0.0.1", set().union(*hosts.values()))


class TestLocate(unittest.TestCase):
    def setUp(self):
        self.entries = camlocator.parse_arp_scan(ARP)
        self.hosts = camlocator.camera_hosts(load_cfg())

    def test_learns_macs_but_never_from_the_factory_address(self):
        state = empty_state()
        moves, _ = camlocator.locate(
            state, self.hosts, self.entries, 100, probe=lambda ip: False
        )
        cams = state["cameras"]
        self.assertEqual(moves, {})
        self.assertEqual(cams["sala_gym"]["mac"], "dc:29:19:e0:38:2f")
        self.assertEqual(cams["cocina"]["status"], "ok")
        # .10 is answered by three cameras: no MAC is learned from it
        self.assertNotIn("mac", cams["entrada"])
        self.assertEqual(cams["entrada"]["status"], "factory_ip")
        self.assertEqual(cams["salida_pieza"]["status"], "not_seen")

    def test_follows_a_camera_that_moved(self):
        state = empty_state()
        state["cameras"]["entrada"] = {"mac": "dc:29:19:e0:38:d0"}
        moves, messages = camlocator.locate(
            state, self.hosts, self.entries, 100, probe=lambda ip: False
        )
        self.assertEqual(moves, {"entrada": ("192.168.1.10", "192.168.1.213")})
        self.assertEqual(state["cameras"]["entrada"]["status"], "moved")
        self.assertIn("192.168.1.213", messages[0])

    def test_two_own_leases_are_not_a_move(self):
        state = empty_state()
        camlocator.locate(state, self.hosts, self.entries, 100, probe=lambda ip: False)
        moves, _ = camlocator.locate(
            state, self.hosts, self.entries, 200, probe=lambda ip: False
        )
        self.assertNotIn("cocina", moves)

    def test_detects_new_cameras_once(self):
        entries = self.entries + [("192.168.1.40", "aa:bb:cc:00:11:22", "Hikvision")]
        state = empty_state()
        rtsp = {"192.168.1.40", "192.168.1.103"}
        _, messages = camlocator.locate(
            state, self.hosts, entries, 100, probe=lambda ip: ip in rtsp
        )
        self.assertIn("aa:bb:cc:00:11:22", state["discovered"])
        # the repeater has no RTSP; the kitchen's second lease belongs to a known camera
        self.assertNotIn("10:27:f5:09:a5:67", state["discovered"])
        self.assertNotIn("b4:fb:e3:37:3f:3d", state["discovered"])
        self.assertEqual(sum("nueva" in m for m in messages), 1)
        _, messages = camlocator.locate(
            state, self.hosts, entries, 200, probe=lambda ip: ip in rtsp
        )
        self.assertEqual(messages, [])
        state["ignored"].append("aa:bb:cc:00:11:22")
        camlocator.locate(state, self.hosts, entries, 300, probe=lambda ip: ip in rtsp)
        self.assertNotIn("aa:bb:cc:00:11:22", state["discovered"])

    def test_forgets_cameras_removed_from_config(self):
        state = empty_state()
        state["cameras"]["vieja"] = {"mac": "00:11:22:33:44:55"}
        camlocator.locate(state, self.hosts, self.entries, 100, probe=lambda ip: False)
        self.assertNotIn("vieja", state["cameras"])


class TestApplyMoves(unittest.TestCase):
    def test_rewrites_only_the_moved_camera(self):
        cfg = load_cfg()
        direct = camlocator.apply_moves(
            cfg,
            {
                "entrada": ("192.168.1.10", "192.168.1.213"),
                "salida_pieza": ("192.168.1.12", "192.168.1.26"),
            },
        )
        streams = cfg["go2rtc"]["streams"]
        self.assertTrue(streams["entrada"][0].startswith("rtsp://192.168.1.213:554/"))
        self.assertTrue(
            streams["entrada_sub"][0].startswith("rtsp://192.168.1.213:554/")
        )
        self.assertTrue(streams["sala_gym"][0].startswith("rtsp://192.168.1.5:554/"))
        self.assertIn("{FRIGATE_RTSP_PASSWORD}", streams["entrada"][0])
        path = cfg["cameras"]["salida_pieza"]["ffmpeg"]["inputs"][0]["path"]
        self.assertEqual(
            path, "rtsp://admin:{FRIGATE_RTSP_PASSWORD}@192.168.1.26:554/0/av0"
        )
        self.assertTrue(direct)

    def test_does_not_touch_longer_addresses(self):
        self.assertEqual(
            camlocator._replace_ip(
                "rtsp://192.168.1.101:554/x", "192.168.1.10", "192.168.1.9"
            ),
            "rtsp://192.168.1.101:554/x",
        )


if __name__ == "__main__":
    unittest.main()
