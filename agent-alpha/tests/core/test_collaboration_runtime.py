"""End-to-end supervision and tools with deterministic, model-free choices."""
import json
import os
from pathlib import Path
import threading
import time
from types import SimpleNamespace

import pytest

from agent.core import process_runtime
from agent.core.agent_runtime import AgentRuntime
from agent.core.tool_loader import ToolLoader
from agent.tools.write_tool import WriteTool
from agent.server import agent_manager as manager_module


class ScriptedLLM:
    profile = SimpleNamespace(provider="test")

    def set_interrupt_event(self, event):
        self.interrupted = event

    def generate_with_tools(self, messages, tools):
        names = {item["function"]["name"] for item in tools}
        is_parent = "subagent_create" in names
        last_user = max(index for index, item in enumerate(messages) if item["role"] == "user")
        following = messages[last_user + 1:]
        if "协作消息" in messages[last_user]["content"] and is_parent:
            content, calls = "子任务结果已收到", []
        elif any(item.get("tool_calls") for item in following):
            content, calls = ("已派发子任务" if is_parent else "文件写入完成"), []
        else:
            name = "subagent_create" if is_parent else "write"
            arguments = {"task_name": "write file", "message": "写入 shared.txt，然后汇报"} if is_parent else {"file_path": "shared.txt", "content": "child wrote this"}
            content = None
            calls = [SimpleNamespace(id="call1", type="function", function=SimpleNamespace(name=name, arguments=json.dumps(arguments)))]
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=calls), finish_reason="stop")])


class ScriptedRuntime(AgentRuntime):
    def __init__(self, **config):
        self.workspace_root = Path(config["workspace_root"])
        self.runtime_logs_dir = Path(config["logs_dir"])
        self.runtime_events_dir = Path(config["events_dir"])
        self.session_created_at = config.get("session_created_at")
        self.system_prompt = "test runtime"
        self.history = []
        self.runtime_events = []
        self.llm = ScriptedLLM()
        self.tool_loader = ToolLoader(enable_permissions=False, workspace_root=self.workspace_root)
        writer = WriteTool()
        self.tools = [writer.get_tool_definition()]
        self.tool_loader.tools = self.tools
        self.tool_loader.tool_executors["write"] = writer.execute
        self.context_manager = SimpleNamespace(should_compress=lambda history: False)
        self.max_turns = 10
        self._interrupted = threading.Event()


def scripted_worker(connection):
    import agent.core.agent_runtime as module
    from agent.core.execution_worker import run_worker
    module.AgentRuntime = ScriptedRuntime
    run_worker(connection)


@pytest.mark.skipif(os.name != "nt", reason="Windows process supervision")
def test_real_worker_delegates_edits_shared_file_and_wakes_parent(monkeypatch, tmp_path):
    monkeypatch.setattr(process_runtime, "run_worker", scripted_worker)
    monkeypatch.setattr(manager_module, "PROJECT_ROOT", tmp_path)
    manager = manager_module.AgentManager()
    root = manager.create_session(project_id="test", workspace=tmp_path)
    try:
        first = manager.start_chat(session_id=root.session_id, message="请创建子 agent 写文件。父会话独有的背景。")
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            with manager._lock:
                runs = list(manager._runs.values())
            parent_runs = [run for run in runs if run["session_id"] == root.session_id]
            if len(parent_runs) >= 2 and all(run["status"] == "success" for run in runs):
                break
            time.sleep(0.05)
        assert len(parent_runs) == 2, runs
        assert all(run["status"] == "success" for run in runs), runs
        assert (tmp_path / "shared.txt").read_text(encoding="utf-8") == "child wrote this"
        children = manager.collaboration.children(root.session_id)
        assert len(children) == 1
        child = children[0]
        assert "父会话独有的背景" not in str(child.runtime_history)
        assert child.metadata["agent_status"] == "idle"
        assert manager.get_run(first)["response"] == "已派发子任务"
        assert manager.store.load(root.session_id).runtime_history[-1]["content"] == "子任务结果已收到"
        assert not (tmp_path / "temp" / f"subagent-notes-{root.session_id[:16]}.md").exists()
        manager.release_all()
        manager._executor.shutdown(wait=True)

        manager = manager_module.AgentManager()
        assert not manager._runs  # Restart alone must not replay old work.
        restored = manager.store.load(child.session_id)
        assert restored.runtime_history == child.runtime_history
        receipt = manager.collaboration.deliver(root.session_id, child.session_id, "再次检查并汇报")
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            with manager._lock:
                restarted_runs = list(manager._runs.values())
            if len(restarted_runs) == 2 and all(run["status"] == "success" and not run.get("finalizing")
                                               for run in restarted_runs):
                break
            time.sleep(0.05)
        assert len(restarted_runs) == 2, restarted_runs
        assert all(run["status"] == "success" for run in restarted_runs), restarted_runs
        assert manager.get_run(receipt["request_id"])["session_id"] == child.session_id
        restored = manager.store.load(child.session_id)
        assert len(restored.runtime_history) > len(child.runtime_history)
        parent_history = manager.store.load(root.session_id).runtime_history
        assert sum("应用已重新启动" in (entry.get("content") or "") for entry in parent_history) == 1
    finally:
        manager.release_all()
        manager._executor.shutdown(wait=True)
