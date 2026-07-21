from __future__ import annotations

import os
import re
import shlex
from pathlib import Path
from typing import Iterable

from agent.core.sandbox_types import AccessAction, BashCategory


READ_ONLY_SINGLE_COMMANDS = {"pwd"}
READ_ONLY_PATH_COMMANDS = {"ls", "dir", "cat", "type", "rg", "grep", "find"}
READ_ONLY_GIT_SUBCOMMANDS = {"status", "diff", "log", "show", "branch", "rev-parse", "ls-files"}
SCRIPT_RUNNERS = {"python", "python3", "py", "node"}
PACKAGE_INSTALL_PATTERNS = {
    ("pip", "install"),
    ("pip", "uninstall"),
    ("pip3", "install"),
    ("pip3", "uninstall"),
    ("npm", "install"),
    ("npm", "uninstall"),
    ("pnpm", "install"),
    ("pnpm", "add"),
    ("pnpm", "uninstall"),
    ("pnpm", "remove"),
    ("yarn", "install"),
    ("yarn", "add"),
    ("yarn", "uninstall"),
    ("yarn", "remove"),
    ("go", "install"),
    ("uv", "tool"),
    ("uv", "pip"),
}
PROJECT_COMMAND_PATTERNS = {
    ("pytest",),
    ("python", "-m"),
    ("python3", "-m"),
    ("py", "-m"),
    ("npm", "run"),
    ("pnpm", "run"),
    ("yarn", "run"),
}
DANGEROUS_COMMANDS = {
    "sudo",
    "su",
    "runas",
    "format",
    "mkfs",
    "diskpart",
    "shutdown",
    "reboot",
    "takeown",
    "icacls",
    "chmod",
    "chown",
    "setx",
    "reg",
    "netsh",
}
MUTATION_COMMANDS = {"mkdir", "cp", "mv", "rm", "del", "rmdir", "touch", "tee", "sed", "echo", "git"}
CONTROL_OPERATORS = ("&&", "||", ";", "$(", "`")


def classify_bash_command(command: str) -> BashCategory:
    stripped = command.strip()
    if not stripped:
        return "unknown"

    tokens = _split_command(stripped)
    if not tokens:
        return "unknown"

    if _is_dangerous_command(stripped, tokens):
        return "dangerous"

    if _is_package_install(tokens):
        return "package_install"

    if _is_project_command(tokens):
        return "project_command"

    if _is_script_run(tokens):
        return "script_run"

    if _is_read_only_command(tokens):
        return "read_only"

    if _is_path_mutation_command(stripped, tokens):
        return "path_mutation"

    return "unknown"


def extract_script_path(command: str, *, base_dir: Path | None = None) -> Path | None:
    tokens = _split_command(command)
    if not _is_script_run(tokens):
        return None

    raw_path = _strip_quotes(tokens[1])
    if not raw_path:
        return None
    return _resolve_path(raw_path, base_dir=base_dir)


def extract_bash_paths(
    command: str,
    category: BashCategory,
    *,
    base_dir: Path | None = None,
) -> tuple[AccessAction, list[Path]] | None:
    if category == "read_only":
        return _extract_read_only_paths(command, base_dir=base_dir)

    if category == "path_mutation":
        return _extract_mutation_paths(command, base_dir=base_dir)

    return None


def extract_general_write_paths(command: str, *, base_dir: Path | None = None) -> list[Path]:
    """Best-effort path extraction for shell commands that clearly write files."""
    return _dedupe_paths(
        [
            *_extract_redirect_write_paths(command, base_dir=base_dir),
            *_extract_output_flag_paths(command, base_dir=base_dir),
            *_extract_powershell_write_paths(command, base_dir=base_dir),
            *_extract_cmd_write_paths(command, base_dir=base_dir),
        ]
    )


