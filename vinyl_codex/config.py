import json
from dataclasses import dataclass
from pathlib import Path
from .safety import SafeError, absolute, no_links


@dataclass(frozen=True)
class Config:
    archive: Path
    work: Path

    def __post_init__(self):
        archive = absolute(no_links(self.archive))
        work = absolute(no_links(self.work))
        if archive.is_relative_to(work) or work.is_relative_to(archive):
            raise SafeError("Архив и рабочий каталог не должны пересекаться.")
        object.__setattr__(self, "archive", archive)
        object.__setattr__(self, "work", work)


def load_config(path):
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict) or set(data) != {"ARCHIVE_ROOT", "WORK_ROOT"}:
        raise SafeError("Конфигурация допускает только ARCHIVE_ROOT и WORK_ROOT.")
    return Config(absolute(data["ARCHIVE_ROOT"]), absolute(data["WORK_ROOT"]))
