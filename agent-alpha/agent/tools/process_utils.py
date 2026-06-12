from __future__ import annotations

import os
import signal
import subprocess
from typing import Any


def subprocess_group_kwargs() -> dict[str, Any]:
    """Return Popen kwargs that make child cleanup reliable on each platform."""
    if os.name == "nt":
        return {"close_fds": True}
    return {"start_new_session": True}


def terminate_process_tree(proc: subprocess.Popen[Any]) -> None:
    """Best-effort termination for a process and its children."""
    if proc.poll() is not None:
        return

    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return

    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except Exception:
        proc.terminate()