def classify_python_launcher_scope(command: str, *, project_root: Path) -> str:
    """Return allowed_alpha_venv, deny, or none for direct Python launcher usage."""
    tokens = _split_command(command)
    if not tokens:
        return "none"

    lowered = [token.lower() for token in tokens]
    if _has_inline_path_override(command) and any(_is_python_launcher_name(token) for token in tokens):
        return "deny"

    first = lowered[0]
    if first == "conda" and "run" in lowered and any(_is_python_launcher_name(token) for token in tokens):
        return "deny"

    if first == "uv" and len(lowered) >= 2 and lowered[1] == "run" and "--python" in lowered:
        index = lowered.index("--python")
        if index + 1 >= len(tokens):
            return "deny"
        return "allowed_alpha_venv" if _is_venv_python(tokens[index + 1], project_root=project_root) else "deny"

    executable = tokens[0]
    if _is_windows_py_launcher(executable):
        return "deny"

    if not _is_python_launcher_name(executable):
        return "none"

    if _is_path_like_executable(executable):
        return "allowed_alpha_venv" if _is_venv_python(executable, project_root=project_root) else "deny"

    return "allowed_alpha_venv"


def command_uses_python_launcher(command: str) -> bool:
    tokens = _split_command(command)
    if not tokens:
        return False
    lowered = [token.lower() for token in tokens]
    if _has_inline_path_override(command) and any(_is_python_launcher_name(token) for token in tokens):
        return True
    if lowered[0] == "conda" and "run" in lowered and any(_is_python_launcher_name(token) for token in tokens):
        return True
    if len(lowered) >= 2 and lowered[0] == "uv" and lowered[1] == "run" and "--python" in lowered:
        return True
    return _is_python_launcher_name(tokens[0])


def is_external_executable_invocation(
    command: str,
    *,
    project_root: Path,
    workspace_root: Path,
    base_dir: Path | None = None,
) -> bool:
    """Return True when the command directly invokes an executable outside alpha/workspace."""
    tokens = _split_command(command)
    if not tokens:
        return False

    executable = tokens[0]
    if not _is_path_like_executable(executable):
        return False

    executable_path = _resolve_path(executable, base_dir=base_dir)
    if executable_path is None:
        return False

    project_root = Path(project_root).resolve()
    workspace_root = Path(workspace_root).resolve()
    return not _is_relative_to(executable_path, project_root) and not _is_relative_to(executable_path, workspace_root)


def classify_package_install_scope(command: str, *, project_root: Path) -> str:
    """Return allowed_host_global, allowed_alpha_venv, ask, or deny for package installs."""
    tokens = _split_command(command)
    if not tokens:
        return "deny"

    lowered = [token.lower() for token in tokens]
    first = lowered[0]

    if "--user" in lowered or "--system" in lowered:
        return "deny"

    if first == "go" and len(lowered) >= 2 and lowered[1] == "install":
        return "allowed_host_global"

    if first == "npm" and len(lowered) >= 2 and lowered[1] == "install":
        return "allowed_host_global" if "-g" in lowered or "--global" in lowered else "ask"

    if first == "pnpm" and len(lowered) >= 2 and lowered[1] in {"add", "install"}:
        return "allowed_host_global" if "-g" in lowered or "--global" in lowered else "ask"

    if first == "yarn":
        if len(lowered) >= 3 and lowered[1] == "global" and lowered[2] == "add":
            return "allowed_host_global"
        return "ask"

    if first == "uv" and len(lowered) >= 3 and lowered[1:3] == ["tool", "install"]:
        return "allowed_alpha_venv"

    if first == "uv" and len(lowered) >= 3 and lowered[1:3] == ["pip", "install"]:
        return _classify_uv_pip_install(tokens, project_root=project_root)

    if _is_bare_pip_launcher(first) and len(lowered) >= 2 and lowered[1] in {"install", "uninstall"}:
        return "deny"

    if _is_python_pip_install(tokens):
        return "allowed_alpha_venv" if _is_allowed_python_launcher(tokens[0], project_root=project_root) else "deny"

    return "ask"


def classify_alpha_venv_command_scope(command: str, *, project_root: Path) -> str:
    """Return allowed_alpha_venv, deny, or none for alpha venv CLI/module commands."""
    tokens = _split_command(command)
    if not tokens:
        return "none"

    executable = tokens[0]
    lowered = [token.lower() for token in tokens]

    if _is_python_module_command(tokens):
        if _is_allowed_python_launcher(executable, project_root=project_root):
            return "allowed_alpha_venv"
        if _is_path_like_executable(executable):
            return "deny"

    if _is_path_like_executable(executable) and _is_venv_python_or_cli(executable, project_root=project_root):
        return "allowed_alpha_venv"

    if lowered[0] in {"agent-reach", "agent_reach"}:
        return "allowed_alpha_venv"

    return "none"


