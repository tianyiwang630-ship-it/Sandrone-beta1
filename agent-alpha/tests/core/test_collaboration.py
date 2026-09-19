import threading
import time
from types import SimpleNamespace

import pytest

from agent.core.collaboration import Collaboration
from agent.core.session_store import SessionRecord, SessionStore
from agent.server.agent_manager import AgentManager


@pytest.fixture
def manager(tmp_path):
    manager = AgentManager.__new__(AgentManager)
    manager.store = SessionStore(tmp_path / "sessions")
    manager.events_dir = tmp_path / "events"
    manager.logs_dir = tmp_path / "logs"
    manager._lock = threading.RLock()
    manager._runs = {}
    manager._agents = {}
    manager._closing = False
    manager._executor = SimpleNamespace(submit=lambda *args: None)
    manager.store.save(SessionRecord(session_id="root", workspace=str(tmp_path),
                                     history=[{"role": "user", "content": "parent private history"}],
                                     metadata={"project_id": "project", "title": "Root"}))
    manager.collaboration = Collaboration(manager)
    return manager


def create(manager, name="work"):
    return manager.collaboration.create("root", name, "独立执行任务")


@pytest.mark.parametrize("fails", [False, True])
def test_input_during_compaction_runs_after_compaction(manager, fails):
    child = create(manager)
    record = manager.store.load("root")
    request_id = manager.start_compact(session_id="root")
    agent = SimpleNamespace(history=record.history, runtime_events=[], is_interrupted=lambda: False)

    def compact_history(**kwargs):
        manager.collaboration.deliver(child["agent_id"], "root", "压缩期间送达的结果")
        assert len([r for r in manager._runs.values() if r["session_id"] == "root"]) == 1
        agent.checkpoint_handler(agent.history)
        if fails:
            raise RuntimeError("compression failed")
        return SimpleNamespace(success=True, skipped=True, fallback=False,
                               to_event=lambda: {"type": "context_compacted", "success": True})

    agent.compact_history = compact_history
    manager._get_agent = lambda *args: agent
    manager._run_compact(request_id, record, "ask", {})
    assert manager._runs[request_id]["status"] == ("failed" if fails else "success")
    next_runs = [r for r in manager._runs.values()
                 if r["session_id"] == "root" and r["request_id"] != request_id]
    assert len(next_runs) == 1
    assert next_runs[0]["status"] == "running"
    mailbox = manager.store.load("root").metadata["mailbox"]
    assert mailbox[0]["run_id"] == next_runs[0]["request_id"]
    assert mailbox[0]["state"] == "reserved"


def test_input_after_result_waits_for_previous_finalization(manager):
    request_id = manager.start_chat(session_id="root", message="开始")
    manager._set_run(request_id, status="success", response="完成")
    receipt = manager.collaboration.deliver(None, "root", "下一条")
    assert receipt["request_id"] == request_id
    assert len(manager._runs) == 1
    assert manager.store.load("root").metadata["mailbox"][0]["state"] == "pending"
    manager.collaboration.finish("root", request_id)
    assert len(manager._runs) == 2
    assert not manager._runs[request_id]["finalizing"]
    assert manager.store.load("root").metadata["mailbox"][0]["state"] == "reserved"


def test_ten_active_children_no_history_inheritance_and_list_pagination(manager):
    children = [create(manager) for _ in range(10)]
    with pytest.raises(ValueError, match="10"):
        create(manager)
    child = children[0]
    record = manager.store.load(child["agent_id"])
    assert "parent private history" not in str(record.history)
    assert record.workspace == manager.store.load("root").workspace
    with pytest.raises(ValueError, match="cannot create"):
        manager.collaboration.create(child["agent_id"], "nested", "no")
    manager._runs[child["request_id"]]["status"] = "success"
    create(manager, "eleventh record")
    page = manager.collaboration.call("root", "unused", "list", {})
    assert len(page["agents"]) == 10
    assert page["next_offset"] == 10
    assert all(item["status"] == "running" for item in page["agents"])
    older = manager.collaboration.call("root", "unused", "list", {"offset": 10})
    assert older["agents"][0]["agent_id"] == child["agent_id"]


