"""Approved sequential resumable uploads. Session URIs encrypted with DPAPI."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import time
from urllib import error, parse, request

from .safety import SafeError, inside, local_file, output_path
from .secret_store import SecretStore, credential_directory
from .youtube_auth import load_client, token_document, google_json, TOKEN_URL, SCOPES, NoRedirect

API = "https://www.googleapis.com/youtube/v3/"
UPLOAD = "https://www.googleapis.com/upload/youtube/v3/"
CHUNK = 8 * 1024 * 1024


def now():
    return datetime.now(timezone.utc).isoformat()


def sha(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while block := stream.read(1024 * 1024):
            value.update(block)
    return value.hexdigest()


def atomic_json(path, value):
    temporary = path.with_suffix(".pending")
    # Caller validates both destinations against WORK_ROOT.
    from .safety import no_links
    no_links(path)
    no_links(temporary)
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush()
        import os
        os.fsync(stream.fileno())
    temporary.replace(path)


class ApiFailure(SafeError):
    def __init__(self, status, reason="unknown"):
        self.status = status
        self.reason = reason
        super().__init__(f"YouTube API: HTTP {status}, причина {reason}.")


def safe_reason(payload):
    try:
        value = json.loads(payload)["error"]["errors"][0]["reason"]
        if re.fullmatch(r"[A-Za-z]{1,80}", value):
            return value
    except (ValueError, KeyError, IndexError, TypeError):
        pass
    return "unknown"


def validate_url(url, method):
    parsed = parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc != "www.googleapis.com" or parsed.fragment:
        raise SafeError("Неофициальный адрес YouTube запрещён.")
    paths = {"GET": {"/youtube/v3/channels", "/youtube/v3/playlistItems", "/youtube/v3/videos"},
             "POST": {"/upload/youtube/v3/videos", "/upload/youtube/v3/thumbnails/set"},
             "PUT": {"/upload/youtube/v3/videos"}}
    if parsed.path not in paths.get(method, set()):
        raise SafeError("Метод или endpoint запрещён; изменения/удаления опубликованного не поддерживаются.")


class Transport:
    def __init__(self, config):
        directory = credential_directory(config)
        self.store = SecretStore(directory)
        self.client = load_client(directory)

    def access_token(self):
        doc = self.store.load()
        if not doc or doc.get("client_id") != self.client["client_id"] or not set(SCOPES).issubset(doc.get("scopes", [])):
            raise SafeError("Нет действующего подключения YouTube для текущего OAuth-клиента.")
        if doc["expires_at"] <= time.time() + 120:
            doc = token_document(google_json(TOKEN_URL, fields=dict(
                self.client, refresh_token=doc["refresh_token"], grant_type="refresh_token")), self.client, doc)
            self.store.save(doc)
        return doc["access_token"]

    def send(self, method, url, data=None, headers=None):
        validate_url(url, method)
        merged = dict(headers or {})
        merged["Authorization"] = "Bearer " + self.access_token()
        merged["Accept"] = "application/json"
        try:
            with request.build_opener(NoRedirect()).open(
                    request.Request(url, data=data, headers=merged, method=method), timeout=45) as response:
                return response.status, dict(response.headers), response.read(2 * 1024 * 1024)
        except error.HTTPError as exc:
            payload = exc.read(2 * 1024 * 1024)
            if exc.code == 308 and method == "PUT":
                return 308, dict(exc.headers), payload
            raise ApiFailure(exc.code, safe_reason(payload)) from None
        except (error.URLError, TimeoutError, OSError):
            raise ApiFailure(0, "connectionInterrupted") from None

    def get(self, resource, fields):
        _, _, body = self.send("GET", API + resource + "?" + parse.urlencode(fields))
        try:
            result = json.loads(body)
            if not isinstance(result, dict):
                raise ValueError
            return result
        except (ValueError, UnicodeError):
            raise SafeError("YouTube вернул некорректный JSON.") from None


def validate_package(config, package_path, approval_path):
    package_path = local_file(package_path, config.work)
    approval_path = local_file(approval_path, config.work)
    package = json.loads(package_path.read_text(encoding="utf-8"))
    approval = json.loads(approval_path.read_text(encoding="utf-8"))
    if approval.get("package_sha256") != sha(package_path) or approval.get("decision") != "publish_all" or \
            approval.get("privacyStatus") != "public" or approval.get("selfDeclaredMadeForKids") is not False or \
            approval.get("rights_confirmed") is not True or approval.get("channel_id") != package.get("channel_id"):
        raise SafeError("Утверждение не соответствует точному пакету, каналу, правам или аудитории.")
    items = package.get("items")
    if not isinstance(items, list) or len(items) != approval.get("material_count"):
        raise SafeError("Число утверждённых материалов не совпадает.")
    materials = set()
    for item in items:
        if item["material"] in materials:
            raise SafeError("Повтор материала в пакете.")
        materials.add(item["material"])
        for pathkey, hashkey in (("video", "sha256"), ("caption_source", "caption_sha256")):
            path = local_file(Path(item[pathkey]), config.work)
            if path.is_relative_to(config.archive) or sha(path) != item[hashkey]:
                raise SafeError("Утверждённый файл изменился; публикация остановлена.")
        if item.get("privacyStatus") != "public" or not 0 < len(item["title"]) <= 100 or len(item["description"]) > 5000:
            raise SafeError("Некорректные параметры утверждённого материала.")
        if re.search(r"(?<!\d)" + re.escape(package["museum_id"]) + r"(?!\d)", item["title"] + item["description"]):
            raise SafeError("Museum ID найден в публичном тексте.")
    thumbnail = local_file(Path(package["thumbnail"]), config.work)
    if sha(thumbnail) != package["thumbnail_sha256"] or thumbnail.stat().st_size > 2 * 1024 * 1024:
        raise SafeError("Обложка изменена или превышает локальный лимит.")
    return package, approval


def verify_channel(api, expected):
    channels = api.get("channels", {"part": "snippet,contentDetails", "mine": "true"}).get("items", [])
    if len(channels) != 1 or channels[0].get("id") != expected:
        raise SafeError("Подключённый канал не совпадает с утверждённым.")
    return channels[0]


def duplicates(api, channel, package, uploaded_ids):
    playlist = channel["contentDetails"]["relatedPlaylists"]["uploads"]
    page = ""
    seen = set()
    count = 0
    matches = []
    names = [item["title"].split(" — ", 1)[-1].split(" | ", 1)[0].casefold()
             for item in package["items"] if " — " in item["title"]]
    artist = ("rouben mateossian", "ruben matevosyan", "ռուբեն մատևոսյան", "ռուբեն մատեւոսյան")
    for _ in range(500):
        fields = {"part": "snippet", "playlistId": playlist, "maxResults": 50}
        if page:
            fields["pageToken"] = page
        result = api.get("playlistItems", fields)
        for video in result.get("items", []):
            snippet = video["snippet"]
            count += 1
            vid = snippet["resourceId"]["videoId"]
            title = snippet["title"]
            if vid not in uploaded_ids and any(name in title.casefold() for name in (*names, *artist)):
                matches.append({"id": vid, "title": title})
        page = result.get("nextPageToken", "")
        if not page:
            return {"scanned": count, "potential_duplicates": matches, "complete": True, "at": now()}
        if page in seen:
            break
        seen.add(page)
    raise SafeError("Проверка дублей не завершена; загрузка запрещена.")


def progress(event, **fields):
    print(json.dumps(dict(event=event, **fields), ensure_ascii=False), flush=True)


def acknowledged(headers, total):
    value = next((v for k, v in headers.items() if k.lower() == "range"), None)
    if value is None:
        return 0
    match = re.fullmatch(r"bytes=0-(\d+)", value)
    if not match or int(match[1]) >= total:
        raise SafeError("Некорректный Range в ответе resumable upload.")
    return int(match[1]) + 1


def final_video(body):
    try:
        result = json.loads(body)
        if not re.fullmatch(r"[A-Za-z0-9_-]{11}", result.get("id", "")):
            raise ValueError
        return result
    except (ValueError, TypeError):
        raise SafeError("Загрузка могла завершиться, но video ID не подтверждён; новую загрузку не создавать.") from None


def resumable(api, item, session, persist):
    video = Path(item["video"])
    total = video.stat().st_size
    if not session.get("url"):
        if session.get("phase") == "initiating":
            raise SafeError("Неопределённый результат создания upload session; требуется ручная диагностика.")
        metadata = {"snippet": {"title": item["title"], "description": item["description"],
                                "categoryId": item["categoryId"]},
                    "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False}}
        session.update(phase="initiating")
        persist()
        try:
            status, headers, _ = api.send("POST", UPLOAD + "videos?" + parse.urlencode(
                {"uploadType": "resumable", "part": "snippet,status,contentDetails"}),
                json.dumps(metadata, ensure_ascii=False).encode("utf-8"),
                {"Content-Type": "application/json; charset=utf-8", "X-Upload-Content-Type": "video/mp4",
                 "X-Upload-Content-Length": str(total)})
        except ApiFailure as exc:
            if 400 <= exc.status < 500:
                session.update(phase="blocked_before_media", error_reason=exc.reason, at=now())
                persist()
            raise
        url = next((v for k, v in headers.items() if k.lower() == "location"), None)
        if not url:
            raise SafeError("Google не выдал URI сессии; повторная загрузка автоматически запрещена.")
        validate_url(url, "PUT")
        session.update(url=url, phase="uploading")
        persist()
    status, headers, body = api.send("PUT", session["url"], b"", {"Content-Range": f"bytes */{total}"})
    if status in (200, 201):
        return final_video(body)
    if status != 308:
        raise SafeError("Неопределённое состояние загрузки.")
    offset = acknowledged(headers, total)
    failures = 0
    with video.open("rb") as stream:
        while offset < total:
            stream.seek(offset)
            data = stream.read(min(CHUNK, total - offset))
            if not data:
                raise SafeError("Видео изменилось во время чтения.")
            try:
                status, headers, body = api.send("PUT", session["url"], data,
                    {"Content-Type": "video/mp4", "Content-Range": f"bytes {offset}-{offset+len(data)-1}/{total}"})
            except ApiFailure as exc:
                if exc.status not in (0, 500, 502, 503, 504) or failures >= 3:
                    raise
                failures += 1
                time.sleep(2 ** failures)
                status, headers, body = api.send("PUT", session["url"], b"", {"Content-Range": f"bytes */{total}"})
            if status in (200, 201):
                return final_video(body)
            if status != 308:
                raise SafeError("Загрузка не подтверждена; повторную сессию не создавать.")
            advanced = acknowledged(headers, total)
            if advanced <= offset:
                failures += 1
                if failures > 3:
                    raise SafeError("Нет прогресса загрузки; сессия сохранена для диагностики.")
            else:
                failures = 0
            offset = advanced
            session["bytes_acknowledged"] = offset
            persist()
            progress("upload_progress", material=item["material"], percent=round(100 * offset / total, 1))
    raise SafeError("Файл отправлен, но завершение загрузки не подтверждено.")


def verified_video(api, video_id, item, channel_id):
    result = api.get("videos", {"part": "snippet,status,processingDetails,contentDetails", "id": video_id})
    videos = result.get("items", [])
    if len(videos) != 1:
        raise SafeError("Загруженное видео пока не найдено; повторную загрузку не создавать.")
    video = videos[0]
    snippet, status = video["snippet"], video["status"]
    if snippet.get("channelId") != channel_id or snippet.get("title") != item["title"] or \
            snippet.get("description", "").replace("\r\n", "\n") != item["description"].replace("\r\n", "\n"):
        raise SafeError("Канал или метаданные опубликованного видео не совпадают с утверждением.")
    return {"video_id": video_id, "url": "https://www.youtube.com/watch?v=" + video_id,
            "privacyStatus": status.get("privacyStatus"), "selfDeclaredMadeForKids": status.get("selfDeclaredMadeForKids"),
            "madeForKids": status.get("madeForKids"),
            "uploadStatus": status.get("uploadStatus"), "failureReason": status.get("failureReason"),
            "rejectionReason": status.get("rejectionReason"),
            "processingStatus": video.get("processingDetails", {}).get("processingStatus"),
            "duration": video.get("contentDetails", {}).get("duration"), "verified_at": now()}


def publish(config, package_path, approval_path, dry_run=True):
    package_path = Path(package_path)
    package, approval = validate_package(config, package_path, Path(approval_path))
    root = package_path.parent
    report_path = output_path(root / "youtube-publication-results-v1.json", config.archive, config.work)
    journal_path = output_path(config.work / package["museum_id"] / "journal.json", config.archive, config.work)
    tokenstore = SecretStore(credential_directory(config))
    secrets_store = SecretStore(tokenstore.directory, "youtube-upload-" + package["museum_id"] + ".dpapi")
    with tokenstore.lock():
        api = Transport(config)
        channel = verify_channel(api, package["channel_id"])
        state = secrets_store.load() or {"package_sha256": sha(package_path), "sessions": {}}
        if state.get("package_sha256") != sha(package_path):
            raise SafeError("Защищённое состояние принадлежит другой версии пакета.")
        results = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {
            "package_sha256": sha(package_path), "channel_id": package["channel_id"], "items": {}}
        if results.get("package_sha256") != sha(package_path):
            raise SafeError("Журнал результатов принадлежит другой версии пакета.")
        uploaded_ids = {session["video_id"] for session in state["sessions"].values() if session.get("video_id")}
        check = duplicates(api, channel, package, uploaded_ids)
        if check["potential_duplicates"]:
            raise SafeError("На канале найдены возможные дубли; новые загрузки остановлены.")
        if dry_run:
            return {"status": "ready_to_upload", "material_count": len(package["items"]),
                    "channel_title": channel["snippet"]["title"], "duplicates": check,
                    "privacyStatus": "public", "selfDeclaredMadeForKids": False, "uploads": 0}
        def persist():
            secrets_store.save(state)
        def record(item, outcome):
            results["items"][item["material"]] = dict(outcome, title=item["title"], video_sha256=item["sha256"])
            results["updated_at"] = now()
            atomic_json(report_path, results)
            journal = json.loads(journal_path.read_text(encoding="utf-8"))
            journal["events"].append(dict(stage="youtube_upload_result", material=item["material"],
                                          package_version=package["package_version"], at=now(), **outcome))
            atomic_json(journal_path, journal)
        progress("preflight_passed", material_count=len(package["items"]), channel=channel["snippet"]["title"],
                 privacyStatus="public", selfDeclaredMadeForKids=False, duplicates=check)
        for index, item in enumerate(package["items"], 1):
            session = state["sessions"].setdefault(item["material"], {})
            if session.get("video_id"):
                record(item, verified_video(api, session["video_id"], item, package["channel_id"]))
                progress("already_uploaded_skipped", material=item["material"], video_id=session["video_id"])
                continue
            progress("upload_start", index=index, total=len(package["items"]), material=item["material"], title=item["title"])
            # Rehash immediately before sending; full package checked before first upload.
            if sha(Path(item["video"])) != item["sha256"]:
                raise SafeError("Видео изменилось после проверки.")
            try:
                video = resumable(api, item, session, persist)
                session.update(video_id=video["id"], phase="uploaded")
                persist()  # Record ID before any later API request: never reinsert this video.
                record(item, {"video_id": video["id"], "url": "https://www.youtube.com/watch?v=" + video["id"],
                              "uploadStatus": "received", "verification": "pending", "uploaded_at": now()})
                thumb_warning = None
                try:
                    thumb = Path(package["thumbnail"])
                    if sha(thumb) != package["thumbnail_sha256"]:
                        raise SafeError("Обложка изменилась.")
                    api.send("POST", UPLOAD + "thumbnails/set?" + parse.urlencode(
                        {"videoId": video["id"], "uploadType": "media"}), thumb.read_bytes(), {"Content-Type": "image/jpeg"})
                    session["thumbnail_uploaded"] = True
                    persist()
                except SafeError as exc:
                    thumb_warning = str(exc)
                outcome = verified_video(api, video["id"], item, package["channel_id"])
                outcome.update(thumbnail_uploaded=session.get("thumbnail_uploaded", False), thumbnail_warning=thumb_warning)
                record(item, outcome)
                progress("upload_verified", index=index, material=item["material"], **outcome)
                if outcome["privacyStatus"] != "public" or outcome["selfDeclaredMadeForKids"] is not False or \
                        outcome["uploadStatus"] in ("failed", "rejected", "deleted"):
                    raise SafeError("Фактические параметры YouTube не соответствуют утверждению; остальные загрузки остановлены.")
            except SafeError as exc:
                results["last_error"] = {"material": item["material"], "message": str(exc), "at": now()}
                atomic_json(report_path, results)
                raise
        return {"status": "uploaded", "results": str(report_path), "uploads": len(results["items"]),
                "items": list(results["items"].values())}


def duration_seconds(value):
    match = re.fullmatch(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?)?", value or "")
    if not match:
        return None
    days, hours, minutes, seconds = (float(v or 0) for v in match.groups())
    return days * 86400 + hours * 3600 + minutes * 60 + seconds


def verify_publication(config, package_path, approval_path, wait_seconds=600):
    package_path = Path(package_path)
    package, approval = validate_package(config, package_path, Path(approval_path))
    root = package_path.parent
    path = output_path(root / "youtube-publication-results-v1.json", config.archive, config.work)
    results = json.loads(local_file(path, config.work).read_text(encoding="utf-8"))
    if results.get("package_sha256") != sha(package_path) or not results.get("items") or \
            not set(results["items"]).issubset({i["material"] for i in package["items"]}):
        raise SafeError("Нет корректного журнала загруженных видео; новую загрузку не создавать.")
    missing = [i["material"] for i in package["items"] if i["material"] not in results["items"]]
    store = SecretStore(credential_directory(config))
    with store.lock():
        api = Transport(config)
        verify_channel(api, package["channel_id"])
        deadline = time.monotonic() + wait_seconds
        while True:
            processed, problems = 0, []
            for item in package["items"]:
                if item["material"] in missing:
                    continue
                previous = results["items"][item["material"]]
                outcome = verified_video(api, previous["video_id"], item, package["channel_id"])
                previous.update(outcome)
                if outcome["privacyStatus"] != "public" or outcome["selfDeclaredMadeForKids"] is not False or \
                        outcome.get("madeForKids") is True or outcome["uploadStatus"] in ("failed", "rejected", "deleted") or \
                        outcome["processingStatus"] in ("failed", "terminated"):
                    problems.append(dict(material=item["material"], **outcome))
                elif outcome["processingStatus"] == "succeeded" and outcome["uploadStatus"] == "processed":
                    duration = duration_seconds(outcome["duration"])
                    if duration is None or abs(duration - item["duration_seconds"]) > 1:
                        problems.append(dict(material=item["material"], reason="durationMismatch", **outcome))
                    else:
                        processed += 1
            status = "blocked" if problems else ("partially_published" if missing else "published") \
                if processed == len(results["items"]) else "uploaded_processing"
            results.update(status=status, processed_count=processed, problems=problems,
                           remaining_materials=missing, updated_at=now())
            atomic_json(path, results)
            progress("processing_check", processed=processed, uploaded=len(results["items"]),
                     total=len(package["items"]), status=status, problems=problems)
            if status != "uploaded_processing" or time.monotonic() >= deadline:
                break
            time.sleep(min(15, max(0, deadline - time.monotonic())))
        journal_path = output_path(config.work / package["museum_id"] / "journal.json", config.archive, config.work)
        journal = json.loads(journal_path.read_text(encoding="utf-8"))
        journal["events"].append(dict(stage="youtube_final_verification", status=status, at=now(),
                                      processed_count=processed, uploads=len(results["items"]),
                                      results=str(path), problems=problems))
        atomic_json(journal_path, journal)
        if status == "published":
            state_path = output_path(root / "state.json", config.archive, config.work)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state.update(published=True, uploads=len(results["items"]), status="youtube_published",
                         publication_results=str(path), publication_approval=str(approval_path),
                         rights_approval=package.get("rights_confirmation"))
            atomic_json(state_path, state)
        return {"status": status, "results": str(path), "uploads": len(results["items"]),
                "processed_count": processed, "remaining_materials": missing,
                "problems": problems, "items": list(results["items"].values())}
