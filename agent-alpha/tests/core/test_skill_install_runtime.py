import os
from pathlib import Path

from agent.core.runtime_info import write_runtime_info
from agent.core.runtime_paths import build_runtime_env, installation_env
from agent.core.runtime_layout import runtime_python
from agent.core.command_path_extractor import classify_package_install_scope
from agent.core.managed_python import resolve_python_entry
from agent.core.sandbox_guard import SandboxGuard
from agent.core.tool_loader import ToolLoader
from agent.tools.bash_tool import BashTool
from agent.tools import python_install_guard


def _layout(monkeypatch, root: Path) -> Path:
    monkeypatch.setenv("AGENT_ALPHA_APP_ROOT", str(root))
    monkeypatch.setenv("AGENT_ALPHA_ROOT", str(root))
    python = root / ".venv" / "Scripts" / "python.exe"
    python.parent.mkdir(parents=True)
    python.touch()
    monkeypatch.setenv("AGENT_ALPHA_PYTHON", str(python))
    return python


def test_runtime_guide_uses_actual_paths_without_private_variables(tmp_path, monkeypatch):
    root = tmp_path / "Alpha 数据"
    python = _layout(monkeypatch, root)
    monkeypatch.setenv("UV_VENV_CLEAR", "1")
    monkeypatch.setenv("SERVICE_SECRET", "private-value")
    path = write_runtime_info(data_root=root, app_root=root, built_in_skills=root / "skills",
                              third_party_skills=root / "home" / ".agents" / "skills")
    body = path.read_text(encoding="utf-8")
    assert str(python) in body
    assert str(root / "home" / ".agents" / "skills") in body
    assert "private-value" not in body
    assert "UV_VENV_CLEAR" not in body
    assert write_runtime_info(data_root=root, app_root=root, built_in_skills=root / "skills",
                              third_party_skills=root / "home" / ".agents" / "skills") == path


def test_install_env_removes_controls_but_preserves_service_variables(tmp_path, monkeypatch):
    root = tmp_path / "alpha"
    _layout(monkeypatch, root)
    env = build_runtime_env(root, base_env={"AGENT_ALPHA_APP_ROOT": str(root), "AGENT_ALPHA_ROOT": str(root),
                                            "UV_VENV_CLEAR": "1", "UV_WORKING_DIR": str(tmp_path),
                                            "SERVICE_URL": "https://example.test"})
    cleaned = installation_env(env)
    assert "UV_VENV_CLEAR" not in cleaned
    assert "UV_WORKING_DIR" not in cleaned
    assert cleaned["SERVICE_URL"] == "https://example.test"
    assert env["UV_VENV_CLEAR"] == "1"


def test_development_python_override_matches_terminal_path(tmp_path, monkeypatch):
    root = tmp_path / "alpha"
    root.mkdir()
    custom = root / "custom-python" / "python.exe"
    custom.parent.mkdir()
    custom.touch()
    base = {"AGENT_ALPHA_APP_ROOT": str(root), "AGENT_ALPHA_ROOT": str(root), "AGENT_ALPHA_PYTHON": str(custom)}
    for key, value in base.items():
        monkeypatch.setenv(key, value)
    assert runtime_python(root) == custom
    assert build_runtime_env(root, base_env=base)["PATH"].split(os.pathsep)[0] == str(custom.parent)
    if os.name == "nt":
        msys_path = f"/{custom.drive[0].lower()}{custom.as_posix()[2:]}"
        assert resolve_python_entry(msys_path, root, root)[1] == "shared"


def test_python_binding_keeps_explicit_skill_environment(tmp_path, monkeypatch):
    root = tmp_path / "alpha"
    shared = _layout(monkeypatch, root)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "python.exe").touch()
    skill = root / "tools" / "venvs" / "example"
    (skill / "Scripts").mkdir(parents=True)
    (skill / "pyvenv.cfg").touch()
    isolated = skill / "Scripts" / "python.exe"
    isolated.touch()
    tool = BashTool.__new__(BashTool)
    tool.project_root = root
    tool.workspace_root = workspace
    assert tool._prepare_command("python -c 'pass'", None)["command"].startswith(f'"{shared}"')
    assert tool._prepare_command(f'"{isolated}" -c "pass"', None)["command"].startswith(f'"{isolated}"')