def explain_alpha_venv_command_guidance(project_root: Path) -> str:
    venv = Path(project_root).resolve() / ".venv"
    windows_python = venv / "Scripts" / "python.exe"
    posix_python = venv / "bin" / "python"
    return (
        "Run Python tools through agent-alpha's virtual environment. "
        f"Use {windows_python} -m <module> ... on Windows or {posix_python} -m <module> ... on Linux/macOS. "
        f"For package installs, use {windows_python} -m pip install ... on Windows, "
        f"{posix_python} -m pip install ... on Linux/macOS, or uv pip install --python <that interpreter> ... . "
        "Do not use bare pip or pip3 because they can resolve to a host Python."
    )


def extract_git_command_context(
    command: str, *, base_dir: Path
) -> tuple[str, Path, bool] | None:
    """Return normalized git subcommand, effective work tree, and unsafe override flag."""
    initial_cwd = Path(base_dir).resolve()
    process_cwd = initial_cwd
    work_tree: Path | None = None
    relative_work_tree = False
    unsafe_override = False
    long_override_pattern = re.compile(
        r"--(?P<kind>work-tree|git-dir)(?:=|\s+)(?P<path>\"[^\"]+\"|'[^']+'|\S+)",
        flags=re.IGNORECASE,
    )
    for match in long_override_pattern.finditer(command):
        if match.group("kind").lower() == "git-dir":
            unsafe_override = True
            continue
        raw_work_tree = _strip_quotes(match.group("path"))
        relative_work_tree = not _path_from_shell_input(raw_work_tree).is_absolute()
        resolved = _resolve_path(raw_work_tree, base_dir=initial_cwd)
        if resolved is None:
            unsafe_override = True
        else:
            work_tree = resolved

    command_without_long_overrides = long_override_pattern.sub("", command)
    tokens = _split_command(command_without_long_overrides)
    if not tokens or tokens[0].lower() != "git":
        return None

    index = 1
    while index < len(tokens):
        token = tokens[index]
        lowered = token.lower()
        if token == "-C":
            if index + 1 >= len(tokens):
                return "git", work_tree or process_cwd, True
            resolved = _resolve_path(_strip_quotes(tokens[index + 1]), base_dir=process_cwd)
            if resolved is None:
                return "git", work_tree or process_cwd, True
            process_cwd = resolved
            index += 2
            continue
        break

    normalized = "git" if index >= len(tokens) else f"git {' '.join(tokens[index:])}"
    if relative_work_tree and process_cwd != initial_cwd:
        unsafe_override = True
    return normalized, work_tree or process_cwd, unsafe_override


def explain_parseable_mutation_forms() -> str:
    return (
        "Use a simple single command with explicit paths. Supported writable forms include: "
        "mkdir path, cp src dst, mv src dst, rm file, del file, rmdir dir, touch file, "
        "echo ... > file, echo ... >> file, echo ... | tee file, echo ... | tee -a file, sed -i ... file, "
        "git checkout -- file, git restore file."
    )


def _extract_read_only_paths(command: str, *, base_dir: Path | None = None) -> tuple[AccessAction, list[Path]] | None:
    tokens = _split_command(command)
    if not tokens:
        return None

    first = tokens[0].lower()

    if first == "pwd":
        return "read", []

    if first == "git":
        return "read", []

    if first in {"ls", "dir"}:
        paths = [
            _resolve_path(_strip_quotes(token), base_dir=base_dir)
            for token in tokens[1:]
            if not token.startswith("-")
        ]
        paths = [path for path in paths if path is not None]
        return "read", paths

    if first in {"cat", "type"}:
        paths = [
            _resolve_path(_strip_quotes(token), base_dir=base_dir)
            for token in tokens[1:]
            if not token.startswith("-")
        ]
        if not paths:
            return None
        return "read", paths

    if first in {"rg", "grep"}:
        path = _extract_last_non_flag_path(tokens[1:], base_dir=base_dir)
        return ("read", [path]) if path else ("read", [])

    if first == "find":
        path = _extract_first_non_flag_path(tokens[1:], base_dir=base_dir)
        return ("read", [path]) if path else ("read", [])

    return None