def test_concurrent_user_and_child_input_start_only_one_main_run(manager):
    child = create(manager)
    barrier = threading.Barrier(3)
    errors = []

    def deliver(sender, content):
        try:
            barrier.wait()
            manager.collaboration.deliver(sender, "root", content)
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=deliver, args=(None, "用户问题")),
               threading.Thread(target=deliver, args=(child["agent_id"], "子任务问题"))]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(timeout=3)
    assert not errors
    root_runs = [run for run in manager._runs.values() if run["session_id"] == "root"]
    assert len(root_runs) == 1
    inbox = manager.store.load("root").metadata["mailbox"]
    assert len(inbox) == 2
    entries = manager.collaboration.take_inputs("root", root_runs[0]["request_id"])
    assert len(entries) == 1
    assert {item["state"] for item in manager.store.load("root").metadata["mailbox"]} == {"reserved"}
    initial = next(item for item in inbox if item["state"] == "reserved")
    history = [manager.collaboration.entry(initial), *entries]
    manager._save_live_checkpoint("root", root_runs[0]["request_id"], history)
    assert {item["state"] for item in manager.store.load("root").metadata["mailbox"]} == {"delivered"}


def test_completion_wakes_main_and_late_input_survives_finish(manager):
    child = create(manager)
    manager._runs[child["request_id"]].update(status="success", response="验证通过")
    manager.collaboration.finish(child["agent_id"], child["request_id"])
    main = manager.get_active_run_for_session("root")
    assert main is not None
    manager.collaboration.deliver(None, "root", "临近结束的新问题")
    manager._runs[main["request_id"]]["status"] = "success"
    manager.collaboration.finish("root", main["request_id"])
    next_run = manager.get_active_run_for_session("root")
    assert next_run["request_id"] != main["request_id"]
    assert manager.store.load("root").metadata["mailbox"][-1]["state"] == "reserved"


def test_restart_does_not_execute_and_notice_only_for_parent(manager):
    child = create(manager)
    manager._runs.clear()
    manager.store.save(SessionRecord(session_id="plain", workspace=manager.store.load("root").workspace,
                                     metadata={"project_id": "project"}))
    manager.collaboration = Collaboration(manager)
    assert not manager._runs
    assert manager.store.load(child["agent_id"]).metadata["agent_status"] == "interrupted"
    manager.start_chat(session_id="root", message="继续聊天")
    history = manager.store.load("root").runtime_history
    assert sum("应用已重新启动" in entry["content"] for entry in history) == 1
    manager.start_chat(session_id="plain", message="你好")
    assert "应用已重新启动" not in str(manager.store.load("plain").runtime_history)


def test_scope_and_rename_do_not_change_task(manager):
    child = create(manager)
    before = manager.store.load(child["agent_id"])
    run_id = manager.start_chat(session_id="root", message="改名")
    manager.collaboration.call("root", run_id, "rename", {"target_id": child["agent_id"], "task_name": "new label"})
    after = manager.store.load(child["agent_id"])
    assert after.history == before.history
    assert after.metadata["mailbox"] == before.metadata["mailbox"]
    manager.store.save(SessionRecord(session_id="other", metadata={"project_id": "project"}))
    with pytest.raises(ValueError, match="outside"):
        manager.collaboration.deliver(child["agent_id"], "other", "no")


def test_sibling_reply_reaches_sender_and_parent_with_correlation(manager):
    sender, receiver = create(manager, "sender"), create(manager, "receiver")
    receipt = manager.collaboration.deliver(sender["agent_id"], receiver["agent_id"], "请确认接口")
    entries = manager.collaboration.take_inputs(receiver["agent_id"], receiver["request_id"])
    manager._save_live_checkpoint(receiver["agent_id"], receiver["request_id"], entries)
    manager._runs[receiver["request_id"]].update(status="success", response="接口已确认")
    manager.collaboration.finish(receiver["agent_id"], receiver["request_id"])
    for target_id in ("root", sender["agent_id"]):
        inbox = manager.store.load(target_id).metadata["mailbox"]
        answer = next(item for item in inbox if item["sender_id"] == receiver["agent_id"])
        assert "接口已确认" in answer["content"]
        assert receipt["message_id"] in answer["reply_to"]


