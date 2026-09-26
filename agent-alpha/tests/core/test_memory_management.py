from __future__ import annotations

from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest

from agent.core.memory.service import MemoryService
from agent.core.memory.sources import available_turns, read_turn
from agent.core.memory.store import MemoryStore
from agent.core.realtime_log import RealtimeLogWriter
from agent.core.session_store import SessionKind, SessionRecord, SessionStore


class MemoryScriptedLLM:
    profile = SimpleNamespace(provider="test")

    def set_interrupt_event(self, event):
        self.interrupted = event

    def generate_with_tools(self, messages, tools):
        role = "organizer" if any(item["function"]["name"] == "memory_submit" for item in tools) else "reviewer"
        call_count = sum(bool(item.get("tool_calls")) for item in messages)
        if role == "organizer":
            steps = [("memory_read", {"kind": "turns"}),
                     ("memory_read", {"kind": "turn", "index": 0}),
                     ("memory_submit", {"proposals": [{"target": "user", "source": "s1:r1", "reason": "explicit preference"}]})]
        else:
            steps = [("memory_read", {"kind": "proposals"}),
                     ("memory_edit", {"proposal_index": 0, "operation_id": "write-user", "target": "user",
                                      "operation": "replace", "content": "用户偏好中文回答"})]
        if call_count < len(steps):
            name, args = steps[call_count]
            calls = [SimpleNamespace(id=f"call{call_count}", type="function",
                                     function=SimpleNamespace(name=name, arguments=json.dumps(args)))]
            content = None
        else:
            calls, content = [], "完成"
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=calls),
                                                       finish_reason="stop")])


def scripted_memory_worker(connection):
    from agent.core.execution_worker import run_worker
    from agent.core.agent_runtime import AgentRuntime
    from agent.core.tool_loader import ToolLoader
    import agent.core.agent_runtime as module

    class ScriptedRuntime(AgentRuntime):
        def __init__(self, **config):
            self.workspace_root = Path(config["workspace_root"])
            self.runtime_logs_dir = Path(config["logs_dir"])
            self.runtime_events_dir = Path(config["events_dir"])
            self.session_created_at = None
            self.role_config = config["role_config"]
            self.system_prompt = "memory test"
            self.history = []
            self.runtime_events = []
            self.llm = MemoryScriptedLLM()
            self.tool_loader = ToolLoader(enable_permissions=False, workspace_root=self.workspace_root)
            self.tools = []
            self.context_manager = SimpleNamespace(should_compress=lambda history: False, tools=[])
            self.max_turns = 10
            self._interrupted = threading.Event()

    module.AgentRuntime = ScriptedRuntime
    run_worker(connection)


def make_turn(root, session_id="s1", request_id="r1", *, content="用户明确说中文回答"):
    sessions = SessionStore(root / "session-log" / "sessions")
    sessions.save(SessionRecord(session_id=session_id, kind=SessionKind.INTERACTIVE))
    writer = RealtimeLogWriter(root / "session-log" / "logs", session_id)
    writer.write_entry({"role": "user", "content": content}, request_id=request_id)
    writer.write_entry({"role": "assistant", "content": "好的"}, request_id=request_id)
    writer.write_event("run_finished", {"interrupted": False, "recoverable": False}, request_id=request_id)
    writer.commit_cycle()


def test_document_versions_restore_limits_and_persistent_settings(tmp_path):
    service = MemoryService(tmp_path)
    assert service.config()["enabled"] and service.config()["skills_auto_update"]
    service.update_config({"auto_prompt": "重点记录偏好", "manual_prompt": "检查旧记录"})
    session = service.begin_edit("user")
    with pytest.raises(ValueError):
        service.save_document("user", "🙂" * 501, edit_id=session["id"], revision=session["revision"])
    first = service.save_document("user", "中文", edit_id=session["id"], revision=session["revision"])
    assert first["length"] == 2
    second_edit = service.begin_edit("user")
    service.save_document("user", "英文", edit_id=second_edit["id"], revision=second_edit["revision"])
    version = service.versions("user")[0]
    assert service.version("user", version["id"])["content"] == "中文"
    restore_edit = service.begin_edit("user")
    service.restore("user", version["id"], edit_id=restore_edit["id"], revision=restore_edit["revision"])
    assert service.document("user")["content"] == "中文"
    assert MemoryService(tmp_path).config()["manual_prompt"] == "检查旧记录"


