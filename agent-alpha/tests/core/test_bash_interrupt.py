from pathlib import Path
import io
import sys
import threading


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from agent.tools.bash_tool import BashTool
from agent.tools import process_utils


class FakePopen:
    def __init__(self, *args, **kwargs):
        self.pid = 12345
        self.returncode = None
        self.stopped = False
        self.stdout = io.StringIO("partial stdout")
        self.stderr = io.StringIO("partial stderr")

    def poll(self):
        return self.returncode

    def communicate(self, timeout=None):
        self.returncode = -1
        return "partial stdout", "partial stderr"

    def wait(self, timeout=None):
        self.returncode = -1
        return self.returncode

    def kill(self):
        self.returncode = -9


def test_bash_tool_interrupt_kills_process_tree(monkeypatch, tmp_path):
    event = threading.Event()
    event.set()
    fake_proc = FakePopen()
    killed = []

    monkeypatch.setattr(BashTool, "_detect_shell", lambda self: setattr(self, "shell", "cmd"))
    monkeypatch.setattr("agent.tools.bash_tool.subprocess.Popen", lambda *args, **kwargs: fake_proc)

    def fake_terminate(proc):
        killed.append(proc.pid)
        proc.returncode = -1

    monkeypatch.setattr("agent.tools.bash_tool.terminate_process_tree", fake_terminate)

    tool = BashTool(project_root=tmp_path, interrupt_event=event, timeout=30)
    result = tool.execute(command="long-running-command")

    assert result["success"] is False
    assert result["interrupted"] is True
    assert result["error"] == "Command interrupted by ESC"
    assert killed == [12345]
    assert result["stdout"] == "partial stdout"
    assert result["stderr"] == "partial stderr"


def test_terminate_process_tree_uses_taskkill_on_windows(monkeypatch):
    calls = []
    fake_proc = FakePopen()

    monkeypatch.setattr(process_utils.os, "name", "nt")

    def fake_run(args, **kwargs):
        calls.append(args)

    monkeypatch.setattr(process_utils.subprocess, "run", fake_run)

    process_utils.terminate_process_tree(fake_proc)

    assert calls == [["taskkill", "/PID", "12345", "/T", "/F"]]


def test_terminate_process_tree_uses_process_group_on_posix(monkeypatch):
    calls = []
    fake_proc = FakePopen()

    monkeypatch.setattr(process_utils.os, "name", "posix")
    monkeypatch.setattr(process_utils.os, "killpg", lambda pid, sig: calls.append((pid, sig)), raising=False)

    process_utils.terminate_process_tree(fake_proc)

    assert calls == [(12345, process_utils.signal.SIGTERM)]
