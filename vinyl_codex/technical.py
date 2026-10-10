"""Техническая инвентаризация без интерпретации музейного JSON."""
import json
from pathlib import Path
import subprocess
from .inventory import inventory
from .safety import SafeError, inside, local_file, museum_id, no_links


def inspect_media(config, selected_id, record_path, ffprobe):
    selected_id = museum_id(selected_id)
    record = inside(no_links(record_path), config.archive)
    if not record.is_dir() or not record.name.startswith(selected_id + " - "):
        raise SafeError("Указанный каталог не соответствует Museum ID.")
    tool = Path(ffprobe)
    if not tool.is_absolute() or not tool.is_file():
        raise SafeError("Требуется абсолютный путь к установленному ffprobe.")
    media = inventory(record)
    for category, entries in media.items():
        for entry in entries["files"]:
            if not entry["extension_candidate"]:
                continue
            path = local_file(record / category / entry["name"], record)
            before = path.stat()
            result = subprocess.run(
                [str(tool), "-v", "error", "-show_format", "-show_streams",
                 "-of", "json", str(path)],
                capture_output=True, timeout=60, encoding="utf-8", errors="replace")
            after = path.stat()
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise SafeError("Исходный файл менялся во время проверки.")
            if result.returncode:
                entry["technical_validity"] = "probe_failed"
                continue
            parsed = json.loads(result.stdout)
            streams = parsed.get("streams", [])
            required = "audio" if category == "TRACKS" else "video"
            entry["technical_validity"] = ("header_checked" if any(
                s.get("codec_type") == required for s in streams) else "missing_required_stream")
            entry["duration_seconds"] = parsed.get("format", {}).get("duration")
            entry["streams"] = [{key: stream[key] for key in (
                "codec_type", "codec_name", "sample_rate", "channels", "bits_per_sample",
                "width", "height") if key in stream} for stream in streams]
    return {"mode": "technical-only", "museum_id": selected_id, "record": str(record),
            "uploads": 0, "published": False, "source_writes": 0, "media": media,
            "metadata_validation": "blocked_standard_mismatch",
            "limits": ["Проверены заголовки, не полное декодирование и не качество.",
                       "Музейные атрибуции и соответствие произведениям не подтверждены."]}