def test_log_range_and_real_user_filter(tmp_path):
    make_turn(tmp_path)
    writer = RealtimeLogWriter(tmp_path / "session-log" / "logs", "s1")
    writer.write_entry({"role": "user", "content": "子 agent 消息", "source_agent_id": "sub"}, request_id="r2")
    writer.write_event("run_finished", {}, request_id="r2")
    writer.commit_cycle()
    selected = available_turns(tmp_path)
    assert [turn["id"] for turn in selected] == ["s1:r1"]
    first = read_turn(tmp_path, selected[0], limit=8)
    assert first["next_offset"] is not None
    second = read_turn(tmp_path, selected[0], offset=first["next_offset"], limit=20000)
    assert "用户明确说中文回答" in first["content"] + second["content"]
    assert available_turns(tmp_path, start=(datetime.now().astimezone() + timedelta(days=1)).isoformat()) == []


def test_prompt_snapshot_switches_and_cancelled_late_write(tmp_path, monkeypatch):
    make_turn(tmp_path)
    service = MemoryService(tmp_path)
    service.update_config({"manual_prompt": "本次要求", "documents_auto_update": False})
    monkeypatch.setattr(service, "_run_role", lambda *args, **kwargs: None)
    task = service.start_task(manual=True)
    if service._thread:
        service._thread.join(timeout=2)
    saved = service.store.task(task["id"])
    assert saved["prompt"] == "本次要求"
    assert saved["status"] == "failed"  # Organizer must submit a proposal or 'no change'.
    service.update_config({"manual_prompt": "下次要求", "enabled": False})
    assert service.allowed(manual=True) == ["references"]
    assert service.store.task(task["id"])["prompt"] == "本次要求"


def test_manual_target_selection_is_enforced_at_review_write(tmp_path, monkeypatch):
    make_turn(tmp_path)
    service = MemoryService(tmp_path)
    monkeypatch.setattr(service, "_run_role", lambda *args, **kwargs: None)
    with pytest.raises(ValueError, match="Invalid manual update targets"):
        service.start_task(manual=True, targets=[])
    task = service.start_task(manual=True, targets=["references"])
    service._thread.join(timeout=2)
    saved = service.store.task(task["id"])
    assert saved["allowed_at_start"] == ["references"]
    saved["status"] = "reviewing"
    saved["proposals"] = [{"target": "user", "source": "s1:r1", "reason": "test"}]
    service.store.save_task(saved)
    result = service._memory_rpc(task["id"], "reviewer", "memory_tool", {
        "name": "memory_edit", "arguments": {"proposal_index": 0, "operation_id": "forbidden",
                                            "target": "user", "operation": "replace", "content": "不应写入"}})
    assert result == {"ok": False, "reason": "This update target is disabled"}
    assert service.document("user")["content"] == ""


def test_reviewer_cannot_create_unproposed_target_or_write_disabled_document(tmp_path):
    service = MemoryService(tmp_path)
    task = {"id": "mem_" + "a" * 32, "manual": False, "status": "reviewing",
                "proposals": [{"target": "user", "source": "s1:r1", "reason": "explicit"}],
                "operations": {}, "allowed_at_start": ["user", "memory", "references"]}
    service.update_config({"documents_auto_update": False})
    service.store.save_task(task)
    rejected = service._memory_edit(task, role="reviewer", proposal_index=0,
                                    operation_id="once", target="user", operation="replace", content="记忆")
    assert rejected["ok"] is False
    assert service.document("user")["content"] == ""
    with pytest.raises(ValueError):
        service._memory_edit(task, role="reviewer", proposal_index=0,
                             operation_id="another", target="memory", operation="replace", content="错误")


