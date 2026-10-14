import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib import parse, request

from vinyl_codex.config import Config
from vinyl_codex.safety import SafeError
from vinyl_codex.secret_store import SecretStore, credential_directory, dpapi
from vinyl_codex import youtube_auth as auth


CLIENT = {"client_id": "synthetic-client", "client_secret": "synthetic-secret"}


def response(**overrides):
    result = dict(access_token="synthetic-access", refresh_token="synthetic-refresh",
                  token_type="Bearer", scope=" ".join(auth.SCOPES), expires_in=3600)
    result.update(overrides)
    return result


class AuthTests(unittest.TestCase):
    def test_pkce(self):
        verifier, challenge = auth.pkce()
        self.assertTrue(43 <= len(verifier) <= 128)
        self.assertEqual(len(challenge), 43)
        self.assertNotEqual(auth.pkce()[0], verifier)

    def test_callback_rejects_forgery_and_duplicates(self):
        for path in ("/?code=secret", "/?state=wrong&code=secret", "/else?state=ok&code=secret",
                     "/?state=ok&state=ok&code=secret", "/?state=ok&code=a&code=b"):
            self.assertIsNone(auth.callback_result(path, "ok"))

    def test_callback_denied(self):
        self.assertEqual(auth.callback_result("/?state=ok&error=access_denied", "ok"), {"denied": True})

    def test_callback_code(self):
        self.assertEqual(auth.callback_result("/?state=ok&code=synthetic", "ok"), {"code": "synthetic"})

    def test_token_partial_consent_rejected(self):
        with self.assertRaises(SafeError):
            auth.token_document(response(scope=auth.SCOPES[0]), CLIENT)

    def test_refresh_preserves_refresh_token_and_scopes(self):
        previous = auth.token_document(response(), CLIENT)
        renewed = dict(access_token="new-synthetic", expires_in=1800, token_type="Bearer")
        result = auth.token_document(renewed, CLIENT, previous)
        self.assertEqual(result["refresh_token"], previous["refresh_token"])
        self.assertEqual(result["scopes"], list(auth.SCOPES))

    def test_invalid_token_rejected(self):
        for override in ({"refresh_token": ""}, {"access_token": None}, {"expires_in": -1},
                         {"token_type": "other"}, {"scope": None}):
            with self.assertRaises(SafeError):
                auth.token_document(response(**override), CLIENT)

    def test_no_media_endpoint_permitted(self):
        for url in ("https://www.googleapis.com/upload/youtube/v3/videos", "https://example.com/token"):
            with self.assertRaises(SafeError):
                auth.google_json(url, fields={"secret": "synthetic"})

    def test_channel_identified_readonly(self):
        with patch.object(auth, "google_json", return_value={"items": [
                {"id": "synthetic-channel", "snippet": {"title": "Test channel"}}]}) as api:
            result = auth.channel_report(auth.token_document(response(), CLIENT))
        self.assertEqual(result["uploads"], 0)
        self.assertTrue(result["channel_confirmation_required"])
        args, kwargs = api.call_args
        self.assertTrue(args[0].startswith(auth.CHANNEL_URL + "?"))
        self.assertNotIn("fields", kwargs)
        self.assertNotIn("access_token", result)

    def test_zero_or_multiple_channels_rejected(self):
        for items in ([], [{}, {}]):
            with patch.object(auth, "google_json", return_value={"items": items}):
                with self.assertRaises(SafeError):
                    auth.channel_report({"access_token": "synthetic"})

    def test_real_loopback_with_synthetic_consent(self):
        def browser(url, **kwargs):
            query = parse.parse_qs(parse.urlsplit(url).query)
            self.assertEqual(query["code_challenge_method"], ["S256"])
            self.assertEqual(query["scope"], [" ".join(auth.SCOPES)])
            self.assertEqual(query["prompt"], ["select_account consent"])
            redirect = query["redirect_uri"][0]
            self.assertTrue(redirect.startswith("http://127.0.0.1:"))
            callback = redirect + "?" + parse.urlencode(dict(state=query["state"][0], code="synthetic-code"))
            with request.urlopen(callback, timeout=5) as result:
                self.assertEqual(result.status, 200)
                self.assertNotIn(b"synthetic-code", result.read())
            return True
        with patch.object(auth.webbrowser, "open", side_effect=browser), \
                patch.object(auth, "google_json", return_value=response()) as api:
            result = auth.authorize(CLIENT, timeout=5)
        self.assertEqual(result["access_token"], "synthetic-access")
        self.assertEqual(api.call_args.args[0], auth.TOKEN_URL)
        self.assertEqual(api.call_args.kwargs["fields"]["grant_type"], "authorization_code")

    def test_client_validation(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            client = dict(CLIENT, auth_uri=auth.AUTH_URL, token_uri=auth.TOKEN_URL)
            file = folder / "client.json"
            file.write_text(json.dumps({"installed": client}))
            self.assertEqual(auth.load_client(folder), CLIENT)
            client["token_uri"] = "https://example.com/token"
            file.write_text(json.dumps({"installed": client}))
            with self.assertRaises(SafeError):
                auth.load_client(folder)
            (folder / "second.json").write_text("{}")
            with self.assertRaises(SafeError):
                auth.load_client(folder)

    def test_real_empty_response_without_items_explained(self):
        empty = {"kind": "youtube#channelListResponse", "pageInfo": {"totalResults": 0, "resultsPerPage": 50}}
        with patch.object(auth, "google_json", return_value=empty):
            with self.assertRaisesRegex(SafeError, "0 каналов"):
                auth.channel_report({"access_token": "synthetic"})

    @unittest.skipUnless(os.name == "nt", "Windows DPAPI")
    def test_dpapi_and_atomic_encrypted_store(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = SecretStore(Path(temporary))
            doc = auth.token_document(response(), CLIENT)
            with store.lock():
                store.save(doc)
                self.assertEqual(store.load(), doc)
            raw = store.path.read_bytes()
            self.assertNotIn(b"synthetic-access", raw)
            self.assertNotIn(b"synthetic-refresh", raw)
            self.assertEqual(len(list(Path(temporary).glob("*.dpapi"))), 1)
            self.assertEqual(json.loads(dpapi(raw, decrypt=True)), doc)
            store.path.write_bytes(b"invalid-synthetic")
            with self.assertRaises(SafeError):
                store.load()

    @unittest.skipUnless(os.name == "nt", "Windows storage")
    def test_onedrive_path_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = Config(root / "archive", root / "work")
            with patch.dict(os.environ, {"LOCALAPPDATA": str(root / "OneDrive" / "Local")}):
                with self.assertRaises(SafeError):
                    credential_directory(config)

    @unittest.skipUnless(os.name == "nt", "Windows lock")
    def test_concurrent_store_lock_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = SecretStore(Path(temporary))
            with store.lock():
                with self.assertRaises(SafeError):
                    with store.lock():
                        self.fail("Second lock acquired")

    @unittest.skipUnless(os.name == "nt", "Windows storage")
    def test_status_refresh_saved_encrypted(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            config = Config(directory / "archive", directory / "work")
            previous = auth.token_document(response(), CLIENT)
            previous["expires_at"] = 0
            store = SecretStore(directory)
            store.save(previous)
            replies = [dict(access_token="new-access", token_type="Bearer", expires_in=3600),
                       {"items": [{"id": "channel", "snippet": {"title": "Channel"}}]}]
            with patch.object(auth, "credential_directory", return_value=directory), \
                    patch.object(auth, "load_client", return_value=CLIENT), \
                    patch.object(auth, "google_json", side_effect=replies) as api:
                result = auth.youtube_status(config)
            self.assertEqual(result["status"], "connected")
            self.assertEqual(api.call_count, 2)
            self.assertEqual(store.load()["access_token"], "new-access")
            self.assertNotIn(b"new-access", store.path.read_bytes())


if __name__ == "__main__":
    unittest.main()
