import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from vinyl_codex.config import Config
from vinyl_codex.inventory import dry_run
from vinyl_codex.legacy246 import ROOT_FIELDS, MUSIC_FIELDS, read_approved_246
from vinyl_codex.safety import SafeError


class Legacy246Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        archive, work = base / "archive", base / "work"
        archive.mkdir()
        work.mkdir()
        self.config = Config(archive, work)
        self.record = archive / "category" / "246 - Synthetic"
        for name in ("METADATA", "TRACKS"):
            (self.record / name).mkdir(parents=True)
        self.item = {k: "" for k in MUSIC_FIELDS}
        self.item.update(Disc="D01", Side="A", Track="01", Composer="Synthetic Composer",
                         Work="Complete Work", Movement="Part One; Part Two")
        self.data = {k: "Unknown" for k in ROOT_FIELDS}
        self.data.update({"Museum ID": "246", "Number of Discs": 1, "Music": [self.item]})
        self.path = self.record / "METADATA" / "metadata.json"
        self.wav = self.record / "TRACKS" / "246_D01_A01 - Synthetic Composer - Complete Work.wav"
        self.wav.write_bytes(b"synthetic")
        self.save()

    def save(self):
        self.path.write_text(json.dumps(self.data), encoding="utf-8")

    def test_preserves_grouping_and_original(self):
        before = hashlib.sha256(self.path.read_bytes()).hexdigest()
        report = dry_run(self.config, "246", self.record, "approved-246")
        self.assertEqual(report["track_count"], 1)
        self.assertEqual(report["works"][0]["movement"], "Part One; Part Two")
        self.assertEqual(report["works"][0]["mapping"], "exact_id_and_title")
        self.assertEqual(before, hashlib.sha256(self.path.read_bytes()).hexdigest())
        self.assertEqual(list(self.config.work.iterdir()), [])

    def test_no_implicit_profile(self):
        with self.assertRaises(OSError):
            dry_run(self.config, "246", self.record)

    def test_other_id_forbidden(self):
        with self.assertRaises(SafeError):
            read_approved_246(self.record, "247")

    def test_ambiguous_wav(self):
        (self.record / "TRACKS" / "246_D01_A01 - Another Work.wav").write_bytes(b"x")
        with self.assertRaises(SafeError):
            read_approved_246(self.record, "246")

    def test_title_mismatch(self):
        self.item["Work"] = "Wrong Work"
        self.save()
        with self.assertRaises(SafeError):
            read_approved_246(self.record, "246")

    def test_duplicate_entry(self):
        self.data["Music"].append(dict(self.item))
        self.save()
        with self.assertRaises(SafeError):
            read_approved_246(self.record, "246")

    def test_extra_field_blocked(self):
        self.data["New Field"] = "not allowed"
        self.save()
        with self.assertRaises(SafeError):
            read_approved_246(self.record, "246")

    def test_missing_wav(self):
        self.wav.unlink()
        with self.assertRaises(SafeError):
            read_approved_246(self.record, "246")