def _extract_mutation_paths(command: str, *, base_dir: Path | None = None) -> tuple[AccessAction, list[Path]] | None:
    stripped = command.strip()

    tee_match = re.match(
        r"^\s*echo\b.*\|\s*tee(?:\s+(-a))?\s+(?P<path>\"[^\"]+\"|'[^']+'|\S+)\s*$",
        stripped,
        flags=re.IGNORECASE,
    )
    if tee_match:
        path = _resolve_path(_strip_quotes(tee_match.group("path")), base_dir=base_dir)
        return ("write", [path]) if path else None

    redirect_match = re.match(
        r"^\s*echo\b.*?(>>?)\s*(?P<path>\"[^\"]+\"|'[^']+'|\S+)\s*$",
        stripped,
        flags=re.IGNORECASE,
    )
    if redirect_match:
        path = _resolve_path(_strip_quotes(redirect_match.group("path")), base_dir=base_dir)
        return ("write", [path]) if path else None

    tokens = _split_command(stripped)
    if not tokens:
        return None

    command_name = tokens[0].lower()
    args = [token for token in tokens[1:] if token]

    if command_name == "mkdir":
        paths = _non_flag_paths(args, base_dir=base_dir)
        return ("write", paths) if len(paths) == 1 else None

    if command_name in {"cp", "mv"}:
        paths = _non_flag_paths(args, base_dir=base_dir)
        if len(paths) != 2:
            return None
        return ("write", [paths[1]]) if command_name == "cp" else ("write", paths)

    if command_name in {"rm", "del", "rmdir"}:
        paths = _non_flag_paths(args, base_dir=base_dir)
        return ("delete", paths) if len(paths) == 1 else None

    if command_name == "touch":
        paths = _non_flag_paths(args, base_dir=base_dir)
        return ("write", paths) if len(paths) == 1 else None

    if command_name == "sed":
        if "-i" not in [arg.lower() for arg in args]:
            return None
        paths = _non_flag_paths(args, base_dir=base_dir)
        return ("write", [paths[-1]]) if paths else None

    if command_name == "git":
        return _extract_git_mutation(args, base_dir=base_dir)

    return None


def _is_dangerous_command(command: str, tokens: list[str]) -> bool:
    first = tokens[0].lower()
    if first in DANGEROUS_COMMANDS:
        if first == "chmod":
            lowered = command.lower()
            return " 777" in lowered or " a+w" in lowered or " -r 777" in lowered
        return True

    normalized = " ".join(token.lower() for token in tokens)
    padded = f" {normalized} "
    if (
        "rm -rf /" in normalized
        or "rm -fr /" in normalized
        or normalized.startswith("git clean -fd")
        or normalized.startswith("git reset --hard")
    ):
        return True
    if ("| bash" in normalized or "| sh" in normalized or "| iex" in normalized) and any(
        marker in padded for marker in {" curl ", " wget ", " irm ", " iwr "}
    ):
        return True
    return any(
        pattern in padded
        for pattern in {
            " set-executionpolicy ",
            " invoke-expression ",
            " start-process ",
            " reg add ",
            " reg delete ",
            " netsh ",
        }
    )


def _is_package_install(tokens: list[str]) -> bool:
    lowered = tuple(token.lower() for token in tokens[:2])
    if lowered in PACKAGE_INSTALL_PATTERNS:
        return True
    if len(tokens) >= 2 and _is_bare_pip_launcher(tokens[0].lower()) and tokens[1].lower() in {"install", "uninstall"}:
        return True
    return _is_python_pip_install(tokens)


def _is_project_command(tokens: list[str]) -> bool:
    lowered = tuple(token.lower() for token in tokens[:2])
    single = (tokens[0].lower(),) if tokens else tuple()
    if lowered in PROJECT_COMMAND_PATTERNS or single in PROJECT_COMMAND_PATTERNS:
        if len(tokens) >= 3 and tokens[0].lower() in {"python", "python3", "py"} and tokens[1] == "-m" and tokens[2] == "pip":
            return False
        return True
    return False


def _is_script_run(tokens: list[str]) -> bool:
    return len(tokens) >= 2 and tokens[0].lower() in SCRIPT_RUNNERS and not tokens[1].startswith("-")


