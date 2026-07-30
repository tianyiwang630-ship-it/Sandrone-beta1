from __future__ import annotations

import os
import re
from pathlib import Path
from agent.core.sandbox_types import AccessAction, SandboxDecision, SandboxZone


PROTECTED_PROJECT_PATHS: tuple[Path, ...] = ()
READ_ONLY_PROJECT_PATHS = (Path("agent"), Path("session-log"))


def resolve_bash_command_context(
    *,
    project_root: Path,
    workspace_root: Path,
    command: str,
    working_dir: str | Path | None,
) -> tuple[str, Path]:
    """Return the command body and cwd that BashTool will actually execute."""
    command_body, cd_working_dir = _split_simple_cd_prefix(command)
    if cd_working_dir is not None:
        if working_dir not in (None, ""):
            raise ValueError("command 中已包含 cd 前缀，请不要同时传 working_dir；请只使用 working_dir 指定目录。")
        working_dir = cd_working_dir
    cwd = resolve_working_directory(
        project_root=project_root,
        workspace_root=workspace_root,
        working_dir=working_dir,
    )
    return command_body, cwd


def resolve_working_directory(
    *,
    project_root: Path,
    workspace_root: Path,
    working_dir: str | Path | None,
) -> Path:
    """Resolve bash cwd using workspace-relative semantics."""
    project_root = Path(project_root).resolve()
    workspace_root = Path(workspace_root).resolve()
    if working_dir in (None, ""):
        return workspace_root

    path = _path_from_user_input(working_dir).expanduser()
    if not path.is_absolute():
        path = workspace_root / path

    resolved = path.resolve()
    if not (_is_relative_to(resolved, project_root) or _is_relative_to(resolved, workspace_root)):
        raise ValueError("working_dir 必须位于 AGENT_ALPHA_ROOT 或当前 workspace 内部。")
    if not resolved.is_dir():
        raise ValueError("working_dir 必须是已存在的目录。")
    return resolved


def resolve_workspace_input_path(path: str | Path, *, workspace_root: Path) -> Path:
    user_path = _path_from_user_input(path)
    if not user_path.is_absolute():
        user_path = Path(workspace_root).resolve() / user_path
    return user_path.resolve()


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
    if action in {"write", "delete"} and _matches_project_paths(
        path, project_root, READ_ONLY_PROJECT_PATHS
    ):
        return "deny", "project"

    zone = classify_path(path, workspace_root=workspace_root, project_root=project_root)

    if zone == "unknown" or action == "unknown":
        return "deny", zone

    if zone == "workspace":
        return "allow", zone

    if zone == "project":
        if action == "read":
            return "allow", zone
        if action in {"write", "delete"}:
            if _matches_project_paths(path, project_root, READ_ONLY_PROJECT_PATHS):
                return "deny", zone
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


def _path_from_user_input(path: str | Path) -> Path:
    text = str(path)
    if (
        os.name == "nt"
        and len(text) > 3
        and text[0] == "/"
        and text[1].isalpha()
        and text[2] in {"/", ":"}
    ):
        suffix = text[3:] if text[2] == ":" else text[2:]
        if suffix.startswith("/"):
            return Path(f"{text[1].upper()}:{suffix}")
    return Path(text)


def _split_simple_cd_prefix(command: str) -> tuple[str, str | None]:
    stripped = command.strip()
    directory_match = re.match(r"^(?:cd|pushd)\s+", stripped, flags=re.IGNORECASE)
    if directory_match is None:
        return command, None

    parts = stripped.split("&&")
    if len(parts) != 2:
        raise ValueError("检测到复杂 cd 用法，请把目录放到 working_dir 参数里。")

    cd_part, rest = parts[0].strip(), parts[1].strip()
    if not rest:
        raise ValueError("cd 后缺少要执行的命令，请把目录放到 working_dir 参数里。")

    cd_tokens = cd_part.split(maxsplit=1)
    if len(cd_tokens) != 2:
        raise ValueError("cd 后缺少目录，请把目录放到 working_dir 参数里。")

    target = cd_tokens[1].strip()
    if cd_tokens[0].lower() == "cd" and target.lower().startswith("/d "):
        target = target[3:].strip()
    if any(token in target for token in ("$", "`", "|", ";", "&")):
        raise ValueError("检测到复杂 cd 目录表达式，请把目录放到 working_dir 参数里。")

    if (target.startswith('"') and target.endswith('"')) or (
        target.startswith("'") and target.endswith("'")
    ):
        target = target[1:-1]
    if not target:
        raise ValueError("cd 后缺少目录，请把目录放到 working_dir 参数里。")
    return rest, target


def _is_protected_project_path(path: Path | None, project_root: Path) -> bool:
    return _matches_project_paths(path, project_root, PROTECTED_PROJECT_PATHS)


def _matches_project_paths(path: Path | None, project_root: Path, protected_paths: tuple[Path, ...]) -> bool:
    if path is None:
        return False
    try:
        relative = path.resolve().relative_to(Path(project_root).resolve())
    except ValueError:
        return False
    return any(relative == protected or _is_relative_to(relative, protected) for protected in protected_paths)
