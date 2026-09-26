"""Cross-process gate for the one Alpha-owned Chrome profile."""

from __future__ import annotations

import os
import time
from pathlib import Path


class BrowserFileLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.handle = None

    def acquire(self, timeout: float) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        deadline = time.monotonic() + max(0, timeout)
        while True:
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.handle = handle
                return True
            except OSError:
                if time.monotonic() >= deadline:
                    handle.close()
                    return False
                time.sleep(min(0.05, deadline - time.monotonic()))

    def release(self) -> None:
        handle, self.handle = self.handle, None
        if handle is None:
            return
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass  # Closing the handle still releases the operating-system lock.
        finally:
            handle.close()