def _is_read_only_command(tokens: list[str]) -> bool:
    first = tokens[0].lower()
    if first in READ_ONLY_SINGLE_COMMANDS:
        return True
    if first in READ_ONLY_PATH_COMMANDS:
        return True
    return first == "git" and len(tokens) >= 2 and tokens[1].lower() in READ_ONLY_GIT_SUBCOMMANDS


def _is_path_mutation_command(command: str, tokens: list[str]) -> bool:
    first = tokens[0].lower()
    if first not in MUTATION_COMMANDS:
        return False
    if first == "git":
        return _is_git_mutation(tokens[1:])
    if any(operator in command for operator in CONTROL_OPERATORS):
        return first == "echo" and "| tee" in command
    return True


def _split_command(command: str) -> list[str]:
    try:
        tokens = shlex.split(command, posix=False)
    except ValueError:
        return []
    return [_strip_quotes(token) for token in tokens if token and token not in {"2>&1", "1>&2"}]


def _is_python_pip_install(tokens: list[str]) -> bool:
    lowered = [token.lower() for token in tokens]
    return len(tokens) >= 4 and lowered[1:4] == ["-m", "pip", "install"]


def _is_python_module_command(tokens: list[str]) -> bool:
    lowered = [token.lower() for token in tokens]
    if len(tokens) < 3:
        return False
    return lowered[1] == "-m" and lowered[2] != "pip"


def _is_bare_python(token: str) -> bool:
    return token.lower() in {"python", "python3", "py"}


def _is_bare_pip_launcher(token: str) -> bool:
    return bool(re.fullmatch(r"pip(?:\d+(?:\.\d+)?)?", Path(_strip_quotes(token)).name.lower()))


def _is_allowed_python_launcher(token: str, *, project_root: Path) -> bool:
    if _is_windows_py_launcher(token):
        return False
    if _is_path_like_executable(token):
        return _is_venv_python(token, project_root=project_root)
    return _is_python_launcher_name(token)


def _is_python_launcher_name(token: str) -> bool:
    name = Path(_strip_quotes(token)).name.lower()
    return name in {"python", "python.exe", "python3", "python3.exe", "py", "py.exe"}


def _is_windows_py_launcher(token: str) -> bool:
    return Path(_strip_quotes(token)).name.lower() in {"py", "py.exe"}


def _is_venv_python(token: str, *, project_root: Path) -> bool:
    try:
        python_path = _resolve_executable_path(token, project_root=project_root)
        if not _is_python_executable_path(python_path):
            return False
        venv_path = Path(project_root).resolve() / ".venv"
        python_path.relative_to(venv_path)
        return True
    except Exception:
        return False


def _is_venv_python_or_cli(token: str, *, project_root: Path) -> bool:
    try:
        executable_path = _resolve_executable_path(token, project_root=project_root)
        venv_path = Path(project_root).resolve() / ".venv"
        executable_path.relative_to(venv_path)
        return True
    except Exception:
        return False


def _is_path_like_executable(token: str) -> bool:
    lowered = token.lower()
    return "/" in token or "\\" in token or lowered.endswith((".exe", ".cmd", ".bat", ".ps1"))


def _resolve_executable_path(token: str, *, project_root: Path) -> Path:
    path = Path(_strip_quotes(token))
    if not path.is_absolute():
        path = Path(project_root) / path
    return path.resolve()


def _is_python_executable_path(path: Path) -> bool:
    return path.name.lower() in {"python", "python.exe", "python3", "python3.exe"}


def _has_inline_path_override(command: str) -> bool:
    return bool(
        re.search(r"(^|\s)(?:export\s+)?PATH\s*=", command, flags=re.IGNORECASE)
        or re.search(r"\$env:PATH\s*=", command, flags=re.IGNORECASE)
        or re.search(r"(^|\s)set\s+PATH\s*=", command, flags=re.IGNORECASE)
    )


def _classify_uv_pip_install(tokens: list[str], *, project_root: Path) -> str:
    lowered = [token.lower() for token in tokens]
    if "--python" not in lowered:
        return "deny"
    index = lowered.index("--python")
    if index + 1 >= len(tokens):
        return "deny"
    return "allowed_alpha_venv" if _is_venv_python(tokens[index + 1], project_root=project_root) else "deny"


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def _resolve_path(raw_path: str, *, base_dir: Path | None = None) -> Path | None:
    if not raw_path:
        return None
    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", raw_path):
        return None
    if "$" in raw_path or "%" in raw_path or "*" in raw_path or "?" in raw_path:
        return None
    try:
        path = _path_from_shell_input(raw_path)
        if not path.is_absolute() and base_dir is not None:
            path = Path(base_dir) / path
        return path.resolve()
    except Exception:
        return None


