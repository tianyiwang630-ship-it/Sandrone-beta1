from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Mapping, MutableMapping


RESERVED_RUNTIME_ENV_KEYS = {
    "AGENT_ALPHA_ROOT",
    "AGENT_ALPHA_RUNTIME_PROFILE_KEYS",
    "HOME",
    "USERPROFILE",
    "HOMEDRIVE",
    "HOMEPATH",
    "XDG_CONFIG_HOME",
    "XDG_CACHE_HOME",
    "XDG_DATA_HOME",
    "XDG_STATE_HOME",
    "APPDATA",
    "LOCALAPPDATA",
    "TMP",
    "TEMP",
    "PIP_CACHE_DIR",
    "UV_CACHE_DIR",
    "UV_TOOL_DIR",
    "PYTHONUSERBASE",
    "PYTHONPYCACHEPREFIX",
    "HF_HOME",
    "TRANSFORMERS_CACHE",
    "PLAYWRIGHT_BROWSERS_PATH",
    "DOTNET_CLI_HOME",
    "CARGO_HOME",
    "RUSTUP_HOME",
    "VIRTUAL_ENV",
    "PATH",
    "PYTHONHOME",
    "PYTHONPATH",
    "PYTHONNOUSERSITE",
    "CONDA_PREFIX",
    "CONDA_DEFAULT_ENV",
    "CONDA_PROMPT_MODIFIER",
}

PYTHON_ENCODING_ENV_KEYS = {"PYTHONUTF8", "PYTHONIOENCODING"}
HOST_PYTHON_ENV_KEYS = {
    "PYTHONHOME",
    "PYTHONPATH",
    "CONDA_PREFIX",
    "CONDA_DEFAULT_ENV",
    "CONDA_PROMPT_MODIFIER",
}
RUNTIME_PROFILE_KEYS_ENV = "AGENT_ALPHA_RUNTIME_PROFILE_KEYS"


def ensure_runtime_directories(project_root: Path) -> None:
    """Create agent-alpha's project-local runtime directory tree."""
    root = Path(project_root)
    for relative in [
        "home",
        "home/.agents/skills",
        "home/.local",
        "bin",
        "userfile",
        "skills",
        "temp",
        "cache",
        "cache/pip",
        "cache/uv",
        "cache/python",
        "cache/huggingface/transformers",
        "cache/playwright",
        "cache/cargo",
        "cache/rustup",
        "tools/uv",
        "config/appdata",
        "data/localappdata",
        "state",
        "state/browser",
        "state/browser/profiles",
        "state/browser/sessions",
        "state/browser/sockets",
        "state/browser/downloads",
        "state/browser/runtime",
    ]:
        (root / relative).mkdir(parents=True, exist_ok=True)


def apply_runtime_env(
    project_root: Path,
    *,
    base_env: Mapping[str, str] | None = None,
    target_env: MutableMapping[str, str] | None = None,
) -> dict[str, str]:
    """Apply agent-alpha runtime env to a process env mapping and return it."""
    root = Path(project_root)
    ensure_runtime_directories(root)
    env = build_runtime_env(root, base_env=base_env)
    target = target_env if target_env is not None else os.environ
    _remove_previous_profile_keys(target, os_name=_runtime_os_name())
    target.update(env)
    return env


