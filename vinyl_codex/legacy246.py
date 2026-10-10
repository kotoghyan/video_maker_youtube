"""Адаптер варианта Museum ID 246, разрешённого владельцем в чате.

Музейный JSON не преобразуется и не записывается. Результат — рабочий отчёт.
"""
import json
import re
from .metadata import unique_keys
from .safety import SafeError, local_file, museum_id

ROOT_FIELDS = {
    "Museum ID", "Release Title", "Label", "Catalog Number", "Release Year",
    "Source Language", "Number of Discs", "Speed", "Diameter", "Format",
    "Digitization Status", "Duplicate Status", "Notes", "Music"
}
MUSIC_FIELDS = {
    "Composer", "Work", "Movement", "Performer", "Instrument", "Conductor",
    "Orchestra / Ensemble", "Choir", "Disc", "Side", "Track"
}


def read_approved_246(record, selected_id):
    if museum_id(selected_id) != "246":
        raise SafeError("Архивный адаптер разрешён только для Museum ID 246.")
    path = local_file(record / "METADATA" / "metadata.json", record)
    if path.stat().st_size > 8 * 1024 * 1024:
        raise SafeError("JSON превышает безопасный лимит чтения.")
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=unique_keys)
    except (UnicodeError, json.JSONDecodeError):
        raise SafeError("Неверный синтаксис или кодировка музейного JSON.") from None
    if not isinstance(data, dict) or set(data) != ROOT_FIELDS:
        raise SafeError("Набор полей отличается от утверждённого варианта 246.")
    if data["Museum ID"] != "246":
        raise SafeError("Museum ID в JSON не совпадает с выбранным.")
    if any(not isinstance(data[k], str) for k in ROOT_FIELDS - {"Music", "Number of Discs"}):
        raise SafeError("Неверный тип поля релиза.")
    count = data["Number of Discs"]
    if type(count) is not int or not 1 <= count <= 99:
        raise SafeError("Некорректное число дисков.")
    if not isinstance(data["Music"], list) or not data["Music"]:
        raise SafeError("Список Music пуст или имеет неверный тип.")
    seen, sequence, mapped = set(), {}, []
    directory = record / "TRACKS"
    local_tracks = []
    for candidate in directory.iterdir():
        local_tracks.append(local_file(candidate, record))
    for item in data["Music"]:
        if not isinstance(item, dict) or set(item) != MUSIC_FIELDS:
            raise SafeError("Набор полей произведения отличается от утверждённого.")
        if any(not isinstance(value, str) for value in item.values()):
            raise SafeError("Некорректный тип поля произведения.")
        disc, side, track = item["Disc"], item["Side"], item["Track"]
        if not re.fullmatch(r"D[0-9]{2}", disc) or not 1 <= int(disc[1:]) <= count:
            raise SafeError("Некорректный номер диска.")
        if side not in ("A", "B") or not re.fullmatch(r"[0-9]{2}", track) or track == "00":
            raise SafeError("Некорректная сторона или номер трека.")
        key = (disc, side, track)
        if key in seen:
            raise SafeError("Дублирующееся произведение.")
        seen.add(key)
        expected = sequence.get(key[:2], 0) + 1
        if int(track) != expected:
            raise SafeError("Нарушена последовательность треков стороны.")
        sequence[key[:2]] = expected
        prefix = f"246_{disc}_{side}{track} - "
        candidates = [p for p in local_tracks if p.name.startswith(prefix) and p.suffix.lower() == ".wav"]
        if len(candidates) != 1:
            raise SafeError("Нет однозначного WAV для произведения.")
        target = candidates[0]
        expected_title = f"{item['Composer']} - {item['Work']}"
        if target.stem[len(prefix):] != expected_title:
            raise SafeError("Название WAV не совпадает с композитором и произведением JSON.")
        if target.stat().st_size == 0:
            raise SafeError("WAV пуст.")
        mapped.append({"disc": disc, "side": side, "track": track,
                       "work": item["Work"], "movement": item["Movement"],
                       "composer": item["Composer"], "conductor": item["Conductor"],
                       "ensemble": item["Orchestra / Ensemble"],
                       "file_name": target.name, "mapping": "exact_id_and_title",
                       "grouping": "one_music_entry_preserved"})
    if len(mapped) != len(local_tracks):
        raise SafeError("TRACKS содержит файлы вне утверждённого списка Music.")
    return {"metadata_profile": "owner_approved_246", "museum_id": "246",
            "release_title": data["Release Title"], "works": mapped}
