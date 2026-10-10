from pathlib import Path
import re
import stat


class SafeError(ValueError):
    """Ожидаемая ошибка без вывода содержимого исходных файлов."""


def museum_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]+", value):
        raise SafeError("Museum ID должен состоять только из цифр.")
    return value


def absolute(value):
    if not isinstance(value, (str, Path)) or not Path(value).is_absolute():
        raise SafeError("Требуется абсолютный путь.")
    no_links(Path(value))
    return Path(value).resolve()


def inside(path, root):
    resolved, base = Path(path).resolve(), Path(root).resolve()
    if not resolved.is_relative_to(base):
        raise SafeError("Путь выходит за разрешённый каталог.")
    return resolved


def no_links(path):
    path = Path(path)
    for part in (path, *path.parents):
        if part.is_symlink() or part.is_junction():
            raise SafeError("Ссылки и junction запрещены.")
    return path


def local_file(path, root):
    no_links(path)
    path = inside(path, root)
    info = path.stat()
    attrs = getattr(info, "st_file_attributes", 0)
    # OFFLINE, RECALL_ON_OPEN, RECALL_ON_DATA_ACCESS: чтение может вызвать скачивание.
    if attrs & (0x1000 | 0x40000 | 0x400000):
        raise SafeError("Файл OneDrive требует локального скачивания владельцем.")
    if not stat.S_ISREG(info.st_mode):
        raise SafeError("Ожидается обычный файл.")
    return path


def output_path(path, archive, work):
    no_links(path)
    resolved = inside(path, work)
    if resolved.is_relative_to(Path(archive).resolve()):
        raise SafeError("Запись в архив запрещена.")
    return resolved