def build_runtime_env(project_root: Path, *, base_env: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return environment variables that redirect normal user dirs into agent-alpha."""
    root = Path(project_root).resolve()
    home = root / "home"
    venv = root / ".venv"
    os_name = _runtime_os_name()
    scripts_dir = venv / ("Scripts" if os_name == "nt" else "bin")
    agent_bin_dir = root / "bin"
    env = _normalize_runtime_env(base_env or os.environ, os_name=os_name)
    _remove_previous_profile_keys(env, os_name=os_name)
    for key in HOST_PYTHON_ENV_KEYS | PYTHON_ENCODING_ENV_KEYS:
        _pop_env_key(env, key, os_name=os_name)
    profile = _load_runtime_env_profile(root)
    profile_keys = {key.upper() for key in profile}
    env.update(profile)

    runtime_values = {
        "AGENT_ALPHA_ROOT": root,
        RUNTIME_PROFILE_KEYS_ENV: json.dumps(sorted(profile), ensure_ascii=True),
        "HOME": home,
        "USERPROFILE": home,
        "XDG_CONFIG_HOME": root / "config",
        "XDG_CACHE_HOME": root / "cache",
        "XDG_DATA_HOME": root / "data",
        "XDG_STATE_HOME": root / "state",
        "APPDATA": root / "config" / "appdata",
        "LOCALAPPDATA": root / "data" / "localappdata",
        "TMP": root / "temp",
        "TEMP": root / "temp",
        "PIP_CACHE_DIR": root / "cache" / "pip",
        "UV_CACHE_DIR": root / "cache" / "uv",
        "UV_TOOL_DIR": root / "tools" / "uv",
        "PYTHONUSERBASE": home / ".local",
        "PYTHONPYCACHEPREFIX": root / "cache" / "python",
        "HF_HOME": root / "cache" / "huggingface",
        "TRANSFORMERS_CACHE": root / "cache" / "huggingface" / "transformers",
        "PLAYWRIGHT_BROWSERS_PATH": root / "cache" / "playwright",
        "DOTNET_CLI_HOME": home,
        "CARGO_HOME": root / "cache" / "cargo",
        "RUSTUP_HOME": root / "cache" / "rustup",
        "VIRTUAL_ENV": venv,
        "PYTHONNOUSERSITE": "1",
    }
    env.update({key: str(value) for key, value in runtime_values.items()})

    if os_name == "nt":
        drive = root.drive or home.drive
        env["HOMEDRIVE"] = drive
        env["HOMEPATH"] = str(home)[len(drive) :] if drive and str(home).startswith(drive) else str(home)
        if "PYTHONUTF8" not in profile_keys:
            env["PYTHONUTF8"] = "1"
        if "PYTHONIOENCODING" not in profile_keys:
            env["PYTHONIOENCODING"] = "utf-8"

    old_path = env.get("PATH", "")
    separator = os.pathsep
    path_prefix_entries = [scripts_dir, agent_bin_dir, *_local_python_scripts_dirs(root)]
    path_prefix = separator.join(str(path) for path in path_prefix_entries)
    env["PATH"] = path_prefix if not old_path else f"{path_prefix}{separator}{old_path}"
    return env


def _runtime_os_name() -> str:
    return os.name


def _normalize_runtime_env(env: Mapping[str, str], *, os_name: str) -> dict[str, str]:
    normalized: dict[str, str] = {}
    canonical_keys = RESERVED_RUNTIME_ENV_KEYS | PYTHON_ENCODING_ENV_KEYS
    for key, value in env.items():
        text_key = str(key)
        upper_key = text_key.upper()
        if os_name == "nt" and upper_key in canonical_keys:
            normalized[upper_key] = str(value)
        else:
            normalized[text_key] = str(value)
    return normalized


def _pop_env_key(env: MutableMapping[str, str], key: str, *, os_name: str) -> None:
    if os_name == "nt":
        upper_key = key.upper()
        for existing in list(env):
            if existing.upper() == upper_key:
                env.pop(existing, None)
        return
    env.pop(key, None)


def _remove_previous_profile_keys(env: MutableMapping[str, str], *, os_name: str) -> None:
    raw_keys = _get_env_value(env, RUNTIME_PROFILE_KEYS_ENV, os_name=os_name)
    if raw_keys:
        try:
            keys = json.loads(raw_keys)
        except Exception:
            keys = []
        if isinstance(keys, list):
            for key in keys:
                if isinstance(key, str):
                    _pop_env_key(env, key, os_name=os_name)
    _pop_env_key(env, RUNTIME_PROFILE_KEYS_ENV, os_name=os_name)


def _get_env_value(env: Mapping[str, str], key: str, *, os_name: str) -> str | None:
    if os_name == "nt":
        upper_key = key.upper()
        for existing, value in env.items():
            if existing.upper() == upper_key:
                return value
        return None
    return env.get(key)


def _local_python_scripts_dirs(project_root: Path) -> list[Path]:
    local_dir = project_root / "home" / ".local"
    if not local_dir.exists():
        return []

    return sorted(
        scripts_dir
        for scripts_dir in local_dir.glob("Python*/Scripts")
        if scripts_dir.is_dir()
    )


def _load_runtime_env_profile(project_root: Path) -> dict[str, str]:
    profile_path = Path(project_root) / "config" / "runtime_env.local.json"
    if not profile_path.exists():
        return {}

    try:
        data = json.loads(profile_path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}

    if not isinstance(data, dict):
        return {}

    result: dict[str, str] = {}
    for key, value in data.items():
        key_text = str(key)
        upper_key = key_text.upper()
        if not key_text or value is None or upper_key in RESERVED_RUNTIME_ENV_KEYS:
            continue
        if upper_key in PYTHON_ENCODING_ENV_KEYS:
            result[upper_key] = str(value)
        else:
            result[key_text] = str(value)
    return result
