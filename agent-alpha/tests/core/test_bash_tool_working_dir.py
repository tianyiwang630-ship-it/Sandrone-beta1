from pathlib import Path
import io
import os
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from agent.tools.bash_tool import BashTool


class ImmediatePopen:
    def __init__(self, args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.returncode = 0
        self.stdout = io.StringIO("ok")
        self.stderr = io.StringIO("")

    def poll(self):
        return self.returncode

    def communicate(self, timeout=None):
        return "ok", ""


class StoreAliasPopen:
    def __init__(self, args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.returncode = 0
        self.stdout = io.StringIO(
            "Python was not found; run without arguments to install from the Microsoft Store, "
            "or disable this shortcut from Settings > Apps > Advanced app settings > App execution aliases.\n"
        )
        self.stderr = io.StringIO("")

    def poll(self):
        return self.returncode


def _tool(monkeypatch, tmp_path):
    calls = []

    def fake_popen(args, **kwargs):
        proc = ImmediatePopen(args, **kwargs)
        calls.append(proc)
        return proc

    monkeypatch.setattr(BashTool, "_detect_shell", lambda self: setattr(self, "shell", "bash"))
    monkeypatch.setattr("agent.tools.bash_tool.subprocess.Popen", fake_popen)

    project_root = tmp_path / "project"
    project_root.mkdir()
    return BashTool(project_root=project_root), project_root, calls


def _create_venv_python(project_root: Path) -> Path:
    relative = Path(".venv") / ("Scripts" if os.name == "nt" else "bin") / ("python.exe" if os.name == "nt" else "python")
    venv_python = project_root / relative
    venv_python.parent.mkdir(parents=True)
    venv_python.write_text("", encoding="utf-8")
    return venv_python


def test_bash_defaults_to_project_root_cwd(monkeypatch, tmp_path):
    tool, project_root, calls = _tool(monkeypatch, tmp_path)

    result = tool.execute(command="pwd")

    assert result["success"] is True
    assert calls[0].kwargs["cwd"] == str(project_root)


def test_bash_tool_definition_documents_working_dir(monkeypatch, tmp_path):
    tool, _project_root, _calls = _tool(monkeypatch, tmp_path)

    definition = tool.get_tool_definition()
    parameters = definition["function"]["parameters"]

    assert "working_dir" in parameters["properties"]
    assert parameters["required"] == ["command"]
    assert "project_root" in parameters["properties"]["working_dir"]["description"]


def test_bash_resolves_relative_working_dir_from_project_root(monkeypatch, tmp_path):
    tool, project_root, calls = _tool(monkeypatch, tmp_path)
    jobs_dir = project_root / "workspace" / "jobs"
    jobs_dir.mkdir(parents=True)

    result = tool.execute(command="pwd", working_dir="workspace/jobs")

    assert result["success"] is True
    assert calls[0].kwargs["cwd"] == str(jobs_dir.resolve())


def test_bash_allows_absolute_working_dir_inside_project_root(monkeypatch, tmp_path):
    tool, project_root, calls = _tool(monkeypatch, tmp_path)
    jobs_dir = project_root / "workspace" / "jobs"
    jobs_dir.mkdir(parents=True)

    result = tool.execute(command="pwd", working_dir=str(jobs_dir))

    assert result["success"] is True
    assert calls[0].kwargs["cwd"] == str(jobs_dir.resolve())


def test_bash_resolves_git_bash_style_working_dir_on_windows(monkeypatch, tmp_path):
    tool, project_root, calls = _tool(monkeypatch, tmp_path)
    if not project_root.drive:
        return

    jobs_dir = project_root / "workspace" / "jobs"
    jobs_dir.mkdir(parents=True)
    drive = jobs_dir.drive.rstrip(":").lower()
    path_without_drive = jobs_dir.as_posix().split(":/", 1)[1]

    result = tool.execute(command="pwd", working_dir=f"/{drive}/{path_without_drive}")

    assert result["success"] is True
    assert calls[0].kwargs["cwd"] == str(jobs_dir.resolve())


def test_bash_rejects_working_dir_outside_project_root(monkeypatch, tmp_path):
    tool, _project_root, calls = _tool(monkeypatch, tmp_path)
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()

    result = tool.execute(command="pwd", working_dir=str(outside_dir))

    assert result["success"] is False
    assert "working_dir" in result["error"]
    assert calls == []


def test_bash_splits_simple_cd_prefix_into_working_dir(monkeypatch, tmp_path):
    tool, project_root, calls = _tool(monkeypatch, tmp_path)
    _create_venv_python(project_root)
    jobs_dir = project_root / "workspace" / "jobs"
    jobs_dir.mkdir(parents=True)

    result = tool.execute(command=f'cd "{jobs_dir}" && python run.py')

    assert result["success"] is True
    assert calls[0].kwargs["cwd"] == str(jobs_dir.resolve())
    assert calls[0].args == ["bash", "-c", "python run.py"]
    assert result["command"] == "python run.py"
    assert result["working_dir"] == str(jobs_dir.resolve())


def test_bash_reports_guidance_for_complex_cd(monkeypatch, tmp_path):
    tool, _project_root, calls = _tool(monkeypatch, tmp_path)

    result = tool.execute(command="cd workspace && cd jobs && python run.py")

    assert result["success"] is False
    assert "working_dir" in result["error"]
    assert calls == []


def test_bash_rejects_python_command_when_alpha_venv_python_is_missing(monkeypatch, tmp_path):
    tool, _project_root, calls = _tool(monkeypatch, tmp_path)

    result = tool.execute(command="python -m pytest")

    assert result["success"] is False
    assert "agent-alpha .venv Python" in result["error"]
    assert "guidance" in result
    assert calls == []


def test_bash_allows_python_command_when_alpha_venv_python_exists(monkeypatch, tmp_path):
    tool, project_root, calls = _tool(monkeypatch, tmp_path)
    _create_venv_python(project_root)

    result = tool.execute(command="python -m pytest")

    assert result["success"] is True
    assert calls[0].args == ["bash", "-c", "python -m pytest"]
    assert calls[0].kwargs["env"]["PYTHONNOUSERSITE"] == "1"


def test_bash_allows_explicit_relative_venv_python_with_dotdot(monkeypatch, tmp_path):
    tool, project_root, calls = _tool(monkeypatch, tmp_path)
    venv_python = project_root / ".venv" / "Scripts" / "python.exe"
    venv_python.parent.mkdir(parents=True)
    venv_python.write_text("", encoding="utf-8")

    result = tool.execute(command=".venv/Scripts/../Scripts/python.exe -m pytest")

    assert result["success"] is True
    assert calls[0].args == ["bash", "-c", ".venv/Scripts/../Scripts/python.exe -m pytest"]


def test_bash_rejects_uv_non_python_file_inside_venv_when_called_directly(monkeypatch, tmp_path):
    tool, project_root, calls = _tool(monkeypatch, tmp_path)
    fake_launcher = project_root / ".venv" / "Scripts" / "not-python.exe"
    fake_launcher.parent.mkdir(parents=True)
    fake_launcher.write_text("", encoding="utf-8")

    result = tool.execute(command=f'uv run --python "{fake_launcher}" script.py')

    assert result["success"] is False
    assert "agent-alpha .venv Python" in result["error"]
    assert calls == []


def test_bash_rejects_conda_run_python_even_when_called_directly(monkeypatch, tmp_path):
    tool, project_root, calls = _tool(monkeypatch, tmp_path)
    _create_venv_python(project_root)

    result = tool.execute(command="conda run -n other python -c \"print(1)\"")

    assert result["success"] is False
    assert "agent-alpha .venv Python" in result["error"]
    assert calls == []


def test_bash_rejects_uv_external_python_even_when_called_directly(monkeypatch, tmp_path):
    tool, project_root, calls = _tool(monkeypatch, tmp_path)
    _create_venv_python(project_root)

    result = tool.execute(command=r"uv run --python C:\OtherPython\python.exe script.py")

    assert result["success"] is False
    assert "agent-alpha .venv Python" in result["error"]
    assert calls == []


def test_bash_rejects_powershell_path_override_before_python(monkeypatch, tmp_path):
    tool, project_root, calls = _tool(monkeypatch, tmp_path)
    _create_venv_python(project_root)

    result = tool.execute(command=r"$env:Path='C:\OtherPython'; python -m pytest")

    assert result["success"] is False
    assert "agent-alpha .venv Python" in result["error"]
    assert calls == []


def test_bash_appends_guidance_for_microsoft_store_python_alias(monkeypatch, tmp_path):
    calls = []

    def fake_popen(args, **kwargs):
        proc = StoreAliasPopen(args, **kwargs)
        calls.append(proc)
        return proc

    monkeypatch.setattr(BashTool, "_detect_shell", lambda self: setattr(self, "shell", "bash"))
    monkeypatch.setattr("agent.tools.bash_tool.subprocess.Popen", fake_popen)
    project_root = tmp_path / "project"
    project_root.mkdir()
    _create_venv_python(project_root)
    tool = BashTool(project_root=project_root)

    result = tool.execute(command="python -m pytest")

    assert result["success"] is True
    assert "Microsoft Store" in result["stdout"]
    assert "agent-alpha .venv Python" in result["guidance"]


def test_two_bash_tools_for_different_agents_use_separate_runtime_envs(monkeypatch, tmp_path):
    calls = []

    def fake_popen(args, **kwargs):
        proc = ImmediatePopen(args, **kwargs)
        calls.append(proc)
        return proc

    monkeypatch.setattr(BashTool, "_detect_shell", lambda self: setattr(self, "shell", "bash"))
    monkeypatch.setattr("agent.tools.bash_tool.subprocess.Popen", fake_popen)
    agent_a = tmp_path / "agent-a"
    agent_b = tmp_path / "agent-b"
    agent_a.mkdir()
    agent_b.mkdir()
    _create_venv_python(agent_a)
    _create_venv_python(agent_b)

    result_a = BashTool(project_root=agent_a).execute(command="python -m pytest")
    result_b = BashTool(project_root=agent_b).execute(command="python -m pytest")

    assert result_a["success"] is True
    assert result_b["success"] is True
    assert calls[0].kwargs["env"]["AGENT_ALPHA_ROOT"] == str(agent_a.resolve())
    assert calls[1].kwargs["env"]["AGENT_ALPHA_ROOT"] == str(agent_b.resolve())
    assert calls[0].kwargs["env"]["VIRTUAL_ENV"] == str(agent_a.resolve() / ".venv")
    assert calls[1].kwargs["env"]["VIRTUAL_ENV"] == str(agent_b.resolve() / ".venv")


def test_two_bash_tools_for_same_agent_do_not_share_env_mapping(monkeypatch, tmp_path):
    calls = []

    def fake_popen(args, **kwargs):
        proc = ImmediatePopen(args, **kwargs)
        calls.append(proc)
        return proc

    monkeypatch.setattr(BashTool, "_detect_shell", lambda self: setattr(self, "shell", "bash"))
    monkeypatch.setattr("agent.tools.bash_tool.subprocess.Popen", fake_popen)
    project_root = tmp_path / "agent-alpha"
    project_root.mkdir()
    _create_venv_python(project_root)
    tool_a = BashTool(project_root=project_root)
    tool_b = BashTool(project_root=project_root)

    result_a = tool_a.execute(command="python -m pytest")
    calls[0].kwargs["env"]["WINDOW_LOCAL_MUTATION"] = "only-first-call"
    result_b = tool_b.execute(command="python -m pytest")

    assert result_a["success"] is True
    assert result_b["success"] is True
    assert calls[0].kwargs["env"] is not calls[1].kwargs["env"]
    assert "WINDOW_LOCAL_MUTATION" not in calls[1].kwargs["env"]
