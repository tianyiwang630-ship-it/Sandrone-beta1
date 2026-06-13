import os
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from agent.core.runtime_paths import apply_runtime_env, build_runtime_env, ensure_runtime_directories


def test_build_runtime_env_redirects_common_user_dirs_inside_agent_alpha(tmp_path):
    project_root = tmp_path / "agent-alpha"
    base_env = {"PATH": "C:/Windows/System32", "NPM_CONFIG_PREFIX": "keep-me"}

    env = build_runtime_env(project_root, base_env=base_env)

    assert env["HOME"] == str(project_root / "home")
    assert env["USERPROFILE"] == str(project_root / "home")
    assert env["XDG_CONFIG_HOME"] == str(project_root / "config")
    assert env["XDG_CACHE_HOME"] == str(project_root / "cache")
    assert env["APPDATA"] == str(project_root / "config" / "appdata")
    assert env["LOCALAPPDATA"] == str(project_root / "data" / "localappdata")
    assert env["PIP_CACHE_DIR"] == str(project_root / "cache" / "pip")
    assert env["UV_CACHE_DIR"] == str(project_root / "cache" / "uv")
    assert env["UV_TOOL_DIR"] == str(project_root / "tools" / "uv")
    assert env["VIRTUAL_ENV"] == str(project_root / ".venv")
    assert env["AGENT_ALPHA_ROOT"] == str(project_root)
    path_entries = env["PATH"].split(os.pathsep)
    assert str(project_root / ".venv" / "Scripts") == path_entries[0]
    assert str(project_root / "bin") == path_entries[1]
    assert env["NPM_CONFIG_PREFIX"] == "keep-me"
    assert "GOPATH" not in env


def test_build_runtime_env_adds_local_python_scripts_to_path_when_present(tmp_path):
    project_root = tmp_path / "agent-alpha"
    local_scripts = project_root / "home" / ".local" / "Python313" / "Scripts"
    local_scripts.mkdir(parents=True)

    env = build_runtime_env(project_root, base_env={"PATH": "C:/Windows/System32"})

    path_entries = env["PATH"].split(os.pathsep)
    assert str(project_root / ".venv" / "Scripts") == path_entries[0]
    assert str(project_root / "bin") == path_entries[1]
    assert str(local_scripts) == path_entries[2]


def test_build_runtime_env_loads_local_runtime_env_profile(tmp_path):
    project_root = tmp_path / "agent-alpha"
    profile_path = project_root / "config" / "runtime_env.local.json"
    profile_path.parent.mkdir(parents=True)
    profile_path.write_text(
        '{"TWITTER_AUTH_TOKEN": "auth-token", "TWITTER_CT0": "ct0-token"}',
        encoding="utf-8-sig",
    )

    env = build_runtime_env(project_root, base_env={})

    assert env["TWITTER_AUTH_TOKEN"] == "auth-token"
    assert env["TWITTER_CT0"] == "ct0-token"


def test_windows_runtime_env_defaults_python_utf8_and_ignores_host_encoding(monkeypatch, tmp_path):
    import agent.core.runtime_paths as runtime_paths

    monkeypatch.setattr(runtime_paths, "_runtime_os_name", lambda: "nt", raising=False)
    project_root = tmp_path / "agent-alpha"

    env = build_runtime_env(
        project_root,
        base_env={
            "PATH": "C:/Windows/System32",
            "PYTHONUTF8": "0",
            "PYTHONIOENCODING": "gbk",
        },
    )

    assert env["PYTHONUTF8"] == "1"
    assert env["PYTHONIOENCODING"] == "utf-8"


def test_runtime_env_profile_can_override_python_encoding_defaults(monkeypatch, tmp_path):
    import agent.core.runtime_paths as runtime_paths

    monkeypatch.setattr(runtime_paths, "_runtime_os_name", lambda: "nt", raising=False)
    project_root = tmp_path / "agent-alpha"
    profile_path = project_root / "config" / "runtime_env.local.json"
    profile_path.parent.mkdir(parents=True)
    profile_path.write_text(
        '{"PYTHONUTF8": "0", "PYTHONIOENCODING": "gbk"}',
        encoding="utf-8",
    )

    env = build_runtime_env(project_root, base_env={"PATH": "C:/Windows/System32"})

    assert env["PYTHONUTF8"] == "0"
    assert env["PYTHONIOENCODING"] == "gbk"


