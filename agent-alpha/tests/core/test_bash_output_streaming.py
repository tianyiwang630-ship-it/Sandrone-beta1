import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from agent.tools.bash_tool import BashTool


def _cmd_tool(monkeypatch, tmp_path, timeout=2):
    monkeypatch.setattr(BashTool, "_detect_shell", lambda self: setattr(self, "shell", "cmd"))
    monkeypatch.setattr(BashTool, "_validate_alpha_python", lambda self, command: None)
    return BashTool(project_root=tmp_path, timeout=timeout)


def _python_script(tmp_path, name: str, code: str) -> str:
    script = tmp_path / name
    script.write_text(code, encoding="utf-8")
    return f"python {script}"


def test_bash_streams_large_stdout_without_deadlock(monkeypatch, tmp_path):
    tool = _cmd_tool(monkeypatch, tmp_path)

    result = tool.execute(
        command=_python_script(tmp_path, "large_stdout.py", "import sys\nsys.stdout.write('x' * 10000)\n")
    )

    assert result["success"] is True
    assert result["stdout"] == "x" * 10000
    assert result["stderr"] == ""


def test_bash_streams_large_stderr_without_deadlock(monkeypatch, tmp_path):
    tool = _cmd_tool(monkeypatch, tmp_path)

    result = tool.execute(
        command=_python_script(tmp_path, "large_stderr.py", "import sys\nsys.stderr.write('e' * 10000)\n")
    )

    assert result["success"] is True
    assert result["stdout"] == ""
    assert result["stderr"] == "e" * 10000


def test_bash_timeout_returns_partial_streamed_output(monkeypatch, tmp_path):
    tool = _cmd_tool(monkeypatch, tmp_path, timeout=1)
    code = "import sys, time\nsys.stdout.write('started')\nsys.stdout.flush()\ntime.sleep(5)\n"

    result = tool.execute(command=_python_script(tmp_path, "slow_output.py", code))

    assert result["success"] is False
    assert "命令超时" in result["error"]
    assert result["stdout"] == "started"
