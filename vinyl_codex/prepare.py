"""Локальный черновик A01 пластинки 246. Публикационных действий нет."""
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
from .config import Config
from .captions import captions
from .legacy246 import read_approved_246
from .safety import SafeError, inside, local_file, no_links, output_path


def checksum(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(config, path, data):
    path = output_path(path, config.archive, config.work)
    temp = output_path(path.with_name(path.name + ".pending"), config.archive, config.work)
    with temp.open("x", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    json.loads(temp.read_text(encoding="utf-8"))
    temp.replace(path)


def run(tool, args, timeout=900):
    result = subprocess.run([str(tool), "-nostdin", "-n", *args],
                            capture_output=True, encoding="utf-8", errors="replace", timeout=timeout)
    if result.returncode:
        raise SafeError("FFmpeg завершился с ошибкой; черновик не считается готовым.")
    return result


def probe(tool, path):
    result = subprocess.run([str(tool), "-v", "error", "-show_format", "-show_streams",
                             "-of", "json", str(path)], capture_output=True,
                            encoding="utf-8", errors="strict", timeout=60, check=True)
    return json.loads(result.stdout)


def draft_plan(config, record_path, selection, resume=False):
    if selection != "D01_A01":
        raise SafeError("Рендерер первого черновика ограничен выбранным D01_A01.")
    record = inside(no_links(record_path), config.archive)
    if not record.is_dir() or not record.name.startswith("246 - "):
        raise SafeError("Каталог не соответствует Museum ID 246.")
    metadata = read_approved_246(record, "246")
    selected = [item for item in metadata["works"] if
                (item["disc"], item["side"], item["track"]) == ("D01", "A", "01")]
    if len(selected) != 1:
        raise SafeError("Нет выбранного произведения.")
    if (selected[0]["work"], selected[0]["composer"], selected[0]["conductor"], selected[0]["ensemble"]) != (
            "Hidjaz", "Alexandre Spendiarian", "Varoujan Kevorkian", "Orquesta de Camara"):
        raise SafeError("Музейные сведения изменились; публикационные тексты требуют пересмотра.")
    # Роли этих изображений проверены вручную в чате, а не угаданы по порядку.
    images = {"front": "image00013.jpg", "back": "image00014.jpg", "side_a": "image00017.jpg"}
    sources = {role: local_file(record / "IMAGES" / name, record) for role, name in images.items()}
    sources["audio"] = local_file(record / "TRACKS" / selected[0]["file_name"], record)
    sources["metadata"] = local_file(record / "METADATA" / "metadata.json", record)
    target = output_path(config.work / "246" / selection / "draft-v2", config.archive, config.work)
    if target.exists():
        if not resume:
            raise SafeError("Черновик v2 уже существует; готовые версии не перезаписываются.")
        previous = json.loads(local_file(target / "state.json", config.work).read_text(encoding="utf-8"))
        if (previous.get("status") != "interrupted_needs_review" or previous.get("selection") != selection
                or previous.get("render_recipe") != "photos-only-v2"):
            raise SafeError("Продолжать можно только прерванный черновик выбранного произведения.")
        for role, source in sources.items():
            if checksum(source) != previous.get("source_checksums", {}).get(role, {}).get("sha256"):
                raise SafeError("Исходники изменились; автоматическое продолжение запрещено.")
    return record, selected[0], sources, target


def prepare_a01(config, record_path, ffmpeg, resume=False):
    record, selected, sources, target = draft_plan(config, record_path, "D01_A01", resume)
    tool = Path(ffmpeg)
    prober = tool.with_name("ffprobe.exe")
    if not tool.is_absolute() or not tool.is_file() or not prober.is_file():
        raise SafeError("Не найдены установленные FFmpeg/ffprobe.")
    if shutil.disk_usage(config.work).free < 2 * 1024**3:
        raise SafeError("Для черновика требуется не менее 2 GiB свободного места.")
    before = {role: {"path": str(path), "sha256": checksum(path),
                      "bytes": path.stat().st_size, "mtime_ns": path.stat().st_mtime_ns}
              for role, path in sources.items()}
    duration = float(probe(prober, sources["audio"])["format"]["duration"])
    if duration <= 180:
        raise SafeError("Предложенные фрагменты выходят за длительность выбранного WAV.")
    target.mkdir(parents=True, exist_ok=resume)
    lock = output_path(config.work / "246" / "prepare.lock", config.archive, config.work)
    with lock.open("x", encoding="utf-8") as handle:
        handle.write(str(os.getpid()))
    state_path = target / "state.json"
    state = {"museum_id": "246", "selection": "D01_A01", "version": "draft-v2",
             "render_recipe": "photos-only-v2",
             "status": "preparing", "completed": [], "source_checksums": before,
             "publication_approval": None, "rights_approval": None, "uploads": 0,
             "logo": "not_used", "source_duration_seconds": duration}
    try:
        atomic_json(config, state_path, state)
        def out(name):
            return output_path(target / name, config.archive, config.work)
        for role in ("front", "back", "side_a", "audio"):
            destination = out({"front": "cover-front-original.jpg", "back": "cover-back-original.jpg",
                               "side_a": "side-a-original.jpg", "audio": "source-audio.wav"}[role])
            if not destination.exists():
                with sources[role].open("rb") as incoming, destination.open("xb") as outgoing:
                    shutil.copyfileobj(incoming, outgoing)
            if checksum(destination) != before[role]["sha256"]:
                raise SafeError("Рабочая копия не совпадает с оригиналом.")
        state["completed"].append("source_copies_verified")
        atomic_json(config, state_path, state)
        public_text = captions(selected)
        if re.search(r"(?i)museum\s*id|թանգարանային\s*id|(?<!\d)246(?!\d)", public_text):
            raise SafeError("Публикационный текст содержит внутренний Museum ID.")
        out("captions-hy-en.md").write_text(public_text, encoding="utf-8")
        image_filter = "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=0x101014,setsar=1"
        total_frames = math.ceil(duration * 24)
        encoder = ["-c:v", "libx264", "-preset", "veryfast", "-tune", "stillimage",
                   "-crf", "19", "-r", "24", "-fps_mode", "cfr", "-pix_fmt", "yuv420p", "-an"]
        segments = [out("front-video.mp4"), out("side-a-video.mp4")]
        for image_name, frames, path in (
                ("cover-front-original.jpg", total_frames // 2, segments[0]),
                ("side-a-original.jpg", total_frames - total_frames // 2, segments[1])):
            # Масштабируем один раз, затем повторяем готовый кадр.
            cached_loop = image_filter + ",loop=loop=-1:size=1:start=0,settb=expr=1/24,setpts=N"
            run(tool, ["-v", "error", "-i", str(out(image_name)), "-vf", cached_loop,
                       "-frames:v", str(frames), *encoder, str(path)])
        concat = out("video-segments.txt")
        concat.write_text("".join("file '" + path.as_posix() + "'\n" for path in segments),
                          encoding="utf-8")
        youtube = out("youtube-full-draft-v2.mp4")
        run(tool, ["-v", "error", "-f", "concat", "-safe", "0", "-i", str(concat),
                   "-i", str(out("source-audio.wav")),
                   "-map", "0:v:0", "-map", "1:a:0", "-t", str(duration),
                   "-map_metadata", "-1", "-map_chapters", "-1",
                   "-c:v", "copy", "-c:a", "aac", "-b:a", "320k",
                   "-movflags", "+faststart", str(youtube)])
        state["completed"].append("youtube_full")
        atomic_json(config, state_path, state)
        vertical = ("scale=1080:1920:force_original_aspect_ratio=decrease,"
                    "pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=0x101014,setsar=1,"
                    "loop=loop=-1:size=1:start=0,settb=expr=1/24,setpts=N")
        proposals = [("reel-option-1.mp4", 45, 30), ("reel-option-2.mp4", 150, 30),
                     ("story-option-1.mp4", 45, 15)]
        for name, start, length in proposals:
            run(tool, ["-v", "error", "-i", str(out("cover-front-original.jpg")),
                       "-ss", str(start), "-i", str(out("source-audio.wav")), "-t", str(length),
                       "-map", "0:v:0", "-map", "1:a:0", "-vf", vertical,
                       "-map_metadata", "-1", "-map_chapters", "-1",
                       "-c:v", "libx264", "-preset", "veryfast", "-tune", "stillimage",
                       "-crf", "20", "-r", "24", "-fps_mode", "cfr", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "256k",
                       "-movflags", "+faststart", str(out(name))])
            state["completed"].append(name)
            atomic_json(config, state_path, state)
        # Обложка и карусель — неизменённые оригинальные JPG без наложений и рамок.
        state["carousel_order"] = ["cover-front-original.jpg", "cover-back-original.jpg", "side-a-original.jpg"]
        for number, name in enumerate(state["carousel_order"], 1):
            run(tool, ["-v", "error", "-i", str(out(name)), "-vf", "scale=1080:-1",
                       "-frames:v", "1", "-q:v", "2", "-update", "1",
                       "-map_metadata", "-1", str(out(f"carousel-{number:02d}.jpg"))])
        state["thumbnail"] = "cover-front-original.jpg"
        state["instagram_fragments"] = [{"file": name, "source_start_seconds": start,
                                         "length_seconds": length, "approval": None}
                                        for name, start, length in proposals]
        quality = []
        for name, expected in [("youtube-full-draft-v2.mp4", duration),
                               *[(name, length) for name, start, length in proposals]]:
            path = out(name)
            info = probe(prober, path)
            actual = float(info["format"]["duration"])
            streams = info["streams"]
            if abs(actual - expected) > 0.1 or not any(s["codec_type"] == "audio" for s in streams):
                raise SafeError("Длительность или аудиодорожка результата не прошли проверку.")
            run(tool, ["-v", "error", "-xerror", "-i", str(path), "-f", "null", "-"])
            quality.append({"file": name, "duration_seconds": actual, "full_decode_ok": True,
                            "sha256": checksum(path),
                            "streams": [{"codec": s.get("codec_name"), "type": s["codec_type"],
                                         "width": s.get("width"), "height": s.get("height")}
                                        for s in streams]})
        # Измерение не преобразует исходник и не применяется к рендеру.
        levels = run(tool, ["-v", "info", "-i", str(out("source-audio.wav")),
                            "-af", "volumedetect", "-f", "null", "-"]).stderr
        state["audio_levels_db"] = {key: float(value) for key, value in re.findall(
            r"(mean_volume|max_volume):\s*(-?[0-9.]+) dB", levels)}
        for role, path in sources.items():
            if checksum(path) != before[role]["sha256"] or path.stat().st_mtime_ns != before[role]["mtime_ns"]:
                raise SafeError("Музейный исходник изменился во время подготовки.")
        state.update(status="ready_for_review", completed=state["completed"] + ["export_validation"],
                     outputs=quality, source_unchanged=True,
                     audio_processing="no_normalization_no_restoration_no_fades",
                     youtube_audio_start_seconds=0, intro_seconds=0, outro_seconds=0,
                     created_at=datetime.now(timezone.utc).isoformat())
        atomic_json(config, state_path, state)
        journal = output_path(config.work / "246" / "journal.json", config.archive, config.work)
        history = json.loads(journal.read_text(encoding="utf-8"))
        history["events"].append({"id": "246-D01_A01-draft-v2", "stage": "preparation",
                                 "status": "ready_for_review", "selection": "D01_A01",
                                 "state": str(state_path.relative_to(config.work / "246")),
                                 "created_at": state["created_at"], "outputs": quality,
                                 "uploads": 0, "published": False, "publication_approval": None,
                                 "rights_approval": None})
        atomic_json(config, journal, history)
        return {"status": state["status"], "directory": str(target), "outputs": quality, "uploads": 0}
    except Exception:
        state["status"] = "interrupted_needs_review"
        atomic_json(config, state_path, state)
        raise
    finally:
        output_path(lock, config.archive, config.work).unlink()
