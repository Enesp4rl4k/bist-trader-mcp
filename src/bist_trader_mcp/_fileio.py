"""Crash- and concurrency-safe small-file writes (journal, configs).

The trade journal is written by the MCP server *and* by the daily pipeline CLI
(Task Scheduler / cron), possibly at the same moment. Plain ``write_text``
can leave a half-written file on a crash, and two read-modify-write cycles
can silently drop each other's rows. Two primitives fix that:

- :func:`atomic_write_text` — write to a temp file in the same directory,
  fsync, then ``os.replace`` (atomic on POSIX and Windows).
- :func:`locked` — exclusive inter-process lock on a sidecar ``.lock`` file
  (``fcntl.flock`` on POSIX, ``msvcrt.locking`` on Windows), plus an
  in-process lock for threads. Wrap every read-modify-write in it.

No third-party dependency.
"""

from __future__ import annotations

import os
import tempfile
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

_thread_locks: dict[str, threading.RLock] = {}
_registry_lock = threading.Lock()


def _thread_lock(path: Path) -> threading.RLock:
    key = str(path.resolve())
    with _registry_lock:
        lock = _thread_locks.get(key)
        if lock is None:
            lock = _thread_locks[key] = threading.RLock()
        return lock


@contextmanager
def locked(path: str | Path, timeout: float = 15.0) -> Iterator[None]:
    """Hold an exclusive lock for ``path`` (across threads and processes)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tlock = _thread_lock(path)
    if not tlock.acquire(timeout=timeout):
        raise TimeoutError(f"could not lock {path} within {timeout}s")
    try:
        with open(path.with_name(path.name + ".lock"), "a+b") as fh:
            _acquire_os_lock(fh, path, timeout)
            try:
                yield
            finally:
                _release_os_lock(fh)
    finally:
        tlock.release()


def _acquire_os_lock(fh, path: Path, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while True:
        try:
            if os.name == "nt":
                import msvcrt

                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except OSError:
            if time.monotonic() >= deadline:
                raise TimeoutError(f"could not lock {path} within {timeout}s") from None
            time.sleep(0.02)


def _release_os_lock(fh) -> None:
    try:
        if os.name == "nt":
            import msvcrt

            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass


def atomic_write_text(path: str | Path, text: str, encoding: str = "utf-8") -> None:
    """Replace ``path`` with ``text`` so readers see the old or the new file, never half."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


__all__ = ["atomic_write_text", "locked"]