def _path_from_shell_input(raw_path: str) -> Path:
    if os.name == "nt" and re.match(r"^/[A-Za-z]/", raw_path):
        return Path(f"{raw_path[1].upper()}:{raw_path[2:]}")
    return Path(raw_path)


def _extract_redirect_write_paths(command: str, *, base_dir: Path | None = None) -> list[Path]:
    paths: list[Path] = []
    for match in re.finditer(r"(?<!\d)>>(?!&)|(?<!\d)>(?!&)", command):
        remainder = command[match.end() :].lstrip()
        if not remainder:
            continue
        token_match = re.match(r"(?P<path>\"[^\"]+\"|'[^']+'|\S+)", remainder)
        if not token_match:
            continue
        raw_path = _strip_quotes(token_match.group("path"))
        if raw_path.startswith("&"):
            continue
        path = _resolve_path(raw_path, base_dir=base_dir)
        if path is not None:
            paths.append(path)
    tee_pattern = r"\|\s*tee(?:\s+-a)?\s+(?P<path>\"[^\"]+\"|'[^']+'|\S+)"
    for match in re.finditer(tee_pattern, command, flags=re.IGNORECASE):
        path = _resolve_path(_strip_quotes(match.group("path")), base_dir=base_dir)
        if path is not None:
            paths.append(path)
    return paths


def _extract_output_flag_paths(command: str, *, base_dir: Path | None = None) -> list[Path]:
    paths: list[Path] = []
    pattern = r"(?:^|\s)(?:-o|--output)\s+(?P<path>\"[^\"]+\"|'[^']+'|\S+)"
    for match in re.finditer(pattern, command, flags=re.IGNORECASE):
        path = _resolve_path(_strip_quotes(match.group("path")), base_dir=base_dir)
        if path is not None:
            paths.append(path)
    return paths


def _extract_powershell_write_paths(command: str, *, base_dir: Path | None = None) -> list[Path]:
    paths: list[Path] = []
    single_path_commands = {
        "set-content",
        "add-content",
        "out-file",
        "new-item",
        "remove-item",
    }
    for name in single_path_commands:
        paths.extend(
            _extract_powershell_named_or_positional_paths(
                command, name, allow_destination=False, base_dir=base_dir
            )
        )
    paths.extend(
        _extract_powershell_named_or_positional_paths(
            command, "copy-item", allow_destination=True, base_dir=base_dir
        )
    )
    paths.extend(
        _extract_powershell_named_or_positional_paths(
            command, "move-item", allow_destination=True, include_source=True, base_dir=base_dir
        )
    )
    return paths


def _extract_powershell_named_or_positional_paths(
    command: str,
    command_name: str,
    *,
    allow_destination: bool,
    include_source: bool = False,
    base_dir: Path | None = None,
) -> list[Path]:
    paths: list[Path] = []
    named_pattern = rf"\b{re.escape(command_name)}\b.*?(?:-(?:path|literalpath|filepath)\s+(?P<source>\"[^\"]+\"|'[^']+'|\S+))"
    destination_pattern = rf"\b{re.escape(command_name)}\b.*?(?:-destination\s+(?P<dest>\"[^\"]+\"|'[^']+'|\S+))"

    named_match = re.search(named_pattern, command, flags=re.IGNORECASE)
    if named_match and include_source:
        source_path = _resolve_path(_strip_quotes(named_match.group("source")), base_dir=base_dir)
        if source_path is not None:
            paths.append(source_path)

    if allow_destination:
        destination_match = re.search(destination_pattern, command, flags=re.IGNORECASE)
        if destination_match:
            destination_path = _resolve_path(_strip_quotes(destination_match.group("dest")), base_dir=base_dir)
            if destination_path is not None:
                paths.append(destination_path)
        else:
            positional_match = re.search(
                rf"\b{re.escape(command_name)}\b\s+(?P<source>\"[^\"]+\"|'[^']+'|\S+)\s+(?P<dest>\"[^\"]+\"|'[^']+'|\S+)",
                command,
                flags=re.IGNORECASE,
            )
            if positional_match:
                if include_source:
                    source_path = _resolve_path(_strip_quotes(positional_match.group("source")), base_dir=base_dir)
                    if source_path is not None:
                        paths.append(source_path)
                destination_path = _resolve_path(_strip_quotes(positional_match.group("dest")), base_dir=base_dir)
                if destination_path is not None:
                    paths.append(destination_path)
        return paths

    if named_match:
        path = _resolve_path(_strip_quotes(named_match.group("source")), base_dir=base_dir)
        if path is not None:
            paths.append(path)
        return paths

    positional_match = re.search(
        rf"\b{re.escape(command_name)}\b\s+(?P<path>\"[^\"]+\"|'[^']+'|\S+)",
        command,
        flags=re.IGNORECASE,
    )
    if positional_match:
        path = _resolve_path(_strip_quotes(positional_match.group("path")), base_dir=base_dir)
        if path is not None:
            paths.append(path)
    return paths


