import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from frigate.orbi360 import camerapassword, camlocator


class TestCameraPassword(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = Path(self.tmp.name) / "orbi360-nvr.env"
        self.patch = mock.patch.object(camlocator, "ENV_FILE", str(self.env))
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_sets_and_replaces_keeping_other_lines(self):
        self.env.write_text("PATH=/usr/bin\nLANG=C.UTF-8\n")
        self.assertFalse(camerapassword.is_set())
        camerapassword.set_password("clave.Cam-1")
        camerapassword.set_password("otra_clave")
        self.assertEqual(
            self.env.read_text().splitlines(),
            ["PATH=/usr/bin", "LANG=C.UTF-8", "FRIGATE_RTSP_PASSWORD=otra_clave"],
        )
        self.assertTrue(camerapassword.is_set())
        if os.name == "posix":
            self.assertEqual(self.env.stat().st_mode & 0o777, 0o600)

    def test_rejects_characters_that_break_camera_urls(self):
        for bad in ("abc", "con espacio", "a@b", "a&b", "a#b", "a/b", "a:b", "x" * 65):
            with self.assertRaises(camerapassword.PasswordError, msg=bad):
                camerapassword.set_password(bad)
        self.assertFalse(self.env.exists())


if __name__ == "__main__":
    unittest.main()