def test_wait_returns_on_one_completion_and_timeout_never_stops_others(manager):
    first, second = create(manager), create(manager)
    run_id = manager.start_chat(session_id="root", message="等待验证")
    targets = [first["agent_id"], second["agent_id"]]
    result = manager.collaboration.wait("root", run_id, targets, timeout_seconds=0)
    assert result["timed_out"]
    assert all(manager._runs[child["request_id"]]["status"] == "running" for child in (first, second))
    manager._runs[first["request_id"]].update(status="success", response="验证完成")
    manager.collaboration.finish(first["agent_id"], first["request_id"])
    result = manager.collaboration.wait("root", run_id, targets, timeout_seconds=0)
    assert not result["timed_out"]
    assert manager._runs[second["request_id"]]["status"] == "running"


def test_user_steering_wakes_wait_and_queue_does_not_steer(manager):
    child = create(manager)
    run_id = manager.start_chat(session_id="root", message="main task")
    manager.submit_chat(session_id="root", message="later", mode="queue")
    assert manager.collaboration.take_inputs("root", run_id) == []
    results = []
    thread = threading.Thread(target=lambda: results.append(manager.collaboration.wait(
        "root", run_id, [child["agent_id"]], timeout_seconds=5,
    )))
    thread.start()
    deadline = time.monotonic() + 2
    while manager.store.load("root").metadata.get("agent_status") != "waiting" and time.monotonic() < deadline:
        time.sleep(0.01)
    manager.submit_chat(session_id="root", message="answer this now", mode="steer")
    thread.join(timeout=2)
    assert not thread.is_alive()
    assert results[0]["new_input"] is True
    assert results[0]["timed_out"] is False
    entries = manager.collaboration.take_inputs("root", run_id)
    assert [entry["content"] for entry in entries] == ["answer this now"]


def test_stop_does_not_close_new_run_received_during_cleanup(manager):
    child = create(manager)
    child_id, old_run = child["agent_id"], child["request_id"]

    def close():
        manager._runs[old_run]["status"] = "interrupted"
        manager.collaboration.finish(child_id, old_run)
        manager.collaboration.deliver("root", child_id, "收尾期间的新任务")
        assert not any(r["session_id"] == child_id and r["status"] == "running"
                       for r in manager._runs.values())

    manager._agents[child_id] = SimpleNamespace(
        interrupt=lambda: None, close=close, clear_interrupt=lambda: None,
    )
    manager.collaboration.stop("root", child_id)
    active = manager.get_active_run_for_session(child_id)
    assert active is not None
    assert active["request_id"] != old_run
    assert manager.store.load(child_id).metadata["mailbox"][-1]["run_id"] == active["request_id"]


def test_shutdown_during_runtime_construction_does_not_register_worker(manager, monkeypatch):
    def construct(**kwargs):
        manager.release_all()
        return SimpleNamespace(llm=SimpleNamespace(), tool_loader=SimpleNamespace(permission_manager=None))

    monkeypatch.setattr("agent.server.agent_manager.AgentRuntime", construct)
    with pytest.raises(RuntimeError, match="shutting down"):
        manager._get_agent(manager.store.load("root"), "ask", {})
    assert manager._agents == {}


@pytest.mark.parametrize("action", ["create", "message", "rename", "stop", "wait"])
def test_late_rpc_cannot_change_state_after_old_run_stops(manager, action):
    child = create(manager)
    old = manager.start_chat(session_id="root", message="旧任务")
    manager._runs[old]["status"] = "interrupted"
    new = manager.start_chat(session_id="root", message="新任务")
    before = manager.store.load(child["agent_id"]).to_dict()
    arguments = {
        "create": {"task_name": "late", "message": "不应创建"},
        "message": {"target_id": child["agent_id"], "message": "不应投递"},
        "rename": {"target_id": child["agent_id"], "task_name": "不应改名"},
        "stop": {"target_id": child["agent_id"]},
        "wait": {"target_ids": [child["agent_id"]], "timeout_seconds": 0},
    }
    with pytest.raises(RuntimeError, match="no longer running"):
        manager.collaboration.call("root", old, action, arguments[action])
    assert manager.store.load(child["agent_id"]).to_dict() == before
    assert len(manager.collaboration.children("root")) == 1
    assert manager._runs[new]["status"] == "running"