def _extract_cmd_write_paths(command: str, *, base_dir: Path | None = None) -> list[Path]:
    paths: list[Path] = []
    copy_match = re.search(
        r"(?:^|\s)copy\s+(?P<src>\"[^\"]+\"|'[^']+'|\S+)\s+(?P<dest>\"[^\"]+\"|'[^']+'|\S+)",
        command,
        flags=re.IGNORECASE,
    )
    if copy_match:
        destination_path = _resolve_path(_strip_quotes(copy_match.group("dest")), base_dir=base_dir)
        if destination_path is not None:
            paths.append(destination_path)

    move_match = re.search(
        r"(?:^|\s)move\s+(?P<src>\"[^\"]+\"|'[^']+'|\S+)\s+(?P<dest>\"[^\"]+\"|'[^']+'|\S+)",
        command,
        flags=re.IGNORECASE,
    )
    if move_match:
        source_path = _resolve_path(_strip_quotes(move_match.group("src")), base_dir=base_dir)
        destination_path = _resolve_path(_strip_quotes(move_match.group("dest")), base_dir=base_dir)
        if source_path is not None:
            paths.append(source_path)
        if destination_path is not None:
            paths.append(destination_path)
    return paths


def _dedupe_paths(paths: Iterable[Path]) -> list[Path]:
    deduped: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(path)
    return deduped


def _is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
        return True
    except ValueError:
        return False


def _non_flag_paths(args: Iterable[str], *, base_dir: Path | None = None) -> list[Path]:
    paths = []
    for arg in args:
        if arg.startswith("-"):
            continue
        path = _resolve_path(_strip_quotes(arg), base_dir=base_dir)
        if path is not None:
            paths.append(path)
    return paths


def _extract_last_non_flag_path(args: Iterable[str], *, base_dir: Path | None = None) -> Path | None:
    paths = _non_flag_paths(args, base_dir=base_dir)
    if not paths:
        return None
    return paths[-1]


def _extract_first_non_flag_path(args: Iterable[str], *, base_dir: Path | None = None) -> Path | None:
    paths = _non_flag_paths(args, base_dir=base_dir)
    if not paths:
        return None
    return paths[0]


def _is_git_mutation(args: list[str]) -> bool:
    if not args:
        return False
    subcommand = args[0].lower()
    if subcommand == "apply":
        return False
    if subcommand == "checkout":
        return len(args) >= 3 and args[1] == "--"
    if subcommand == "restore":
        return len(args) >= 2
    return False


def _extract_git_mutation(
    args: list[str], *, base_dir: Path | None = None
) -> tuple[AccessAction, list[Path]] | None:
    if not args:
        return None

    subcommand = args[0].lower()
    if subcommand == "checkout":
        if len(args) == 3 and args[1] == "--" and args[2] != ".":
            path = _resolve_path(args[2], base_dir=base_dir)
            return ("write", [path]) if path else None
        return None

    if subcommand == "restore":
        non_flag_args = [arg for arg in args[1:] if not arg.startswith("-")]
        if len(non_flag_args) == 1 and non_flag_args[0] != ".":
            path = _resolve_path(non_flag_args[0], base_dir=base_dir)
            return ("write", [path]) if path else None
        return None

    return None
