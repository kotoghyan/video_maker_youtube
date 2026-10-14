"""Current-user Windows DPAPI storage, exclusively outside synced folders."""
import ctypes
from ctypes import wintypes
from contextlib import contextmanager
import json
import os
from pathlib import Path
import tempfile

from .safety import SafeError, absolute, no_links


def credential_directory(config):
    value = os.environ.get("LOCALAPPDATA")
    if os.name != "nt" or not value:
        raise SafeError("Хранилище требует Windows и LOCALAPPDATA.")
    directory = absolute(Path(value) / "Vinyl_Codex" / "credentials")
    excluded = [config.archive, config.work, Path(__file__).resolve().parents[1]]
    excluded.extend(Path(os.environ[key]).resolve() for key in
                    ("OneDrive", "OneDriveConsumer", "OneDriveCommercial") if os.environ.get(key))
    if any(directory.is_relative_to(root) for root in excluded) or any(
            part.lower().startswith("onedrive") for part in directory.parts):
        raise SafeError("Секреты запрещены в OneDrive, проекте и музейных каталогах.")
    return directory


class Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def dpapi(data, decrypt=False):
    if os.name != "nt":
        raise SafeError("DPAPI доступен только в Windows.")
    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    result = Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    function = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                         ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    function.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result)):
        raise SafeError("DPAPI: шифрование или расшифровка не выполнены.")
    try:
        return ctypes.string_at(result.pbData, result.cbData)
    finally:
        kernel.LocalFree(result.pbData)


class SecretStore:
    def __init__(self, directory, filename="youtube-token.dpapi"):
        if not filename.endswith(".dpapi") or Path(filename).name != filename or "/" in filename or "\\" in filename:
            raise SafeError("Некорректное имя защищённого хранилища.")
        self.directory = no_links(directory)
        self.path = self.directory / filename

    @contextmanager
    def lock(self):
        import msvcrt
        no_links(self.directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        path = no_links(self.directory / "youtube.lock")
        with path.open("a+b") as handle:
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                raise SafeError("Другой процесс уже работает с подключением YouTube.") from None
            try:
                if os.fstat(handle.fileno()).st_size == 0:
                    handle.write(b"0")
                    handle.flush()
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)

    def load(self):
        no_links(self.path)
        if not self.path.exists():
            return None
        try:
            data = json.loads(dpapi(self.path.read_bytes(), decrypt=True))
            if not isinstance(data, dict):
                raise ValueError
            return data
        except (ValueError, UnicodeError):
            raise SafeError("Повреждённое хранилище YouTube; требуется повторное подключение.") from None

    def save(self, data):
        # Encrypt before opening any output: plaintext never reaches the filesystem.
        encrypted = dpapi(json.dumps(data, ensure_ascii=False).encode("utf-8"))
        no_links(self.directory)
        no_links(self.path)
        self.directory.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix="youtube-", suffix=".dpapi", dir=self.directory)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(encrypted)
                handle.flush()
                os.fsync(handle.fileno())
            no_links(self.path)
            os.replace(temporary, self.path)
        finally:
            if Path(temporary).exists():
                Path(temporary).unlink()
