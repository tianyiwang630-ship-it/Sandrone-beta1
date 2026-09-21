from __future__ import annotations

import os
from pathlib import Path

from agent.core.runtime_paths import build_runtime_env, configure_standard_streams, ensure_runtime_directories


class RecordingStream:
    def __init__(self, *, error: Exception | None = None):
        self.error = error
        self.calls: list[dict[str, str]] = []

    def reconfigure(self, **kwargs: str) -> None:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error


def test_standard_streams_are_reconfigured_to_utf8():
    stdout = RecordingStream()
    stderr = RecordingStream()

    configure_standard_streams(stdout, stderr)

    expected = [{"encoding": "utf-8", "errors": "replace"}]
    assert stdout.calls == expected
    assert stderr.calls == expected


def test_standard_stream_failure_does_not_block_the_other_stream():
    stdout = RecordingStream(error=RuntimeError("unsupported"))
    stderr = RecordingStream()

    configure_standard_streams(stdout, stderr)

    assert stderr.calls == [{"encoding": "utf-8", "errors": "replace"}]


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


def test_runtime_env_preserves_host_browser_install_locations(tmp_path: Path):
    env = build_runtime_env(
        tmp_path,
        base_env={
            "LOCALAPPDATA": r"C:\Users\person\AppData\Local",
            "PROGRAMFILES": r"C:\Program Files",
            "PROGRAMFILES(X86)": r"C:\Program Files (x86)",
        },
    )

    assert env["AGENT_ALPHA_HOST_LOCALAPPDATA"] == r"C:\Users\person\AppData\Local"
    assert env["AGENT_ALPHA_HOST_PROGRAMFILES"] == r"C:\Program Files"
    assert env["AGENT_ALPHA_HOST_PROGRAMFILES_X86"] == r"C:\Program Files (x86)"


def test_development_runtime_does_not_enable_packaged_overrides(tmp_path: Path):
    root = tmp_path / "agent-alpha"

    env = build_runtime_env(root, base_env={"PATH": "host-path"})

    assert env["AGENT_ALPHA_ROOT"] == str(root.resolve())
    assert "AGENT_ALPHA_APP_ROOT" not in env
    assert "AGENT_ALPHA_PYTHON" not in env
    assert "AGENT_ALPHA_BROWSER_PYTHON" not in env
    assert "AGENT_ALPHA_NODE_EXECUTABLE" not in env


def test_packaged_runtime_env_keeps_resources_read_only_and_data_writable(tmp_path: Path):
    app_root = tmp_path / "resources" / "agent-alpha"
    data_root = tmp_path / "data" / "AgentAlpha"
    backend_python = app_root / "runtime" / "backend-python" / "python.exe"
    env = build_runtime_env(
        data_root,
        base_env={
            "PATH": "",
            "AGENT_ALPHA_APP_ROOT": str(app_root),
            "AGENT_ALPHA_ROOT": str(data_root),
            "AGENT_ALPHA_PYTHON": str(backend_python),
            "AGENT_ALPHA_BROWSER_PYTHON": str(app_root / "runtime" / "browser-python" / "python.exe"),
        },
    )

    assert Path(env["AGENT_ALPHA_APP_ROOT"]) == app_root.resolve()
    assert Path(env["AGENT_ALPHA_ROOT"]) == data_root.resolve()
    assert Path(env["AGENT_ALPHA_PYTHON"]) == backend_python.resolve()
    assert Path(env["HOME"]) == (data_root / "home").resolve()
    assert Path(env["TEMP"]) == (data_root / "temp").resolve()


def test_browser_harness_runtime_directories_are_created(tmp_path: Path):
    ensure_runtime_directories(tmp_path)

    assert (tmp_path / "state" / "browser-harness" / "runtime").is_dir()
    assert (tmp_path / "state" / "browser-harness" / "browser-profile").is_dir()
    assert (tmp_path / "state" / "browser-harness" / "agent-workspace").is_dir()
    assert (tmp_path / "temp" / "browser-harness").is_dir()


def test_runtime_path_entries_are_not_duplicated_when_env_is_applied_twice(tmp_path: Path):
    project_root = tmp_path / "portable-alpha"
    host_bin = tmp_path / "host-bin"

    first = build_runtime_env(project_root, base_env={"PATH": str(host_bin)})
    second = build_runtime_env(project_root, base_env=first)

    normalized = [os.path.normcase(os.path.normpath(value)) for value in second["PATH"].split(os.pathsep)]
    assert len(normalized) == len(set(normalized))
    assert normalized.count(os.path.normcase(os.path.normpath(str(host_bin)))) == 1
