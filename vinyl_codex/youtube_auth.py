"""Desktop OAuth and read-only channel identification. No media upload methods."""
import base64
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import secrets
import threading
import time
from urllib import error, parse, request
import webbrowser

from .safety import SafeError, no_links
from .secret_store import SecretStore, credential_directory, dpapi

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
CHANNEL_URL = "https://www.googleapis.com/youtube/v3/channels"
SCOPES = ("https://www.googleapis.com/auth/youtube.readonly",
          "https://www.googleapis.com/auth/youtube.upload")


def load_client(directory):
    files = list(no_links(directory).glob("*.json"))
    if len(files) != 1:
        raise SafeError("Нужен ровно один Desktop OAuth JSON в локальном каталоге credentials.")
    try:
        data = json.loads(no_links(files[0]).read_text(encoding="utf-8-sig"))
        client = data["installed"]
        if not isinstance(client, dict) or any(not isinstance(client.get(key), str) or not client[key]
                for key in ("client_id", "client_secret", "auth_uri", "token_uri")):
            raise ValueError
        if client["auth_uri"] not in (AUTH_URL, "https://accounts.google.com/o/oauth2/auth") or client["token_uri"] != TOKEN_URL:
            raise ValueError
        return {key: client[key] for key in ("client_id", "client_secret")}
    except (KeyError, TypeError, ValueError, UnicodeError):
        raise SafeError("Некорректный Desktop OAuth JSON или неофициальные адреса Google.") from None


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def google_json(url, fields=None, token=None):
    if url != TOKEN_URL and not url.startswith(CHANNEL_URL + "?"):
        raise SafeError("Разрешены только OAuth и чтение подключённого канала.")
    headers = {"Accept": "application/json"}
    data = None
    if fields is not None:
        if url != TOKEN_URL:
            raise SafeError("Отправка данных разрешена только OAuth endpoint.")
        data = parse.urlencode(fields).encode("ascii")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    if token:
        headers["Authorization"] = "Bearer " + token
    try:
        opener = request.build_opener(NoRedirect())
        with opener.open(request.Request(url, data=data, headers=headers), timeout=30) as response:
            payload = response.read(1024 * 1024 + 1)
            if len(payload) > 1024 * 1024:
                raise ValueError
            result = json.loads(payload)
            if not isinstance(result, dict):
                raise ValueError
            return result
    except error.HTTPError as exc:
        raise SafeError(f"Google API вернул HTTP {exc.code}; подключение не подтверждено.") from None
    except (error.URLError, TimeoutError, OSError, ValueError, UnicodeError):
        raise SafeError("Не получен корректный ответ Google API; проверьте соединение.") from None


def pkce():
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
    return verifier, challenge


def callback_result(path, state):
    url = parse.urlsplit(path)
    query = parse.parse_qs(url.query)
    states = query.get("state", [])
    if url.path != "/" or len(states) != 1 or not secrets.compare_digest(states[0], state):
        return None
    if "error" in query:
        return {"denied": True}
    codes = query.get("code", [])
    return {"code": codes[0]} if len(codes) == 1 and codes[0] else None


def authorize(client, timeout=600):
    state = secrets.token_urlsafe(32)
    verifier, challenge = pkce()
    completed = threading.Event()
    received = {}

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            self.request.settimeout(5)
            super().setup()

        def log_message(self, *args):
            pass  # Callback URL contains an authorization code: never log it.

        def do_GET(self):
            result = callback_result(self.path, state)
            valid = result is not None and not completed.is_set()
            if valid:
                received.update(result)
                completed.set()
            self.send_response(200 if valid else 400)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            try:
                self.wfile.write(("Ответ Google получен. Вернитесь в Codex для проверки канала."
                                  if valid else "Недействительный ответ авторизации.").encode("utf-8"))
            except OSError:
                pass

    class Server(ThreadingHTTPServer):
        daemon_threads = True
        def handle_error(self, *args):
            pass  # Prevent tracebacks from including callback details.

    with Server(("127.0.0.1", 0), Handler) as server:
        redirect = f"http://127.0.0.1:{server.server_port}/"
        parameters = dict(client_id=client["client_id"], redirect_uri=redirect, response_type="code",
                          scope=" ".join(SCOPES), state=state, code_challenge=challenge,
                          code_challenge_method="S256", access_type="offline", prompt="select_account consent")
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            if not webbrowser.open(AUTH_URL + "?" + parse.urlencode(parameters), new=1):
                raise SafeError("Не удалось открыть системный браузер; повторите запуск после его настройки.")
            print(json.dumps({"status": "waiting_for_google_consent", "timeout_seconds": timeout,
                              "uploads": 0}, ensure_ascii=False), flush=True)
            if not completed.wait(timeout):
                raise SafeError("Время входа Google истекло. Повторите youtube-connect.")
        finally:
            server.shutdown()
            worker.join(timeout=5)
    if received.get("denied"):
        raise SafeError("Доступ отклонён в Google; токены не сохранены.")
    fields = dict(client, code=received["code"], code_verifier=verifier,
                  redirect_uri=redirect, grant_type="authorization_code")
    return google_json(TOKEN_URL, fields=fields)


