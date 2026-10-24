"""Save a local, verified project snapshot without contacting any model service."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from contextlib import closing
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
TABLES = ("batches", "videos", "shots", "calls", "jobs")
DIRECTORIES = ("backend", "frontend", "data", "outputs", "samples", "workflows", "scripts")
EXCLUDED = {"node_modules", "__pycache__", ".pytest_cache", "backups"}


def database_state(connection: sqlite3.Connection) -> dict:
    counts = {table: connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] for table in TABLES}
    counts["active_jobs"] = connection.execute("SELECT COUNT(*) FROM jobs WHERE state IN ('queued','running')").fetchone()[0]
    counts["active_videos"] = connection.execute("SELECT COUNT(*) FROM videos WHERE active_job IS NOT NULL AND active_job != ''").fetchone()[0]
    return counts


def protect_config(raw: bytes) -> bytes:
    """Use the current Windows account's DPAPI; never store a plaintext key copy."""
    if os.name != "nt":
        raise RuntimeError("Configuration backup requires Windows DPAPI. The original .env is unchanged.")

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]

    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    crypt.CryptProtectData.argtypes = [ctypes.POINTER(Blob), wintypes.LPCWSTR, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    crypt.CryptProtectData.restype = wintypes.BOOL
    crypt.CryptUnprotectData.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    crypt.CryptUnprotectData.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    buffer = ctypes.create_string_buffer(raw)
    source = Blob(len(raw), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
    encrypted = Blob()
    if not crypt.CryptProtectData(ctypes.byref(source), "AI Video Studio config", None, None, None, 1, ctypes.byref(encrypted)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        result = ctypes.string_at(encrypted.pbData, encrypted.cbData)
        restored = Blob()
        if not crypt.CryptUnprotectData(ctypes.byref(encrypted), None, None, None, None, 1, ctypes.byref(restored)):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            if ctypes.string_at(restored.pbData, restored.cbData) != raw:
                raise RuntimeError("Encrypted configuration verification failed")
        finally:
            kernel.LocalFree(restored.pbData)
        return result
    finally:
        kernel.LocalFree(encrypted.pbData)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    backup_dir = ROOT / "outputs/backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    (ROOT / "work").mkdir(exist_ok=True)
    stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S-%f")
    target = backup_dir / f"project-snapshot-{stamp}.zip"
    partial = target.with_suffix(".zip.partial")
    database = ROOT / "data/studio.db"
    if not database.is_file():
        raise RuntimeError("Local data/studio.db was not found; no snapshot was saved.")
    manifest = {"created_at": datetime.now().astimezone().isoformat(), "project": ROOT.name, "storage": "local only", "files": []}
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as connection:
        before = database_state(connection)
        data_version = connection.execute("PRAGMA data_version").fetchone()[0]
        if before["active_jobs"] or before["active_videos"]:
            raise RuntimeError("Wait until generation tasks finish before saving a snapshot.")
        with tempfile.TemporaryDirectory(prefix="snapshot-", dir=ROOT / "work") as temp:
            temp_path = Path(temp).resolve()
            if not temp_path.is_relative_to((ROOT / "work").resolve()):
                raise RuntimeError("Snapshot temporary path must stay inside the project's work directory")
            snapshot = temp_path / "studio.db"
            with closing(sqlite3.connect(snapshot)) as destination:
                connection.backup(destination)
                if destination.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise RuntimeError("Database integrity check failed")
                manifest["database"] = database_state(destination)
            paths = [p for p in ROOT.iterdir() if p.is_file() and not p.is_symlink() and (not p.name.startswith(".env") or p.name == ".env.example")]
            for directory in DIRECTORIES:
                for current, dirs, names in os.walk(ROOT / directory, followlinks=False):
                    dirs[:] = [name for name in dirs if name not in EXCLUDED and not (Path(current) / name).is_symlink()]
                    for name in names:
                        path = Path(current) / name
                        if path.is_symlink() or name.startswith(".env") or name.endswith((".pyc", ".log", ".db-wal", ".db-shm")):
                            continue
                        if path != database:
                            paths.append(path)
            try:
                with zipfile.ZipFile(partial, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=3, allowZip64=True) as archive:
                    for path in sorted(paths):
                        name = path.relative_to(ROOT).as_posix()
                        initial = path.stat()
                        digest = sha256(path)
                        compression = zipfile.ZIP_STORED if path.suffix.lower() in {".mp4", ".mp3", ".png", ".jpg", ".jpeg", ".zip"} else zipfile.ZIP_DEFLATED
                        archive.write(path, name, compress_type=compression)
                        if (path.stat().st_size, path.stat().st_mtime_ns) != (initial.st_size, initial.st_mtime_ns):
                            raise RuntimeError(f"File changed during backup: {name}")
                        manifest["files"].append({"path": name, "bytes": initial.st_size, "sha256": digest})
                    archive.write(snapshot, "data/studio.db")
                    manifest["files"].append({"path": "data/studio.db", "bytes": snapshot.stat().st_size, "sha256": sha256(snapshot)})
                    env = ROOT / ".env"
                    manifest["configuration"] = {"backup": "not included", "original_env": "preserved in project", "note": "Restore configuration from the original .env or fill .env.example again."}
                    if env.is_file():
                        try:
                            encrypted = protect_config(env.read_bytes())
                        except OSError:
                            manifest["configuration"]["note"] = "Windows account encryption is unavailable in this process. No plaintext credentials were copied. Original .env remains in project."
                        else:
                            archive.writestr("local-config.env.dpapi", encrypted)
                            manifest["configuration"] = {"backup": "Windows DPAPI encrypted", "original_env": "preserved in project", "note": "Restore requires the same Windows account and its DPAPI keys; not a portable credential backup."}
                    archive.writestr("snapshot-manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
                    archive.writestr("RESTORE.txt", "Extract into a new folder. Database is data/studio.db; generated media is in data/media. Dependencies are excluded and can be reinstalled with start-local.ps1. The original project's .env remains unchanged. See snapshot-manifest.json for configuration backup status: local-config.env.dpapi, if present, is encrypted for the current Windows user. If absent, copy the original .env locally or fill .env.example again. No cloud upload was performed.\n")
                if database_state(connection) != before or connection.execute("PRAGMA data_version").fetchone()[0] != data_version:
                    raise RuntimeError("Project data changed during backup; please save again after tasks finish.")
                with zipfile.ZipFile(partial) as archive:
                    damaged = archive.testzip()
                    if damaged:
                        raise RuntimeError(f"Archive verification failed: {damaged}")
                    for entry in manifest["files"]:
                        with archive.open(entry["path"]) as stream:
                            digest = hashlib.file_digest(stream, "sha256").hexdigest()
                        if digest != entry["sha256"]:
                            raise RuntimeError(f"Archive hash mismatch: {entry['path']}")
                partial.rename(target)
            except Exception:
                partial.unlink(missing_ok=True)
                raise
    print(json.dumps({"snapshot": str(target), "files": len(manifest["files"]), "bytes": target.stat().st_size, "database": manifest["database"], "config": manifest["configuration"], "verification": "SQLite integrity + ZIP CRC + SHA256 passed"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
