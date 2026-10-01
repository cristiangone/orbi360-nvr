import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

from frigate.orbi360 import mosaics


def make(**overrides) -> dict:
    data = {
        "id": "principal",
        "name": "Principal",
        "streams": ["a_sub", "b_sub", "c_sub", "d_sub"],
        "srt_port": 9999,
    }
    data.update(overrides)
    return data


class TestMosaicValidation(unittest.TestCase):
    def test_defaults(self):
        mosaic = mosaics.Mosaic(**make())
        self.assertTrue(mosaic.enabled)
        self.assertEqual(mosaic.resolution, "1920x1080")
        self.assertEqual(mosaic.encoder, "auto")

    def test_rejects_unsafe_values(self):
        for bad in (
            make(id="Mal Id"),
            make(id="x;rm"),
            make(streams=["a", "b", "c"]),
            make(streams=["a", "b", "c", "d$(id)"]),
            make(srt_port=80),
            make(srt_port=8554),
            make(srt_port=60000),
            make(encoder="nvenc"),
        ):
            with self.assertRaises(ValidationError, msg=bad):
                mosaics.Mosaic(**bad)

    def test_ports_and_ids_must_be_unique(self):
        with self.assertRaises(ValidationError):
            mosaics.MosaicList(mosaics=[make(), make(id="otro")])
        with self.assertRaises(ValidationError):
            mosaics.MosaicList(mosaics=[make(), make(srt_port=10000)])
        with self.assertRaises(ValidationError):
            # the internal UDP port of 9999 is 19999
            mosaics.MosaicList(mosaics=[make(), make(id="otro", srt_port=19999)])
        mosaics.MosaicList(mosaics=[make(), make(id="otro", srt_port=10001)])


class TestMosaicFiles(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.patches = [
            patch.object(mosaics, "MOSAICS_DIR", base / "orbi360"),
            patch.object(mosaics, "MOSAICS_FILE", base / "orbi360" / "mosaics.json"),
            patch.object(mosaics, "CONF_DIR", base / "orbi360" / "mosaics"),
            patch.object(mosaics, "LEGACY_CONF", base / "orbi360-mosaico.conf"),
            patch.object(mosaics, "systemd_available", return_value=False),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_render_conf(self):
        conf = mosaics.render_conf(mosaics.Mosaic(**make(resolution="1280x720")))
        self.assertIn('CAMS="a_sub b_sub c_sub d_sub"', conf)
        self.assertIn("SOURCE=direct", conf)
        self.assertIn("UDP_PORT=19999", conf)
        self.assertIn("TILE_W=640", conf)

    def test_save_load_and_apply_without_systemd(self):
        mosaic_list = mosaics.MosaicList(mosaics=[make(), make(id="b", srt_port=9000)])
        mosaics.save(mosaic_list)
        self.assertEqual(mosaics.load(), mosaic_list)

        status = mosaics.apply(mosaic_list)
        self.assertEqual(status, {"principal": "unsupported", "b": "unsupported"})
        self.assertTrue((mosaics.CONF_DIR / "b.conf").exists())

        mosaics.apply(mosaics.MosaicList(mosaics=[make()]))
        self.assertFalse((mosaics.CONF_DIR / "b.conf").exists())

    def test_migrate_legacy(self):
        mosaics.LEGACY_CONF.write_text(
            '# comentario\nCAMS="sala_gym cocina quincho entrada"\n'
            "SOURCE=sub\nSRT_PORT=9999   # UDP\nBITRATE=2500\nENCODER=auto\n"
        )
        self.assertTrue(mosaics.migrate_legacy())
        migrated = mosaics.load().mosaics[0]
        self.assertEqual(migrated.id, "principal")
        self.assertEqual(migrated.streams[0], "sala_gym_sub")
        self.assertEqual(migrated.srt_port, 9999)
        # only once
        self.assertFalse(mosaics.migrate_legacy())

    def test_migrate_ignores_placeholder(self):
        mosaics.LEGACY_CONF.write_text('CAMS="CAMARA1 CAMARA2 CAMARA3 CAMARA4"\n')
        self.assertFalse(mosaics.migrate_legacy())


if __name__ == "__main__":
    unittest.main()
