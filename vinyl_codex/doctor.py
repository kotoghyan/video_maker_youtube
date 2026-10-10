import platform
import shutil
import subprocess
import sys
import tempfile
import os
from .safety import no_links, output_path


def doctor(config, check_write=False):
    tools = {"python": {"path": sys.executable, "version": platform.python_version()}}
    for name in ("ffmpeg", "ffprobe", "git"):
        executable = shutil.which(name)
        version = None
        if executable:
            result = subprocess.run([executable, "-version" if name != "git" else "--version"],
                                    capture_output=True, text=True, timeout=15)
            version = (result.stdout or result.stderr).splitlines()[0]
        tools[name] = {"path": executable, "version": version}
    paths = {}
    for name, path in (("archive", config.archive), ("work", config.work)):
        no_links(path)
        available = path.is_dir()
        paths[name] = {"path": str(path), "exists": available,
                       "writable": "not_tested", "readable": "not_tested"}
        if available:
            with os.scandir(path):
                # Проверяется открытие каталога без перечисления пластинок.
                pass
            paths[name]["readable"] = True
            paths[name]["free_bytes"] = shutil.disk_usage(path).free
    if check_write:
        target = output_path(config.work, config.archive, config.work)
        with tempfile.TemporaryFile(dir=target) as handle:
            handle.write(b"write probe")
            handle.flush()
        paths["work"]["writable"] = True
    return {"mode": "doctor", "os": platform.platform(), "tools": tools,
            "paths": paths, "archive_write_probe": False,
            "onedrive_sync_state": "not_verified", "uploads": 0}