def token_document(response, client, previous=None):
    previous = previous or {}
    access = response.get("access_token")
    refresh = response.get("refresh_token", previous.get("refresh_token"))
    scopes = response.get("scope", " ".join(previous.get("scopes", [])))
    seconds = response.get("expires_in")
    if not isinstance(access, str) or not access or not isinstance(refresh, str) or not refresh or \
            response.get("token_type", "").lower() != "bearer" or not isinstance(seconds, (int, float)) or \
            not 0 < seconds <= 86400 or not isinstance(scopes, str):
        raise SafeError("Google не выдал корректные access/refresh токены.")
    granted = scopes.split()
    if not set(SCOPES).issubset(granted):
        raise SafeError("Не предоставлены необходимые разрешения YouTube: чтение канала и загрузка.")
    return dict(client_id=client["client_id"], access_token=access, refresh_token=refresh,
                scopes=granted, expires_at=time.time() + seconds)


def channel_report(document):
    query = parse.urlencode(dict(part="snippet", mine="true", maxResults=50))
    result = google_json(CHANNEL_URL + "?" + query, token=document["access_token"])
    items = result.get("items")
    if items == [] or (items is None and result.get("kind") == "youtube#channelListResponse"
                       and result.get("pageInfo", {}).get("totalResults") == 0):
        raise SafeError("OAuth выполнен, но Google API вернул 0 каналов для выданной OAuth-идентичности. "
                        "Нужно проверить привязку Brand Account и роль владельца; "
                        "открытый канал в браузере не подтверждает идентичность API.")
    if not isinstance(items, list) or len(items) != 1 or result.get("nextPageToken"):
        raise SafeError("Google API не вернул однозначный канал: проверьте структуру ответа и список каналов.")
    try:
        channel_id, title = items[0]["id"], items[0]["snippet"]["title"]
        if not isinstance(channel_id, str) or not channel_id or not isinstance(title, str) or not title:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise SafeError("Google не вернул название и идентификатор канала.") from None
    return dict(status="connected", channel_id=channel_id, channel_title=title,
                channel_confirmation_required=True, storage="Windows DPAPI, current user, outside OneDrive",
                scopes=list(SCOPES), uploads=0)


def youtube_check(config):
    directory = credential_directory(config)
    load_client(directory)
    probe = b"Vinyl Codex synthetic DPAPI check"
    if dpapi(dpapi(probe), decrypt=True) != probe:
        raise SafeError("Проверка DPAPI не пройдена.")
    return dict(status="ready_for_oauth", desktop_client_valid=True, dpapi_roundtrip=True,
                token_present=no_links(directory / "youtube-token.dpapi").exists(), uploads=0)


def youtube_connect(config, timeout=600, reconnect=False):
    directory = credential_directory(config)
    store = SecretStore(directory)
    with store.lock():
        if store.load() is not None and not reconnect:
            raise SafeError("Токен уже сохранён. Используйте youtube-status или youtube-connect --reconnect.")
        client = load_client(directory)
        document = token_document(authorize(client, timeout), client)
        # Persist even if channel API is temporarily unavailable: no repeated consent needed.
        store.save(document)
        return channel_report(document)


def youtube_status(config):
    directory = credential_directory(config)
    store = SecretStore(directory)
    with store.lock():
        document = store.load()
        if document is None:
            return dict(status="not_connected", uploads=0)
        client = load_client(directory)
        if document.get("client_id") != client["client_id"]:
            raise SafeError("OAuth-клиент изменён; требуется youtube-connect --reconnect.")
        if not isinstance(document.get("expires_at"), (float, int)) or \
                not set(SCOPES).issubset(document.get("scopes", [])) or \
                not isinstance(document.get("access_token"), str) or \
                not isinstance(document.get("refresh_token"), str):
            raise SafeError("Сохранённые данные подключения некорректны.")
        if document["expires_at"] <= time.time() + 60:
            fields = dict(client, refresh_token=document["refresh_token"], grant_type="refresh_token")
            document = token_document(google_json(TOKEN_URL, fields=fields), client, document)
            store.save(document)
        return channel_report(document)
