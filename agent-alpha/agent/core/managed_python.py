"""Identify Python entrypoints managed by this Alpha instance."""

from __future__ import annotations

import os
import re
from pathlib import Path

from agent.core.runtime_layout import runtime_python


PYTHON_NAMES = {"python", "python.exe", "python3", "python3.exe"}


def managed_python_kind(path: Path, root: Path) -> str | None:
    """Return shared, skill, tool, or None. Preserve the venv entrypoint path."""
    root = Path(root).resolve()
    entry = Path(os.path.abspath(path))
    if entry.name.lower() not in PYTHON_NAMES:
        return None
    shared = runtime_python(root)
    if os.path.normcase(str(entry)) == os.path.normcase(str(shared)):
        return "shared"
    for parent, kind in ((root / "tools" / "venvs", "skill"), (root / "tools" / "uv", "tool")):
        try:
            relative = entry.relative_to(parent)
        except ValueError:
            continue
        if len(relative.parts) != 3 or relative.parts[1].lower() not in {"scripts", "bin"}:
            continue
        environment = parent / relative.parts[0]
        if not parent.resolve().is_relative_to(root) or not environment.resolve().is_relative_to(parent):
            return None
        if not (environment / "pyvenv.cfg").is_file() or not entry.is_file():
            return None
        # An environment's Python may legitimately link to the selected base interpreter.
        resolved = environment.resolve()
        if entry.is_symlink() and entry.resolve() != shared.resolve():
            try:
                entry.resolve().relative_to(resolved)
            except ValueError:
                return None
        return kind
    return None


def resolve_python_entry(token: str, root: Path, cwd: Path) -> tuple[Path | None, str | None]:
    name = token.strip('"\'').lower()
    if name in {"python", "python3", "python.exe", "python3.exe"}:
        path = runtime_python(root)
    else:
        value = token.strip('"\'')
        if os.name == "nt" and re.match(r"^/[A-Za-z]/", value):
            value = f"{value[1].upper()}:{value[2:]}"
        path = Path(value)
        if not path.is_absolute():
            path = Path(cwd) / path
        path = Path(os.path.abspath(path))
    return path, managed_python_kind(path, root)
