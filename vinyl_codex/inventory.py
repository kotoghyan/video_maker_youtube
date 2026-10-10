from .catalog import discover
from .metadata import read_metadata
from .safety import SafeError, local_file, no_links, inside
from .legacy246 import read_approved_246

EXTENSIONS = {
    "VIDEO": {".mp4", ".mov", ".mkv", ".avi", ".m4v"},
    "IMAGES": {".jpg", ".jpeg", ".png", ".tif", ".tiff"},
    "TRACKS": {".wav", ".flac", ".mp3", ".aiff", ".aif"},
}


def inventory(record):
    result = {}
    for name, extensions in EXTENSIONS.items():
        directory = record / name
        no_links(directory)
        inside(directory, record)
        if not directory.exists():
            result[name] = {"status": "missing", "files": []}
            continue
        if not directory.is_dir():
            raise SafeError("Вместо медиа-каталога найден файл.")
        files = []
        for path in sorted(directory.iterdir()):
            no_links(path)
            if path.is_dir():
                raise SafeError("Вложенный медиа-каталог требует ручной проверки.")
            path = local_file(path, record)
            size = path.stat().st_size
            files.append({"name": path.name, "bytes": size,
                          "extension_candidate": path.suffix.lower() in extensions and size > 0,
                          "technical_validity": "not_checked"})
        result[name] = {"status": "present" if files else "empty", "files": files}
    return result


def dry_run(config, selected_id, record_path=None, metadata_profile="official"):
    if record_path is None:
        record = discover(config, selected_id)
    else:
        from .safety import museum_id
        selected_id = museum_id(selected_id)
        record = inside(no_links(record_path), config.archive)
        if not record.is_dir() or not record.name.startswith(selected_id + " - "):
            raise SafeError("Каталог не соответствует Museum ID.")
    media = inventory(record)
    if metadata_profile == "approved-246":
        report = read_approved_246(record, selected_id)
        return {**report, "mode": "dry-run", "record": str(record),
                "published": False, "uploads": 0, "source_writes": 0,
                "media": media, "track_count": len(report["works"]),
                "warnings": ["Права, атрибуции и качество звука требуют проверки.",
                             "Группировка записей Music сохранена без деления частей."]}
    if metadata_profile != "official":
        raise SafeError("Неизвестный профиль метаданных.")
    metadata = read_metadata(record, selected_id)
    return {
        "mode": "dry-run", "museum_id": selected_id, "record": str(record),
        "published": False, "uploads": 0, "source_writes": 0,
        "metadata_status": "documented_example_structure_checked",
        "museum_attributions": "requires_owner_review",
        "media": media, "track_count": len(metadata["tracks"]),
        "rendering": "not_implemented", "media_selection": "requires_technical_validation",
        "warnings": ["Пригодность медиа, связь фотографий/VIDEO с произведениями и права не проверены."]
    }
