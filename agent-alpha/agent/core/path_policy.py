from __future__ import annotations

from pathlib import Path
from agent.core.sandbox_types import AccessAction, SandboxDecision, SandboxZone


PROTECTED_PROJECT_PATHS = (
    Path("agent/core"),
    Path("agent/tools"),
)


def classify_path(path: Path | None, *, workspace_root: Path, project_root: Path) -> SandboxZone:
    if path is None:
        return "unknown"

    resolved = path.resolve()
    workspace_root = Path(workspace_root).resolve()
    if _is_relative_to(resolved, workspace_root):
        return "workspace"

    project_root = Path(project_root).resolve()
    if _is_relative_to(resolved, project_root):
        return "project"

    return "outside"


def decide_path_access(
    path: Path | None,
    *,
    action: AccessAction,
    workspace_root: Path,
    project_root: Path,
) -> tuple[SandboxDecision, SandboxZone]:
    zone = classify_path(path, workspace_root=workspace_root, project_root=project_root)

    if zone == "unknown" or action == "unknown":
        return "deny", zone

    if zone == "workspace":
        return "allow", zone

    if zone == "project":
        if action == "read":
            return "allow", zone
        if action in {"write", "delete"}:
            return ("ask" if _is_protected_project_path(path, project_root) else "allow"), zone

    if zone == "outside" and action == "read":
        return "allow", zone

    return "deny", zone


def _is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
        return True
    except ValueError:
        return False


def _is_protected_project_path(path: Path | None, project_root: Path) -> bool:
    if path is None:
        return False
    try:
        relative = path.resolve().relative_to(Path(project_root).resolve())
    except ValueError:
        return False
    return any(relative == protected or _is_relative_to(relative, protected) for protected in PROTECTED_PROJECT_PATHS)
