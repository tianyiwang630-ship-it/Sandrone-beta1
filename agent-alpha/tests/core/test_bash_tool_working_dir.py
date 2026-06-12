from pathlib import Path
import io
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