def test_built_in_script_allowed_after_runtime_configuration(tmp_path, monkeypatch):
    root = tmp_path / "data"
    app = tmp_path / "resources"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    python = _layout(monkeypatch, root)
    built_in = app / "skills"
    built_in.mkdir(parents=True)
    packaged_python = app / "runtime" / "backend-python" / "python.exe"
    packaged_python.parent.mkdir(parents=True)
    packaged_python.touch()
    monkeypatch.setenv("AGENT_ALPHA_APP_ROOT", str(app))
    monkeypatch.setenv("AGENT_ALPHA_PYTHON", str(packaged_python))
    python = packaged_python
    script = built_in / "run.py"
    script.touch()
    guard = SandboxGuard(project_root=root, workspace_root=workspace, builtin_skills_dir=built_in)
    result = guard.check_tool_call("bash", {"command": f'"{python}" "{script}"'})
    assert result.decision == "allow"
    outside = app / "run.py"
    outside.touch()
    result = guard.check_tool_call("bash", {"command": f'"{python}" "{outside}"'})
    assert result.decision == "deny"

    loader = ToolLoader(project_root=root, app_root=app, workspace_root=workspace)
    loader.configure_runtime(workspace)
    assert loader.sandbox_guard.check_tool_call("bash", {"command": f'"{python}" "{script}"'}).decision == "allow"


def test_shared_install_checks_plan_under_lock_without_real_install(tmp_path, monkeypatch):
    root = tmp_path / "alpha"
    python = _layout(monkeypatch, root)
    (root / "temp").mkdir()
    (root / "state").mkdir()
    requirement = tmp_path / "requirements.txt"
    requirement.write_text("new-package==1.0\n", encoding="utf-8")
    calls = []

    def fake_stage(args, **kwargs):
        calls.append(args)
        if "list" in args:
            return python_install_guard.subprocess.CompletedProcess(args, 0, '[{"name":"existing","version":"2.0"}]', "")
        if "--dry-run" in args:
            assert (root / "state" / "skill-install.lock").exists()
            assert "existing==2.0" in Path(args[args.index("--constraint") + 1]).read_text(encoding="utf-8")
            return python_install_guard.subprocess.CompletedProcess(args, 0, "Would install new-package", "")
        return python_install_guard.subprocess.CompletedProcess(args, 0, "installed", "")

    monkeypatch.setattr(python_install_guard, "_run_stage", fake_stage)
    command = f'uv pip install --python "{python}" -r "{requirement}"'
    result = python_install_guard.install_shared(command, python=python, root=root, cwd=tmp_path,
                                                 env={}, timeout=30, interrupt_event=None)
    assert result["success"]
    assert len(calls) == 3
    assert calls[1][-1] == "--no-config"
    assert "--dry-run" not in calls[2]


def test_shared_install_rejects_unplanned_or_destructive_forms(tmp_path, monkeypatch):
    root = tmp_path / "alpha"
    python = _layout(monkeypatch, root)
    (root / "temp").mkdir()
    (root / "state").mkdir()
    assert not python_install_guard.install_shared(
        f'uv pip install --python "{python}" --exact package', python=python, root=root,
        cwd=root, env={}, timeout=30, interrupt_event=None,
    )["success"]
    assert not python_install_guard.install_shared(
        f'uv pip install --python "{python}" --dry-run package', python=python, root=root,
        cwd=root, env={}, timeout=30, interrupt_event=None,
    )["success"]


def test_uv_tool_python_can_run_but_cannot_receive_skill_packages(tmp_path, monkeypatch):
    root = tmp_path / "alpha"
    _layout(monkeypatch, root)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    tool_env = root / "tools" / "uv" / "browser-harness"
    (tool_env / "Scripts").mkdir(parents=True)
    (tool_env / "pyvenv.cfg").touch()
    executable = tool_env / "Scripts" / "python.exe"
    executable.touch()
    guard = SandboxGuard(project_root=root, workspace_root=workspace)
    assert guard.check_tool_call("bash", {"command": f'"{executable}" -c "pass"'}).decision == "allow"
    install = f'uv pip install --python "{executable}" package'
    assert classify_package_install_scope(install, project_root=root, base_dir=workspace) == "deny"
    assert guard.check_tool_call("bash", {"command": install}).decision == "deny"
    assert guard.check_tool_call("bash", {"command": f'"{executable}" -m pip uninstall package'}).decision == "deny"
    assert guard.check_tool_call("bash", {"command": f'uv pip list --python "{executable}"'}).decision == "allow"
    assert guard.check_tool_call("bash", {"command": "uv tool install --force browser-harness==0.1.13"}).decision == "deny"
    assert guard.check_tool_call("bash", {"command": "uv tool install browser-harness==0.1.13"}).decision == "deny"
    assert guard.check_tool_call("bash", {"command": "uv tool install other-tool==1.0"}).decision == "allow"


def test_environment_creation_is_limited_to_new_managed_directory(tmp_path, monkeypatch):
    root = tmp_path / "alpha"
    python = _layout(monkeypatch, root)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (root / "tools" / "venvs").mkdir(parents=True)
    guard = SandboxGuard(project_root=root, workspace_root=workspace)
    allowed = f'uv venv --no-project --no-config --python "{python}" "{root / "tools" / "venvs" / "new-skill"}"'
    escaped = f'uv venv --python "{python}" "{workspace / "other-env"}"'
    assert guard.check_tool_call("bash", {"command": allowed}).decision == "allow"
    assert guard.check_tool_call("bash", {"command": escaped}).decision == "deny"