def test_runtime_env_profile_normalizes_lowercase_python_encoding_keys(monkeypatch, tmp_path):
    import agent.core.runtime_paths as runtime_paths

    monkeypatch.setattr(runtime_paths, "_runtime_os_name", lambda: "nt", raising=False)
    project_root = tmp_path / "agent-alpha"
    profile_path = project_root / "config" / "runtime_env.local.json"
    profile_path.parent.mkdir(parents=True)
    profile_path.write_text(
        '{"pythonutf8": "0", "pythonioencoding": "gbk"}',
        encoding="utf-8",
    )

    env = build_runtime_env(project_root, base_env={"PATH": "C:/Windows/System32"})

    assert env["PYTHONUTF8"] == "0"
    assert env["PYTHONIOENCODING"] == "gbk"
    assert "pythonutf8" not in env
    assert "pythonioencoding" not in env


def test_posix_runtime_env_does_not_invent_windows_python_encoding(monkeypatch, tmp_path):
    import agent.core.runtime_paths as runtime_paths

    monkeypatch.setattr(runtime_paths, "_runtime_os_name", lambda: "posix", raising=False)
    project_root = tmp_path / "agent-alpha"

    env = build_runtime_env(project_root, base_env={"PATH": "/usr/bin"})

    assert env["PATH"].split(os.pathsep)[0] == str(project_root / ".venv" / "bin")
    assert "PYTHONUTF8" not in env
    assert "PYTHONIOENCODING" not in env


def test_posix_runtime_env_uses_encoding_only_when_profile_explicitly_sets_it(monkeypatch, tmp_path):
    import agent.core.runtime_paths as runtime_paths

    monkeypatch.setattr(runtime_paths, "_runtime_os_name", lambda: "posix", raising=False)
    project_root = tmp_path / "agent-alpha"
    profile_path = project_root / "config" / "runtime_env.local.json"
    profile_path.parent.mkdir(parents=True)
    profile_path.write_text(
        '{"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}',
        encoding="utf-8",
    )

    env = build_runtime_env(project_root, base_env={"PATH": "/usr/bin", "PYTHONUTF8": "0"})

    assert env["PATH"].split(os.pathsep)[0] == str(project_root / ".venv" / "bin")
    assert env["PYTHONUTF8"] == "1"
    assert env["PYTHONIOENCODING"] == "utf-8"


def test_runtime_env_scrubs_host_python_and_conda_pollution(tmp_path):
    project_root = tmp_path / "agent-alpha"

    env = build_runtime_env(
        project_root,
        base_env={
            "PATH": "C:/Windows/System32",
            "PYTHONHOME": "C:/PythonHome",
            "PYTHONPATH": "C:/leak",
            "CONDA_PREFIX": "D:/Anaconda/envs/ai12",
            "CONDA_DEFAULT_ENV": "ai12",
            "CONDA_PROMPT_MODIFIER": "(ai12)",
        },
    )

    assert "PYTHONHOME" not in env
    assert "PYTHONPATH" not in env
    assert "CONDA_PREFIX" not in env
    assert "CONDA_DEFAULT_ENV" not in env
    assert "CONDA_PROMPT_MODIFIER" not in env
    assert env["PYTHONNOUSERSITE"] == "1"


def test_apply_runtime_env_updates_target_env_from_local_profile(tmp_path):
    project_root = tmp_path / "agent-alpha"
    profile_path = project_root / "config" / "runtime_env.local.json"
    profile_path.parent.mkdir(parents=True)
    profile_path.write_text(
        '{"CUSTOM_TOKEN": "token-value", "AGENT_BROWSER_EXECUTABLE_PATH": "C:/Chrome/chrome.exe"}',
        encoding="utf-8-sig",
    )
    target_env = {"PATH": "C:/Windows/System32"}

    env = apply_runtime_env(project_root, base_env=target_env, target_env=target_env)

    assert env["CUSTOM_TOKEN"] == "token-value"
    assert target_env["CUSTOM_TOKEN"] == "token-value"
    assert target_env["AGENT_BROWSER_EXECUTABLE_PATH"] == "C:/Chrome/chrome.exe"
    assert target_env["AGENT_ALPHA_ROOT"] == str(project_root.resolve())


def test_runtime_env_profile_cannot_override_alpha_runtime_dirs(tmp_path):
    project_root = tmp_path / "agent-alpha"
    profile_path = project_root / "config" / "runtime_env.local.json"
    profile_path.parent.mkdir(parents=True)
    profile_path.write_text(
        '{"HOME": "C:/Users/not-alpha", "Path": "C:/bad", "AGENT_ALPHA_ROOT": "C:/bad", "TWITTER_AUTH_TOKEN": "auth-token"}',
        encoding="utf-8",
    )

    env = build_runtime_env(project_root, base_env={"PATH": "C:/Windows/System32"})

    assert env["HOME"] == str(project_root / "home")
    assert env["AGENT_ALPHA_ROOT"] == str(project_root)
    assert env["PATH"].endswith("C:/Windows/System32")
    assert "C:/bad" not in env["PATH"]
    assert "Path" not in env
    assert env["TWITTER_AUTH_TOKEN"] == "auth-token"


