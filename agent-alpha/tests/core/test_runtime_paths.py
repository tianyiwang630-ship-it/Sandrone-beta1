from __future__ import annotations

import os
from pathlib import Path

from agent.core.runtime_paths import build_runtime_env


def test_runtime_env_exposes_harness_node_and_tool_locations(tmp_path: Path):
    project_root = tmp_path / "portable-alpha"

    env = build_runtime_env(project_root, base_env={"PATH": str(tmp_path / "host-bin")})

    npm_prefix = project_root / "config" / "appdata" / "npm"
    assert Path(env["NODE_PATH"]) == (npm_prefix / "node_modules").resolve()
    assert Path(env["NPM_CONFIG_PREFIX"]) == npm_prefix.resolve()
    assert Path(env["NPM_CONFIG_CACHE"]) == (project_root / "cache" / "npm").resolve()
    assert Path(env["UV_TOOL_BIN_DIR"]) == (project_root / "bin").resolve()

    path_entries = [Path(value) for value in env["PATH"].split(os.pathsep)]
    expected_entries = {
        (project_root / "bin").resolve(),
        (project_root / "home" / ".local" / "bin").resolve(),
        (project_root / "cache" / "cargo" / "bin").resolve(),
        (project_root / "home" / ".dotnet" / "tools").resolve(),
    }
    if os.name == "nt":
        expected_entries.add(npm_prefix.resolve())
    else:
        expected_entries.add((npm_prefix / "bin").resolve())
    assert expected_entries.issubset(set(path_entries))


def test_runtime_path_entries_are_not_duplicated_when_env_is_applied_twice(tmp_path: Path):
    project_root = tmp_path / "portable-alpha"
    host_bin = tmp_path / "host-bin"

    first = build_runtime_env(project_root, base_env={"PATH": str(host_bin)})
    second = build_runtime_env(project_root, base_env=first)

    normalized = [os.path.normcase(os.path.normpath(value)) for value in second["PATH"].split(os.pathsep)]
    assert len(normalized) == len(set(normalized))
    assert normalized.count(os.path.normcase(os.path.normpath(str(host_bin)))) == 1
