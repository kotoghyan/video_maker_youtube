"""Структурная проверка примера раздела 15 официального стандарта.

Это не проверка атрибуций по фотографиям и не новая музейная схема.
"""
import json
import re
from .safety import SafeError, local_file

RELEASE_STRINGS = (
    "museum_id release_title normalized_release_name label catalog_number "
    "release_year source_language speed diameter format digitization_status "
    "duplicate_status notes"
).split()
TRACK_FIELDS = (
    "disc side track composer work movement performer instrument conductor "
    "orchestra_ensemble choir file_name"
).split()


def unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise SafeError("Повторяющийся ключ музейного JSON.")
        result[key] = value
    return result


def read_metadata(record, selected_id):
    path = local_file(record / "METADATA" / (selected_id + "_metadata.json"), record)
    if path.stat().st_size > 8 * 1024 * 1024:
        raise SafeError("JSON превышает безопасный лимит чтения 8 MiB.")
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=unique_keys)
    except (UnicodeError, json.JSONDecodeError):
        raise SafeError("Музейный JSON имеет неверную кодировку или синтаксис.") from None
    if not isinstance(data, dict) or set(data) != set(RELEASE_STRINGS) | {"number_of_discs", "tracks"}:
        raise SafeError("Поля JSON отличаются от документированного примера; нужна ручная проверка.")
    if any(not isinstance(data[k], str) for k in RELEASE_STRINGS):
        raise SafeError("Некорректный тип поля релиза.")
    if data["museum_id"] != selected_id:
        raise SafeError("Museum ID в JSON не совпадает с выбранным.")
    count = data["number_of_discs"]
    if type(count) is not int or not 1 <= count <= 99:
        raise SafeError("Некорректное число дисков.")
    if not isinstance(data["tracks"], list) or not data["tracks"]:
        raise SafeError("Список tracks отсутствует или пуст.")
    seen, sides = set(), {}
    for track in data["tracks"]:
        if not isinstance(track, dict) or set(track) != set(TRACK_FIELDS):
            raise SafeError("Поля трека отличаются от документированного примера.")
        if any(not isinstance(track[k], str) for k in TRACK_FIELDS):
            raise SafeError("Тип поля трека требует ручной проверки по стандарту.")
        if not re.fullmatch(r"D[0-9]{2}", track["disc"]) or not 1 <= int(track["disc"][1:]) <= count:
            raise SafeError("Некорректный номер диска.")
        if track["side"] not in ("A", "B") or not re.fullmatch(r"[0-9]{2}", track["track"]) or track["track"] == "00":
            raise SafeError("Некорректная сторона или номер трека.")
        key = (track["disc"], track["side"], track["track"])
        if key in seen:
            raise SafeError("Дублирующийся трек.")
        seen.add(key)
        side = key[:2]
        expected = sides.get(side, 0) + 1
        if int(track["track"]) != expected:
            raise SafeError("Нарушен порядок треков стороны.")
        sides[side] = expected
        prefix = f"{selected_id}_{track['disc']}_{track['side']}{track['track']} - "
        name = track["file_name"]
        if not name.startswith(prefix) or not name.endswith(".wav") or any(c in name for c in '/\\:<>"|?*') or re.search(r"[А-Яа-яЁё]", name):
            raise SafeError("Имя TRACKS не соответствует стандарту.")
        target = local_file(record / "TRACKS" / name, record)
        if target.stat().st_size == 0:
            raise SafeError("Файл трека пуст.")
    return data
