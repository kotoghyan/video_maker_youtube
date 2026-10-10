import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from vinyl_codex.__main__ import main
from vinyl_codex.catalog import discover
from vinyl_codex.config import Config, load_config
from vinyl_codex.inventory import dry_run
from vinyl_codex.metadata import RELEASE_STRINGS, TRACK_FIELDS
from vinyl_codex.safety import SafeError, local_file, museum_id, output_path
from vinyl_codex.technical import inspect_media


class SafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.archive = self.base / "archive"
        self.archive.mkdir()
        self.work = self.base / "work"
        self.work.mkdir()
        self.config = Config(self.archive, self.work)
        self.record = self.archive / "900001 - Synthetic Fixture"
        self.record.mkdir()
        for name in ("VIDEO", "IMAGES", "TRACKS", "METADATA"):
            (self.record / name).mkdir()
        self.track = {key: "Unknown" for key in TRACK_FIELDS}
        self.track.update(disc="D01", side="A", track="01",
                          file_name="900001_D01_A01 - Synthetic.wav")
        (self.record / "TRACKS" / self.track["file_name"]).write_bytes(b"synthetic fixture")
        self.data = {key: "Unknown" for key in RELEASE_STRINGS}
        self.data.update(museum_id="900001", number_of_discs=1, tracks=[self.track], notes="")
        self.metadata = self.record / "METADATA" / "900001_metadata.json"
        self.save()
        self.config_path = self.base / "config.json"
        self.config_path.write_text(json.dumps({"ARCHIVE_ROOT": str(self.archive),
                                               "WORK_ROOT": str(self.work)}))

    def save(self):
        self.metadata.write_text(json.dumps(self.data), encoding="utf-8")

    def snapshot(self):
        return {str(p.relative_to(self.archive)): (hashlib.sha256(p.read_bytes()).hexdigest(),
                                                  p.stat().st_mtime_ns)
                for p in self.archive.rglob("*") if p.is_file()}

    def test_dry_run_never_writes_or_networks(self):
        before = self.snapshot()
        original_open = Path.open
        def read_only(path, mode="r", *args, **kwargs):
            if any(flag in mode for flag in "wax+"):
                self.fail("dry-run attempted file write")
            return original_open(path, mode, *args, **kwargs)
        with patch("pathlib.Path.open", read_only), patch("socket.socket", side_effect=AssertionError("network")):
            report = dry_run(self.config, "900001")
            self.assertEqual(report["uploads"], 0)
            self.assertFalse(report["published"])
            self.assertEqual(report["track_count"], 1)
        self.assertEqual(before, self.snapshot())
        self.assertEqual(list(self.work.iterdir()), [])

    def test_invalid_ids(self):
        for value in ("", "../900001", "900001/VIDEO", "C:\\x", "９００", "1:stream"):
            with self.subTest(value=value), self.assertRaises(SafeError):
                museum_id(value)

    def test_overlap(self):
        for archive, work in ((self.archive, self.archive), (self.archive, self.record),
                              (self.archive, self.base)):
            with self.assertRaises(SafeError):
                Config(archive, work)

    def test_relative_config(self):
        with self.assertRaises(SafeError):
            Config(Path("relative"), self.work)

    def test_write_archive_forbidden(self):
        with self.assertRaises(SafeError):
            output_path(self.metadata, self.archive, self.work)

    def test_output_traversal(self):
        with self.assertRaises(SafeError):
            output_path(self.work / ".." / "escape.json", self.archive, self.work)

    def test_unknown_id_and_no_prefix_collision(self):
        for selected in ("9", "90000", "111"):
            with self.assertRaises(SafeError):
                discover(self.config, selected)

    def test_ambiguous_folder(self):
        (self.archive / "900001 - Other").mkdir()
        with self.assertRaises(SafeError):
            discover(self.config, "900001")

    def test_missing_archive(self):
        with self.assertRaises(SafeError):
            discover(Config(self.base / "missing", self.work), "900001")

    def test_missing_optional_folders(self):
        (self.record / "VIDEO").rmdir()
        report = dry_run(self.config, "900001")
        self.assertEqual(report["media"]["VIDEO"]["status"], "missing")
        self.assertEqual(report["media"]["IMAGES"]["status"], "empty")

    def test_missing_json(self):
        self.metadata.unlink()
        with self.assertRaises(OSError):
            dry_run(self.config, "900001")

    def test_missing_track(self):
        (self.record / "TRACKS" / self.track["file_name"]).unlink()
        with self.assertRaises(OSError):
            dry_run(self.config, "900001")

    def test_empty_track(self):
        (self.record / "TRACKS" / self.track["file_name"]).write_bytes(b"")
        with self.assertRaises(SafeError):
            dry_run(self.config, "900001")

    def test_wrong_json_id(self):
        self.data["museum_id"] = "111"
        self.save()
        with self.assertRaises(SafeError):
            dry_run(self.config, "900001")

    def test_extra_metadata_fields(self):
        self.data["social_title"] = "forbidden"
        self.save()
        with self.assertRaises(SafeError):
            dry_run(self.config, "900001")

    def test_track_path_traversal(self):
        self.track["file_name"] = "../escape.wav"
        self.save()
        with self.assertRaises(SafeError):
            dry_run(self.config, "900001")

    def test_duplicate_json_keys(self):
        self.metadata.write_text('{"museum_id":"900001","museum_id":"111"}')
        with self.assertRaises(SafeError):
            dry_run(self.config, "900001")

    def test_invalid_json_safe_error(self):
        self.metadata.write_text("PRIVATE_INVALID_CONTENT")
        output = io.StringIO()
        with contextlib.redirect_stderr(output):
            status = main(["--config", str(self.config_path), "dry-run", "--museum-id", "900001"])
        self.assertEqual(status, 2)
        self.assertNotIn("PRIVATE_INVALID_CONTENT", output.getvalue())
        self.assertNotIn("Traceback", output.getvalue())
        self.assertEqual(json.loads(output.getvalue())["uploads"], 0)

    def test_unknown_config_fields(self):
        self.config_path.write_text('{"token":"PRIVATE"}')
        with self.assertRaises(SafeError):
            load_config(self.config_path)

    def test_cloud_placeholder_not_read(self):
        from types import SimpleNamespace
        target = self.record / "TRACKS" / self.track["file_name"]
        with patch("vinyl_codex.safety.no_links"), patch("vinyl_codex.safety.inside", return_value=target), patch.object(Path, "stat", return_value=SimpleNamespace(st_file_attributes=0x400000)):
            with self.assertRaises(SafeError):
                local_file(target, self.record)

    def test_junction_escape(self):
        import os
        import subprocess
        if os.name != "nt":
            self.skipTest("Windows junction")
        link = self.work / "archive-link"
        result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(self.archive)],
                                capture_output=True)
        self.assertEqual(result.returncode, 0)
        self.addCleanup(link.rmdir)
        with self.assertRaises(SafeError):
            output_path(link / "new.json", self.archive, self.work)
        self.config_path.write_text(json.dumps({"ARCHIVE_ROOT": str(link),
                                               "WORK_ROOT": str(self.base / "other")}))
        with self.assertRaises(SafeError):
            load_config(self.config_path)

    def test_extension_does_not_prove_validity(self):
        (self.record / "VIDEO" / "fake.mp4").write_bytes(b"not real video")
        report = dry_run(self.config, "900001")
        self.assertEqual(report["media"]["VIDEO"]["files"][0]["technical_validity"], "not_checked")
        self.assertEqual(report["media_selection"], "requires_technical_validation")

    def test_cli_success(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = main(["--config", str(self.config_path), "dry-run", "--museum-id", "900001"])
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(output.getvalue())["mode"], "dry-run")

    def test_track_order(self):
        self.track["track"] = "02"
        self.save()
        with self.assertRaises(SafeError):
            dry_run(self.config, "900001")

    def test_technical_rejects_outside_archive_before_tool(self):
        with patch("subprocess.run") as run, self.assertRaises(SafeError):
            inspect_media(self.config, "900001", self.work, "C:/missing/ffprobe.exe")
        run.assert_not_called()

    def test_technical_does_not_read_museum_json(self):
        from types import SimpleNamespace
        self.metadata.write_text("intentionally incompatible JSON")
        before = self.snapshot()
        tool = self.base / "ffprobe.exe"
        tool.write_bytes(b"test only")
        response = SimpleNamespace(returncode=0, stdout=json.dumps({
            "streams": [{"codec_type": "audio", "codec_name": "pcm_s24le"}],
            "format": {"duration": "1.0"}}))
        with patch("subprocess.run", return_value=response):
            report = inspect_media(self.config, "900001", self.record, tool)
        self.assertEqual(report["metadata_validation"], "blocked_standard_mismatch")
        self.assertEqual(before, self.snapshot())
        self.assertFalse(report["published"])
        self.assertEqual(list(self.work.iterdir()), [])

    def test_technical_marks_probe_failure(self):
        from types import SimpleNamespace
        tool = self.base / "ffprobe.exe"
        tool.write_bytes(b"test only")
        with patch("subprocess.run", return_value=SimpleNamespace(returncode=1)):
            report = inspect_media(self.config, "900001", self.record, tool)
        self.assertEqual(report["media"]["TRACKS"]["files"][0]["technical_validity"], "probe_failed")


if __name__ == "__main__":
    unittest.main()
