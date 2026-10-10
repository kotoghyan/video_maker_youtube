from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import json
from vinyl_codex.captions import captions
from vinyl_codex.config import Config
from vinyl_codex.prepare import draft_plan, atomic_json
from vinyl_codex.safety import SafeError


class PrepareSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.archive, self.work = root / "archive", root / "work"
        self.archive.mkdir()
        self.work.mkdir()
        self.config = Config(self.archive, self.work)

    def test_invalid_record_does_not_create_outputs(self):
        with self.assertRaises(SafeError):
            draft_plan(self.config, self.archive, "D01_A01")
        self.assertEqual(list(self.work.iterdir()), [])

    def test_only_selected_track(self):
        with self.assertRaises(SafeError):
            draft_plan(self.config, self.archive, "D01_A02")

    def test_outside_record_forbidden(self):
        with self.assertRaises(SafeError):
            draft_plan(self.config, self.work, "D01_A01")

    def test_atomic_state_cannot_write_archive(self):
        with self.assertRaises(SafeError):
            atomic_json(self.config, self.archive / "state.json", {"status": "draft"})
        self.assertEqual(list(self.archive.iterdir()), [])

    def test_atomic_state_roundtrip(self):
        import json
        path = self.work / "state.json"
        atomic_json(self.config, path, {"status": "draft", "approval": None})
        self.assertIsNone(json.loads(path.read_text())["approval"])
        self.assertFalse(path.with_name("state.json.pending").exists())

    def test_stale_pending_does_not_overwrite(self):
        path = self.work / "state.json"
        path.write_text("original state")
        path.with_name("state.json.pending").write_text("interrupted")
        with self.assertRaises(FileExistsError):
            atomic_json(self.config, path, {"status": "draft"})
        self.assertEqual(path.read_text(), "original state")

    def fixture(self):
        record = self.archive / "246 - Synthetic"
        for name in ("IMAGES", "TRACKS", "METADATA"):
            (record / name).mkdir(parents=True)
        for name in ("image00013.jpg", "image00014.jpg", "image00017.jpg"):
            (record / "IMAGES" / name).write_bytes(b"photo")
        (record / "TRACKS" / "audio.wav").write_bytes(b"audio")
        (record / "METADATA" / "metadata.json").write_bytes(b"metadata")
        selected = dict(disc="D01", side="A", track="01", work="Hidjaz",
                        composer="Alexandre Spendiarian", conductor="Varoujan Kevorkian",
                        ensemble="Orquesta de Camara", file_name="audio.wav")
        return record, selected

    def test_v2_preserves_v1_without_logo_requirement(self):
        record, selected = self.fixture()
        previous = self.work / "246" / "D01_A01" / "draft-v1"
        previous.mkdir(parents=True)
        (previous / "video.mp4").write_bytes(b"previous")
        with patch("vinyl_codex.prepare.read_approved_246", return_value={"works": [selected]}):
            *_, target = draft_plan(self.config, record, "D01_A01")
        self.assertEqual(target.name, "draft-v2")
        self.assertFalse(target.exists())
        self.assertEqual((previous / "video.mp4").read_bytes(), b"previous")

    def test_ready_version_cannot_be_overwritten(self):
        record, selected = self.fixture()
        target = self.work / "246" / "D01_A01" / "draft-v2"
        target.mkdir(parents=True)
        (target / "state.json").write_text(json.dumps({"status": "ready_for_review"}))
        with patch("vinyl_codex.prepare.read_approved_246", return_value={"works": [selected]}):
            for resume in (False, True):
                with self.assertRaises(SafeError):
                    draft_plan(self.config, record, "D01_A01", resume)

    def test_public_text_uses_metadata_without_internal_id(self):
        _, selected = self.fixture()
        selected["museum_id"] = "246"
        text = captions(selected)
        self.assertNotIn("246", text)
        self.assertNotIn("Museum ID", text)
        self.assertNotIn("Թանգարանային ID", text)
        self.assertIn("Alexandre Spendiarian", text)
        self.assertIn("Varoujan Kevorkian", text)
