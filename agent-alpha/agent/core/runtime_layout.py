from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


SOURCE_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True, slots=True)
class RuntimeLayout:
    """Resolve immutable application resources and writable runtime data."""

    app_root: Path
    data_root: Path
    python_executable: Path
    browser_python_executable: Path
    node_executable: Path | None

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "RuntimeLayout":
        values = env if env is not None else os.environ
        app_root = Path(values.get("AGENT_ALPHA_APP_ROOT") or SOURCE_ROOT).resolve()
        data_root = Path(values.get("AGENT_ALPHA_ROOT") or app_root).resolve()
        python_executable = Path(
            values.get("AGENT_ALPHA_PYTHON") or _development_python(data_root)
        ).resolve()
        browser_python_executable = Path(
            values.get("AGENT_ALPHA_BROWSER_PYTHON")
            or data_root / "tools" / "uv" / "browser-harness" / "Scripts" / "python.exe"
        ).resolve()
        raw_node = str(values.get("AGENT_ALPHA_NODE_EXECUTABLE") or "").strip()
        return cls(
            app_root=app_root,
            data_root=data_root,
            python_executable=python_executable,
            browser_python_executable=browser_python_executable,
            node_executable=Path(raw_node).resolve() if raw_node else None,
        )

    @property
    def packaged(self) -> bool:
        return self.app_root != self.data_root


def _development_python(root: Path) -> Path:
    scripts = "Scripts/python.exe" if os.name == "nt" else "bin/python"
    return root / ".venv" / scripts


LAYOUT = RuntimeLayout.from_env()
APP_ROOT = LAYOUT.app_root
PROJECT_ROOT = LAYOUT.data_root


def current_layout() -> RuntimeLayout:
    """Return a fresh layout so tests and launched workers can override the environment."""
    return RuntimeLayout.from_env()


def runtime_python(project_root: Path | None = None) -> Path:
    layout = current_layout()
    if project_root is None or Path(project_root).resolve() == layout.data_root:
        return layout.python_executable
    return _development_python(Path(project_root).resolve())