@pytest.mark.skipif(os.name != "nt", reason="Windows process supervision")
def test_real_memory_worker_tool_round_trip(monkeypatch, tmp_path):
    import agent.core.process_runtime as process_runtime

    make_turn(tmp_path)
    monkeypatch.setattr(process_runtime, "run_worker", scripted_memory_worker)
    service = MemoryService(tmp_path)
    task = service.start_task(manual=True)
    service._thread.join(timeout=20)
    assert not service._thread.is_alive()
    assert service.store.task(task["id"])["status"] == "completed", service.store.task(task["id"])["error"]
    assert service.document("user")["content"] == "用户偏好中文回答"


def test_first_automatic_batch_waits_for_new_turns_and_includes_old_history(tmp_path, monkeypatch):
    make_turn(tmp_path, request_id="old")
    service = MemoryService(tmp_path)
    progress = service.store.progress()
    progress["initialized_at"] = (datetime.now().astimezone() - timedelta(days=2)).isoformat()
    service.store.save_progress(progress)

    def no_change(task_id, role, settings):
        assert role == "organizer"
        task = service.store.task(task_id)
        service._memory_submit(task, role=role, proposals=[])

    monkeypatch.setattr(service, "_run_role", no_change)
    for number in range(19):
        request_id = f"new{number}"
        make_turn(tmp_path, request_id=request_id)
        service.note_completed_turn("s1", request_id)
    assert service.maybe_start_auto() is None
    make_turn(tmp_path, request_id="new19")
    service.note_completed_turn("s1", "new19")
    started = service.maybe_start_auto()
    assert started is not None
    service._thread.join(timeout=3)
    assert service.store.task(started["id"])["status"] == "no_change"
    assert len(service.store.progress()["completed_ids"]) == 21


def test_nested_skill_reference_scope_and_capacity(tmp_path, monkeypatch):
    import agent.core.memory.service as service_module

    monkeypatch.setattr(service_module, "APP_ROOT", tmp_path)
    skill_root = tmp_path / "skills" / "demo"
    (skill_root / "references" / "sub").mkdir(parents=True)
    (skill_root / "SKILL.md").write_text("---\nname: demo\ndescription: Example\n---\nBody", encoding="utf-8")
    (skill_root / "references" / "sub" / "a.md").write_text("old", encoding="utf-8")
    service = MemoryService(tmp_path)
    task = {"id": "mem_" + "b" * 32, "manual": True, "status": "reviewing",
            "proposals": [{"target": "references", "skill": "demo", "path": "sub/a.md",
                           "source": "s1:r1", "reason": "verified"}], "operations": {},
            "allowed_at_start": ["references"]}
    service.store.save_task(task)
    result = service._memory_edit(task, role="reviewer", proposal_index=0, operation_id="one",
                                  target="references", operation="replace", skill="demo", path="sub/a.md", content="new")
    assert result["ok"]
    assert (skill_root / "references" / "sub" / "a.md").read_text(encoding="utf-8") == "new"
    with pytest.raises(ValueError):
        service._skill_path("demo", "../SKILL.md")
    with pytest.raises(ValueError):
        service._skill_path("demo", "sub/../sub/a.md")


def test_edit_cancels_active_task_and_rejects_late_write(tmp_path, monkeypatch):
    make_turn(tmp_path)
    service = MemoryService(tmp_path)
    entered = threading.Event()
    release = threading.Event()

    def waiting_role(*args):
        entered.set()
        assert release.wait(5)

    monkeypatch.setattr(service, "_run_role", waiting_role)
    started = service.start_task(manual=True)
    assert entered.wait(3)
    with pytest.raises(RuntimeError, match="already running"):
        service.start_task(manual=True)
    edit = service.begin_edit("user")
    assert service.store.task(started["id"])["status"] == "cancelled"
    with pytest.raises(RuntimeError, match="no longer active"):
        service._memory_rpc(started["id"], "organizer", "memory_tool",
                            {"name": "memory_read", "arguments": {"kind": "turns"}})
    saved = service.save_document("user", "手动优先", edit_id=edit["id"], revision=edit["revision"])
    release.set()
    service._thread.join(timeout=3)
    assert saved["content"] == service.document("user")["content"]
    assert service.store.task(started["id"])["status"] == "cancelled"
