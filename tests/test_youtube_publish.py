import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from vinyl_codex.config import Config
from vinyl_codex.safety import SafeError
from vinyl_codex import youtube_publish as pub


class PublishTests(unittest.TestCase):
    def test_duration_parsing_preserves_full_length_check(self):
        self.assertEqual(pub.duration_seconds("PT40M18S"), 2418)
        self.assertEqual(pub.duration_seconds("P0D"), 0)
        self.assertEqual(pub.duration_seconds("PT5M46.375S"), 346.375)
        self.assertIsNone(pub.duration_seconds("invalid"))

    def test_only_official_primary_publication_endpoints(self):
        for method, url in (("DELETE", pub.API + "videos"), ("PUT", pub.API + "videos"),
                            ("POST", "https://evil.example/upload/youtube/v3/videos"),
                            ("PUT", "https://www.googleapis.com.evil.example/upload/youtube/v3/videos")):
            with self.assertRaises(SafeError):
                pub.validate_url(url, method)
        pub.validate_url(pub.UPLOAD + "videos?upload_id=synthetic", "PUT")

    def test_safe_reason_never_displays_google_message(self):
        value = {"error": {"message": "synthetic-secret", "errors": [{"reason": "quotaExceeded"}]}}
        self.assertEqual(pub.safe_reason(json.dumps(value).encode()), "quotaExceeded")
        value["error"]["errors"][0]["reason"] = "https://secret.example/"
        self.assertEqual(pub.safe_reason(json.dumps(value).encode()), "unknown")

    def test_range_rejects_overflow_and_noncontinuous(self):
        self.assertEqual(pub.acknowledged({"Range": "bytes=0-255"}, 512), 256)
        self.assertEqual(pub.acknowledged({}, 512), 0)
        for value in ("bytes=1-255", "bytes=0-512", "other"):
            with self.assertRaises(SafeError):
                pub.acknowledged({"Range": value}, 512)

    def test_final_response_requires_video_id(self):
        with self.assertRaises(SafeError):
            pub.final_video(b'{"id":"not-a-valid-video-id"}')

    def test_resuming_completed_session_never_posts_again(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.mp4"
            path.write_bytes(b"synthetic")
            api = Mock()
            api.send.return_value = (201, {}, b'{"id":"abcdefghijk"}')
            result = pub.resumable(api, {"video": str(path)},
                                   {"url": pub.UPLOAD + "videos?upload_id=synthetic"}, Mock())
            self.assertEqual(result["id"], "abcdefghijk")
            self.assertEqual(api.send.call_args.args[0], "PUT")
            self.assertEqual(api.send.call_count, 1)

    def test_uncertain_initiation_stops_without_duplicate(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.mp4"
            path.write_bytes(b"synthetic")
            api = Mock()
            with self.assertRaises(SafeError):
                pub.resumable(api, {"video": str(path)}, {"phase": "initiating"}, Mock())
            api.send.assert_not_called()

    def test_known_upload_limit_before_media_is_saved(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.mp4"
            path.write_bytes(b"synthetic")
            api = Mock()
            api.send.side_effect = pub.ApiFailure(400, "uploadLimitExceeded")
            session, persist = {}, Mock()
            item = {"video": str(path), "title": "Title", "description": "Description", "categoryId": "10"}
            with self.assertRaisesRegex(SafeError, "uploadLimitExceeded"):
                pub.resumable(api, item, session, persist)
            self.assertEqual(session["phase"], "blocked_before_media")
            self.assertNotIn("url", session)
            self.assertEqual(api.send.call_count, 1)

    def test_metadata_and_chunked_upload_after_interruption(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.mp4"
            path.write_bytes(b"a" * 512)
            item = {"video": str(path), "title": "Synthetic title", "description": "Synthetic description",
                    "categoryId": "10", "material": "album"}
            api = Mock()
            api.send.side_effect = [(200, {"Location": pub.UPLOAD + "videos?upload_id=synthetic"}, b""),
                                    (308, {}, b""), pub.ApiFailure(0, "connectionInterrupted"),
                                    (308, {"Range": "bytes=0-255"}, b""),
                                    (201, {}, b'{"id":"abcdefghijk"}')]
            session = {}
            with patch.object(pub, "CHUNK", 256), patch.object(pub.time, "sleep"), patch.object(pub, "progress"):
                result = pub.resumable(api, item, session, Mock())
            calls = api.send.call_args_list
            self.assertEqual(sum(c.args[0] == "POST" for c in calls), 1)
            metadata = json.loads(calls[0].args[2])
            self.assertEqual(metadata["status"], {"privacyStatus": "public", "selfDeclaredMadeForKids": False})
            self.assertEqual(calls[-1].args[3]["Content-Range"], "bytes 256-511/512")
            self.assertEqual(result["id"], "abcdefghijk")

    def test_channel_mismatch_stops(self):
        api = Mock()
        api.get.return_value = {"items": [{"id": "wrong-channel"}]}
        with self.assertRaises(SafeError):
            pub.verify_channel(api, "approved-channel")

    def test_duplicates_exclude_only_known_uploaded_ids(self):
        api = Mock()
        api.get.return_value = {"items": [
            {"snippet": {"title": "Artist — Song", "resourceId": {"videoId": "known"}}},
            {"snippet": {"title": "Artist — Song", "resourceId": {"videoId": "other"}}}]}
        package = {"items": [{"title": "Artist — Song | Archive recording"}]}
        channel = {"contentDetails": {"relatedPlaylists": {"uploads": "playlist"}}}
        report = pub.duplicates(api, channel, package, {"known"})
        self.assertEqual(report["potential_duplicates"], [{"id": "other", "title": "Artist — Song"}])

    def test_actual_visibility_is_returned_not_assumed(self):
        api = Mock()
        item = {"title": "Title", "description": "Description"}
        api.get.return_value = {"items": [{"id": "abcdefghijk", "snippet": dict(item, channelId="channel"),
                                          "status": {"privacyStatus": "private", "selfDeclaredMadeForKids": False,
                                                     "uploadStatus": "uploaded"}}]}
        result = pub.verified_video(api, "abcdefghijk", item, "channel")
        self.assertEqual(result["privacyStatus"], "private")

    def test_package_hash_and_changed_video_invalidate_approval(self):
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary) / "work"
            work.mkdir()
            config = Config(Path(temporary) / "archive", work)
            video = work / "video.mp4"; video.write_bytes(b"synthetic")
            caption = work / "caption.md"; caption.write_text("synthetic")
            thumb = work / "thumbnail.jpg"; thumb.write_bytes(b"synthetic")
            package = {"museum_id": "353", "channel_id": "channel", "thumbnail": str(thumb),
                       "thumbnail_sha256": pub.sha(thumb), "items": [{"material": "album", "video": str(video),
                       "sha256": pub.sha(video), "caption_source": str(caption), "caption_sha256": pub.sha(caption),
                       "title": "Title", "description": "Description", "privacyStatus": "public"}]}
            path = work / "package.json"; pub.atomic_json(path, package)
            approval = {"package_sha256": pub.sha(path), "decision": "publish_all", "privacyStatus": "public",
                        "selfDeclaredMadeForKids": False, "rights_confirmed": True, "channel_id": "channel",
                        "material_count": 1}
            approval_path = work / "approval.json"; pub.atomic_json(approval_path, approval)
            pub.validate_package(config, path, approval_path)
            video.write_bytes(b"changed")
            with self.assertRaises(SafeError):
                pub.validate_package(config, path, approval_path)
            video.write_bytes(b"synthetic")
            package["items"][0]["title"] = "Changed title"
            pub.atomic_json(path, package)
            with self.assertRaises(SafeError):
                pub.validate_package(config, path, approval_path)


if __name__ == "__main__":
    unittest.main()
