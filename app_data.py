"""Persistent data directory and single-process lock for slashbot."""
from __future__ import annotations

import os
import sys
from typing import Optional

_lock_handle: Optional[object] = None


def resolve_data_dir(project_root: Optional[str] = None) -> str:
    """Pick writable directory for bot_users.json, chat history, etc."""
    explicit = os.environ.get("SLASHBOT_DATA_DIR", "").strip()
    if explicit:
        return explicit

    candidates = [
        os.environ.get("RAILWAY_VOLUME_MOUNT_PATH", "").strip(),
        "/data",
    ]
    for candidate in candidates:
        if not candidate or not os.path.isdir(candidate):
            continue
        try:
            probe = os.path.join(candidate, ".slashbot_write_probe")
            with open(probe, "w", encoding="utf-8") as handle:
                handle.write("ok")
            os.remove(probe)
            return candidate
        except OSError:
            continue

    if project_root:
        return project_root
    return os.path.dirname(os.path.abspath(__file__))


def ensure_data_dir(data_dir: str) -> None:
    os.makedirs(data_dir, exist_ok=True)


def acquire_bot_lock(data_dir: str) -> None:
    """Ensure only one bot process runs (local + accidental double start)."""
    global _lock_handle

    try:
        import fcntl
    except ImportError:
        return

    ensure_data_dir(data_dir)
    lock_path = os.path.join(data_dir, ".bot.lock")
    _lock_handle = open(lock_path, "w", encoding="utf-8")
    try:
        fcntl.flock(_lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("❌ Другой экземпляр slashbot уже запущен (файл блокировки).", flush=True)
        print(f"   Lock: {lock_path}", flush=True)
        print("   Остановите локальный бот или второй деплой на Railway.", flush=True)
        sys.exit(1)

    _lock_handle.write(str(os.getpid()))
    _lock_handle.flush()
