import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ruamel.yaml import YAML

from frigate.orbi360 import camadd, camlocator

CONFIG = """mqtt:
  enabled: false
go2rtc:
  streams:
    cocina:
      - rtsp://192.168.1.6:554/user=admin&password={FRIGATE_RTSP_PASSWORD}&channel=1&stream=0.sdp
cameras:
  cocina:
    friendly_name: Cocina
    ffmpeg:
      inputs:
        - path: rtsp://127.0.0.1:8554/cocina
          roles:
            - record
"""


class TestSlug(unittest.TestCase):
    def test_slug(self):
        self.assertEqual(camadd.slug("Patio Norte"), "patio_norte")
        self.assertEqual(
            camadd.slug("Salida Pieza Principal"), "salida_pieza_principal"
        )
        self.assertEqual(camadd.slug("Baño / Niños"), "bano_ninos")
        self.assertEqual(camadd.slug("2do piso"), "cam_2do_piso")


class TestEntries(unittest.TestCase):
    def test_xiongmai_rtsp(self):
        main, sub, cam = camadd.camera_entries(
            "patio", "Patio", "xm_rtsp", "192.168.1.40"
        )
        self.assertEqual(
            main,
            [
                "rtsp://192.168.1.40:554/user=admin&password={FRIGATE_RTSP_PASSWORD}&channel=1&stream=0.sdp"
            ],
        )
        self.assertTrue(sub[0].endswith("stream=1.sdp"))
        self.assertNotIn("output_args", cam["ffmpeg"])
        self.assertEqual(
            cam["ffmpeg"]["inputs"][1]["path"], "rtsp://127.0.0.1:8554/patio_sub"
        )

    def test_dvrip_is_recorded_without_audio(self):
        main, sub, cam = camadd.camera_entries(
            "garaje", "Garaje", "dvrip", "192.168.1.37"
        )
        self.assertEqual(
            main,
            [
                "dvrip://admin:{FRIGATE_RTSP_PASSWORD}@192.168.1.37:34567?channel=0&subtype=0"
            ],
        )
        self.assertTrue(sub[0].endswith("subtype=1"))
        self.assertEqual(
            cam["ffmpeg"]["output_args"]["record"], "preset-record-generic"
        )
        self.assertEqual(list(cam["ffmpeg"]["hwaccel_args"]), [])

    def test_custom_urls(self):
        main, sub, _ = camadd.camera_entries(
            "ezviz",
            "EZVIZ",
            "custom",
            main_url="rtsp://admin:x@192.168.1.19:554/ch1/main",
        )
        self.assertEqual(main, sub)  # no sub URL: the main one is used for both
        with self.assertRaises(camadd.AddError):
            camadd.camera_entries("ezviz", "EZVIZ", "custom", main_url="ftp://x")


class TestAddCamera(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.config = base / "config.yml"
        self.config.write_text(CONFIG)
        self.state = base / "camera-network.json"
        self.patches = [
            mock.patch.object(camadd, "CONFIG_FILE", self.config),
            mock.patch.object(camlocator, "STATE_FILE", self.state),
            mock.patch.object(camlocator, "LOCK_FILE", base / "lock"),
            # the real one takes an flock (Linux only)
            mock.patch.object(camlocator, "_with_saved_state", self._saved_state),
        ]
        for p in self.patches:
            p.start()

    @staticmethod
    def _saved_state(change):
        state = camlocator.load_state()
        result = change(state)
        camlocator.save_state(state)
        return result

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_writes_config_and_mac(self):
        state = camlocator.load_state()
        state["discovered"]["10:65:19:0a:d2:fe"] = {"ip": "192.168.1.37"}
        camlocator.save_state(state)

        result = camadd.add_camera(
            "garaje",
            "Garaje",
            "dvrip",
            "192.168.1.37",
            mac="10:65:19:0A:D2:FE",
            restart=False,
        )
        cfg = YAML().load(self.config.read_text())
        self.assertIn("garaje", cfg["cameras"])
        self.assertIn("garaje_sub", cfg["go2rtc"]["streams"])
        self.assertEqual(
            cfg["cameras"]["cocina"]["friendly_name"], "Cocina"
        )  # untouched
        self.assertTrue((self.config.parent / result["backup"]).exists())
        saved = json.loads(self.state.read_text())
        self.assertEqual(saved["cameras"]["garaje"]["mac"], "10:65:19:0a:d2:fe")
        self.assertEqual(saved["discovered"], {})

    def test_never_assigns_a_repeater_mac(self):
        rep = "10:27:f5:09:a5:67"
        state = camlocator.load_state()
        state["discovered"][f"{rep}@192.168.1.111"] = {"ip": "192.168.1.111"}
        camlocator.save_state(state)
        result = camadd.add_camera(
            "patio_pieza",
            "Patio Pieza",
            "dvrip",
            "192.168.1.111",
            mac=f"{rep}@192.168.1.111",
            restart=False,
        )
        saved = json.loads(self.state.read_text())
        self.assertNotIn("patio_pieza", saved["cameras"])
        self.assertEqual(saved["discovered"], {})
        self.assertIn("repetidor", result["notes"][0])

    def test_rejects_duplicates_and_bad_names(self):
        with self.assertRaises(camadd.AddError):
            camadd.add_camera(
                "cocina", "Cocina", "xm_rtsp", "192.168.1.6", restart=False
            )
        with self.assertRaises(camadd.AddError):
            camadd.add_camera("Mala Cam", "x", "xm_rtsp", "192.168.1.6", restart=False)
        self.assertEqual(self.config.read_text(), CONFIG)  # nothing written


class TestProbe(unittest.TestCase):
    def test_prefers_rtsp_then_dvrip(self):
        with (
            mock.patch.object(camlocator, "port_open", return_value=True),
            mock.patch.object(camlocator, "stream_ok", return_value=True),
        ):
            self.assertEqual(camadd.probe("192.168.1.6")["protocol"], "xm_rtsp")
        with (
            mock.patch.object(
                camlocator, "port_open", side_effect=lambda ip, port: port == 34567
            ),
            mock.patch.object(camadd, "_dvrip_login", return_value=203),
        ):
            result = camadd.probe("192.168.1.37")
            self.assertIsNone(result["protocol"])
            self.assertIn("xmcam passwd", result["message"])
        with (
            mock.patch.object(
                camlocator, "port_open", side_effect=lambda ip, port: port == 34567
            ),
            mock.patch.object(camadd, "_dvrip_login", return_value=100),
            mock.patch.object(camadd, "_dvrip_codec", return_value="H.265"),
        ):
            self.assertEqual(
                camadd.probe("192.168.1.37"),
                {"protocol": "dvrip", "ip": "192.168.1.37", "codec": "H.265"},
            )


if __name__ == "__main__":
    unittest.main()