def test_release_failure_keeps_runtime_available_for_cleanup_retry(manager):
    def close():
        raise TimeoutError("still stopping")

    agent = SimpleNamespace(close=close)
    manager._agents["root"] = agent
    with pytest.raises(TimeoutError):
        manager.release("root")
    assert manager._agents["root"] is agent
    agent.close = lambda: None
    manager.release("root")
    assert "root" not in manager._agents


def test_successful_stop_retry_releases_failed_slot_and_keeps_identity(manager):
    child = create(manager)
    target_id, request_id = child["agent_id"], child["request_id"]
    manager._runs[request_id].update(status="stop_failed", error="old cleanup failure")
    record = manager.store.load(target_id)
    record.metadata["agent_status"] = "stop_failed"
    manager.store.save(record)
    manager._agents[target_id] = SimpleNamespace(interrupt=lambda: None, close=lambda: None,
                                                clear_interrupt=lambda: None)
    result = manager.collaboration.stop("root", target_id)
    assert result["status"] == "interrupted"
    assert manager.get_active_run_for_session(target_id) is None
    next_message = manager.collaboration.deliver("root", target_id, "继续")
    assert next_message["request_id"] != request_id
    assert manager._runs[next_message["request_id"]]["status"] == "running"


def test_stop_retry_freed_slot_starts_an_older_queued_child(manager):
    older = create(manager, "older")
    manager._runs[older["request_id"]]["status"] = "success"
    active = [create(manager) for _ in range(10)]
    receipt = manager.collaboration.deliver("root", older["agent_id"], "再次执行")
    assert receipt["request_id"] is None
    assert manager.store.load(older["agent_id"]).metadata["agent_status"] == "queued"
    stopped = active[0]
    manager._runs[stopped["request_id"]]["status"] = "stop_failed"
    manager._agents[stopped["agent_id"]] = SimpleNamespace(interrupt=lambda: None, close=lambda: None)
    manager.collaboration.stop("root", stopped["agent_id"])
    resumed = manager.get_active_run_for_session(older["agent_id"])
    assert resumed is not None
    assert resumed["request_id"] != older["request_id"]
    assert manager.collaboration._active_count("root") == 10


@pytest.mark.parametrize("delete", [False, True])
def test_retire_root_stops_children_and_drains_late_writes(manager, delete):
    from concurrent.futures import ThreadPoolExecutor

    child = create(manager)
    child_id, run_id = child["agent_id"], child["request_id"]
    stale = manager.store.load(child_id)
    release_writer = threading.Event()

    def late_write():
        assert release_writer.wait(3)
        with pytest.raises(ValueError, match="not found"):
            manager.collaboration.deliver(child_id, "root", "迟到的结果")
        manager._save_run_record(stale)
        manager._runs[run_id]["status"] = "interrupted"
        manager.collaboration.finish(child_id, run_id)
        manager.events_dir.mkdir(parents=True, exist_ok=True)
        (manager.events_dir / f"{child_id}.jsonl").write_text("late log", encoding="utf-8")

    manager._agents[child_id] = SimpleNamespace(interrupt=lambda: None, close=release_writer.set)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(late_write)
        manager._futures[run_id] = future
        if delete:
            assert manager.delete_session("root")
        else:
            manager.update_session("root", {"is_archived": True})
        future.result(timeout=1)
    assert manager.get_session("root") is None
    assert manager.get_session(child_id) is None
    assert not manager._agents
    assert manager.collaboration.children("root") == []
    if delete:
        assert manager.store.load("root") is None
        assert manager.store.load(child_id) is None
        assert not (manager.events_dir / f"{child_id}.jsonl").exists()
    else:
        assert manager.store.load(child_id).metadata["is_archived"]
