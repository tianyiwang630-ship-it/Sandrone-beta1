from __future__ import annotations

import io
from pathlib import Path

import pytest

from agent.tools import bash_tool as bash_module
from agent.tools.bash_tool import BashTool


def make_tool(tmp_path: Path) -> BashTool:
    project_root = tmp_path / "alpha"
    project_root.mkdir()
    tool = BashTool.__new__(BashTool)
    tool.timeout = 30
    tool.max_timeout = 300
    tool.project_root = project_root.resolve()
    tool.workspace_root = project_root.resolve()
    tool.interrupt_event = None
    tool.shell = "cmd"
    return tool


def test_tool_definition_exposes_timeout_seconds(tmp_path: Path):
    tool = make_tool(tmp_path)

    definition = tool.get_tool_definition()
    timeout_schema = definition["function"]["parameters"]["properties"]["timeout_seconds"]

    assert timeout_schema["type"] == "integer"
    assert timeout_schema["minimum"] == 1
    assert timeout_schema["maximum"] == 300
    assert "Defaults to 30 seconds" in timeout_schema["description"]


def test_timeout_seconds_defaults_to_30(tmp_path: Path):
    tool = make_tool(tmp_path)

    assert tool._resolve_timeout_seconds(None) == 30


def test_timeout_seconds_allows_maximum(tmp_path: Path):
    tool = make_tool(tmp_path)

    assert tool._resolve_timeout_seconds(300) == 300


@pytest.mark.parametrize("value", [0, -1, 301, "30", 1.5, True])
def test_timeout_seconds_rejects_invalid_values(tmp_path: Path, value):
    tool = make_tool(tmp_path)

    result = tool._resolve_timeout_seconds(value)

    assert result["success"] is False
    assert "between 1 and 300" in result["error"]
    assert result["invalid_timeout_seconds"] == value
    assert "maximum allowed value is 300s" in result["guidance"]


class SlowProcess:
    def __init__(self):
        self.stdout = io.StringIO("partial stdout")
        self.stderr = io.StringIO("partial stderr")
        self.returncode = None
        self.terminated = False
        self.killed = False

    def poll(self):
        return None

    def wait(self, timeout=None):
        if self.returncode is None:
            self.returncode = -15
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = -9


def test_execute_times_out_and_terminates_process_tree(tmp_path: Path, monkeypatch):
    tool = make_tool(tmp_path)
    proc = SlowProcess()
    terminated = {"called": False}

    monkeypatch.setattr(bash_module.subprocess, "Popen", lambda *args, **kwargs: proc)
    monkeypatch.setattr(bash_module.time, "monotonic", iter([0.0, 2.0]).__next__)
    monkeypatch.setattr(bash_module.time, "sleep", lambda _seconds: None)

    def fake_terminate_process_tree(process):
        terminated["called"] = True
        process.terminated = True
        process.returncode = -15

    monkeypatch.setattr(bash_module, "terminate_process_tree", fake_terminate_process_tree)

    result = tool.execute(command="slow-tool", timeout_seconds=1)

    assert result["success"] is False
    assert result["timed_out"] is True
    assert result["timeout_seconds"] == 1
    assert result["returncode"] == -15
    assert "partial stdout" in result["stdout"]
    assert "partial stderr" in result["stderr"]
    assert "avoid shell pipelines" in result["guidance"]
    assert terminated["called"] is True
    assert proc.terminated is True
