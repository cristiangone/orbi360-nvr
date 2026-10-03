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
            make(streams=[]),
            make(streams=[f"s{i}" for i in range(10)]),
            make(streams=["a", "b", "c", "d$(id)"]),
            make(srt_port=80),
            make(srt_port=8554),
            make(srt_port=60000),
            make(encoder="nvenc"),
            make(passphrase="corta"),
            make(passphrase="con espacios no"),
            make(passphrase="x" * 80),
            make(passphrase="clave$(reboot)ok"),
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
        self.assertIn("OUT_W=1280", conf)
        self.assertIn("OUT_H=720", conf)

    def test_passphrase(self):
        plain = mosaics.render_conf(mosaics.Mosaic(**make()))
        self.assertIn("SRT_PASSPHRASE=\n", plain)
        empty = mosaics.Mosaic(**make(passphrase=""))
        self.assertIsNone(empty.passphrase)
        secured = mosaics.Mosaic(**make(passphrase="Orbi360-Temuco.2026"))
        self.assertIn(
            "SRT_PASSPHRASE=Orbi360-Temuco.2026\n", mosaics.render_conf(secured)
        )

    def test_caller_mode(self):
        caller = mosaics.Mosaic(
            **make(
                mode="caller",
                target_host="stream.orbi360.cl",
                target_port=8890,
                stream_id="#!::r=live/cam,m=publish",
            )
        )
        conf = mosaics.render_conf(caller)
        self.assertIn("MODE=caller", conf)
        self.assertIn("TARGET_HOST=stream.orbi360.cl", conf)
        self.assertIn("TARGET_PORT=8890", conf)
        self.assertIn("STREAM_ID='#!::r=live/cam,m=publish'", conf)

        listener = mosaics.render_conf(mosaics.Mosaic(**make()))
        self.assertIn("MODE=listener", listener)
        self.assertIn("STREAM_ID=''", listener)

    def test_caller_mode_rejects_bad_targets(self):
        for bad in (
            make(mode="caller"),
            make(mode="caller", target_host="1.2.3.4"),
            make(mode="caller", target_port=8890),
            make(mode="caller", target_host="-oProxy", target_port=8890),
            make(mode="caller", target_host="a b", target_port=8890),
            make(mode="caller", target_host="x", target_port=70000),
            make(stream_id="live/cam&passphrase=x"),
            make(stream_id="it's"),
            make(stream_id="$(reboot)"),
        ):
            with self.assertRaises(ValidationError, msg=bad):
                mosaics.Mosaic(**bad)

    def test_any_count_from_one_to_nine(self):
        for count in range(1, 10):
            mosaic = mosaics.Mosaic(**make(streams=[f"s{i}" for i in range(count)]))
            self.assertIn(
                f'CAMS="{" ".join(mosaic.streams)}"', mosaics.render_conf(mosaic)
            )

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

    def test_name_is_shell_quoted(self):
        conf = mosaics.render_conf(mosaics.Mosaic(**make(name="Patio $(reboot) 'x'")))
        self.assertIn("NAME='Patio $(reboot) '\"'\"'x'\"'\"''\n", conf)

    def test_runtime_state(self):
        state = Path(self.tmp.name)
        with patch.object(mosaics, "STATE_DIR", state):
            self.assertIsNone(mosaics.runtime("principal"))
            (state / "principal.srt").write_text("connected 1700000000\n")
            (state / "principal.enc").write_text("ok 1700000005 3\n")
            self.assertEqual(
                mosaics.runtime("principal"),
                {
                    "srt": "connected",
                    "srt_since": 1700000000,
                    "encoder": "ok",
                    "encoder_since": 1700000005,
                    "restarts": 3,
                    "missing": [],
                },
            )
            (state / "principal.cams").write_text(
                "missing 1700000009 entrada_sub,cocina_sub\n"
            )
            self.assertEqual(
                mosaics.runtime("principal")["missing"], ["entrada_sub", "cocina_sub"]
            )
            (state / "principal.enc").write_text("garbage")
            self.assertEqual(mosaics.runtime("principal")["encoder"], "unknown")


if __name__ == "__main__":
    unittest.main()