def test_runtime_env_isolated_between_two_agent_roots(tmp_path):
    agent_a = tmp_path / "agent-alpha-a"
    agent_b = tmp_path / "agent-alpha-b"
    for root, token in [(agent_a, "token-a"), (agent_b, "token-b")]:
        profile_path = root / "config" / "runtime_env.local.json"
        profile_path.parent.mkdir(parents=True)
        profile_path.write_text(f'{{"CUSTOM_TOKEN": "{token}"}}', encoding="utf-8")

    env_a = build_runtime_env(agent_a, base_env={"PATH": "C:/Windows/System32"})
    env_b = build_runtime_env(agent_b, base_env={"PATH": "C:/Windows/System32"})

    assert env_a["AGENT_ALPHA_ROOT"] == str(agent_a.resolve())
    assert env_b["AGENT_ALPHA_ROOT"] == str(agent_b.resolve())
    assert env_a["VIRTUAL_ENV"] == str(agent_a.resolve() / ".venv")
    assert env_b["VIRTUAL_ENV"] == str(agent_b.resolve() / ".venv")
    assert env_a["CUSTOM_TOKEN"] == "token-a"
    assert env_b["CUSTOM_TOKEN"] == "token-b"
    assert str(agent_b.resolve()) not in env_a["PATH"]
    assert str(agent_a.resolve()) not in env_b["PATH"]


def test_runtime_env_returns_fresh_mapping_for_multi_window_calls(tmp_path):
    project_root = tmp_path / "agent-alpha"

    env_a = build_runtime_env(project_root, base_env={"PATH": "C:/Windows/System32"})
    env_b = build_runtime_env(project_root, base_env={"PATH": "C:/Windows/System32"})
    env_a["WINDOW_LOCAL_MUTATION"] = "only-a"

    assert env_b.get("WINDOW_LOCAL_MUTATION") is None
    assert env_a is not env_b


def test_apply_runtime_env_removes_previous_agent_profile_keys(tmp_path):
    agent_a = tmp_path / "agent-alpha-a"
    agent_b = tmp_path / "agent-alpha-b"
    profile_a = agent_a / "config" / "runtime_env.local.json"
    profile_b = agent_b / "config" / "runtime_env.local.json"
    profile_a.parent.mkdir(parents=True)
    profile_b.parent.mkdir(parents=True)
    profile_a.write_text('{"AGENT_A_ONLY": "secret-a"}', encoding="utf-8")
    profile_b.write_text('{"AGENT_B_ONLY": "secret-b"}', encoding="utf-8")
    process_env = {"PATH": "C:/Windows/System32"}

    apply_runtime_env(agent_a, base_env=process_env, target_env=process_env)
    apply_runtime_env(agent_b, base_env=process_env, target_env=process_env)

    assert "AGENT_A_ONLY" not in process_env
    assert process_env["AGENT_B_ONLY"] == "secret-b"
    assert process_env["AGENT_ALPHA_ROOT"] == str(agent_b.resolve())


def test_ensure_runtime_directories_creates_project_internal_tree(tmp_path):
    project_root = tmp_path / "agent-alpha"

    ensure_runtime_directories(project_root)

    for relative in [
        "home",
        "home/.agents/skills",
        "bin",
        "userfile",
        "skills",
        "temp",
        "cache",
        "tools",
        "config/appdata",
        "data/localappdata",
        "state",
    ]:
        assert (project_root / relative).is_dir()


def test_start_script_uses_runtime_paths_as_single_env_source():
    script = (PROJECT_ROOT / "start-agent-alpha.ps1").read_text(encoding="utf-8")

    assert "build_runtime_env" in script
    assert "ensure_runtime_directories" in script
    assert "$env:HOME =" not in script
    assert "$env:PATH = \"$ScriptsDir;$AgentBinDir;$env:PATH\"" not in script


def test_cli_and_runtime_apply_runtime_env_on_startup():
    cli_main = (PROJECT_ROOT / "agent" / "cli" / "main.py").read_text(encoding="utf-8")
    agent_runtime = (PROJECT_ROOT / "agent" / "core" / "agent_runtime.py").read_text(encoding="utf-8")

    assert "apply_runtime_env(project_root)" in cli_main
    assert "apply_runtime_env(PROJECT_ROOT)" in agent_runtime
