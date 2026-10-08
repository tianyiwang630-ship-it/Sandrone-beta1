from datetime import datetime, timedelta
import threading
from types import SimpleNamespace
import pytest

from agent.core.memory.service import MemoryConflict, MemoryService
from agent.core.memory.store import now


def reviewing(service, *, count=1, manual=True):
    task = {"id": "mem_" + "b" * 32, "created_at": now(), "manual": manual, "status": "reviewing",
            "turns": [{"id": "s:r", "session_id": "s", "request_id": "r"}], "prompt": "keep snapshot",
            "allowed_at_start": ["user", "memory", "references"], "operations": {}, "results": {},
            "proposals": [{"target": "user", "reason": "explicit", "source": "s:r"} for _ in range(count)],
            "reviewer_history": [], "organizer_history": [], "error": None,
            "document_revisions": {"user": service.document("user")["revision"]}}
    service.store.save_task(task)
    return task


def edit(service, task, index=0, content="stable preference", operation_id="write"):
    return service._memory_edit(task, role="reviewer", proposal_index=index, operation_id=operation_id,
                                target="user", operation="replace", content=content)


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("auto", [False, True])
def test_load_switch_does_not_disable_maintenance(tmp_path, enabled, auto):
    service = MemoryService(tmp_path)
    service.update_config({"enabled": enabled, "documents_auto_update": auto, "skills_auto_update": False})
    assert service.allowed(manual=True) == ["user", "memory", "references"]
    assert service.allowed(manual=False) == (["user", "memory"] if auto else [])
    task = reviewing(service)
    assert service._memory_read(task, role="reviewer", kind="document", target="user")["content"] == ""
    assert edit(service, task)["changed"]


@pytest.mark.parametrize("point", ["before_write", "after_write", "after_receipt"])
def test_interrupted_write_reconciles_once(tmp_path, monkeypatch, point):
    service = MemoryService(tmp_path)
    task = reviewing(service)
    original = service.store.save_document

    def interrupted(*args, **kwargs):
        if point == "after_write":
            original(*args, **kwargs)
        raise OSError("simulated process loss")

    if point != "after_receipt":
        monkeypatch.setattr(service.store, "save_document", interrupted)
        with pytest.raises(OSError):
            edit(service, task)
    else:
        edit(service, task)
    restored = MemoryService(tmp_path)
    pending = restored.store.task(task["id"])
    with restored._data_lock():
        restored._recover_operation(pending)
    result = edit(restored, pending, operation_id="model-regenerated-id")
    assert result["ok"]
    assert restored.document("user")["content"] == "stable preference"
    assert len(restored.versions("user")) == 1
    assert len(restored.store.task(task["id"])["results"]) == 1


def test_pending_write_never_overwrites_external_edit(tmp_path, monkeypatch):
    service = MemoryService(tmp_path)
    task = reviewing(service)
    monkeypatch.setattr(service.store, "save_document", lambda *a, **k: (_ for _ in ()).throw(OSError("before write")))
    with pytest.raises(OSError):
        edit(service, task)
    restored = MemoryService(tmp_path)
    restored.store.save_document("user", "new user content", source="manual")
    with pytest.raises(MemoryConflict):
        with restored._data_lock():
            restored._recover_operation(restored.store.task(task["id"]))
    assert restored.document("user")["content"] == "new user content"


def test_recovery_after_many_failures_keeps_original_batch(tmp_path, monkeypatch):
    service = MemoryService(tmp_path)
    task = reviewing(service)
    task.update(status="failed", failed_stage="reviewing", attempts=8, retryable=True,
                retry_after=(datetime.now().astimezone() - timedelta(seconds=1)).isoformat())
    service.store.save_task(task)
    service.update_config({"manual_prompt": "new prompt"})
    assert service.protected_sessions() == {"s"}
    with pytest.raises(RuntimeError, match="already running"):
        service.start_task(manual=True)

    def review(task_id, role, settings):
        saved = service.store.task(task_id)
        assert saved["prompt"] == "keep snapshot" and role == "reviewer"
        edit(service, saved)

    monkeypatch.setattr(service, "_run_role", review)
    service.resume()
    service._thread.join(3)
    final = service.store.task(task["id"])
    assert final["status"] == "completed" and final["attempts"] == 0
    assert not service.protected_sessions()


@pytest.mark.parametrize("action", ["unfinished", "skip", "same", "partial", "blocked"])
def test_results_are_complete_and_explain_no_write(tmp_path, monkeypatch, action):
    service = MemoryService(tmp_path)
    task = reviewing(service, count=2 if action == "partial" else 1, manual=action != "blocked")
    if action == "blocked":
        service.update_config({"documents_auto_update": False})

    def review(task_id, role, settings):
        saved = service.store.task(task_id)
        if action == "unfinished":
            return
        if action == "skip":
            service._memory_skip(saved, role=role, proposal_index=0, reason="temporary task instruction")
        else:
            edit(service, saved, content="" if action == "same" else "stable preference")
            if action == "partial":
                service._memory_skip(saved, role=role, proposal_index=1, reason="not enough evidence")

    monkeypatch.setattr(service, "_run_role", review)
    service._run(task["id"], {})
    final = service.store.task(task["id"])
    assert final["status"] == {"unfinished": "failed", "skip": "skipped", "same": "no_change",
                               "partial": "partial", "blocked": "skipped"}[action]
    if action == "unfinished":
        assert "s:r" not in service.store.progress()["completed_ids"]
    else:
        assert final["operation_count"] == (1 if action == "partial" else 0)
        assert len(service.task(task["id"])["results"]) == len(task["proposals"])


def test_failed_task_edit_cancellation_and_retry_backoff(tmp_path, monkeypatch):
    service = MemoryService(tmp_path)
    task = reviewing(service)
    task.update(status="failed", failed_stage="reviewing", retryable=True,
                retry_after=(datetime.now().astimezone() + timedelta(hours=1)).isoformat())
    service.store.save_task(task)
    monkeypatch.setattr(service, "_run_role", lambda *args: pytest.fail("must not run"))
    service.resume()
    assert service._thread is None
    session = service.begin_edit("user")
    service.save_document("user", "user wins", edit_id=session["id"], revision=session["revision"])
    service.resume()
    assert service.store.task(task["id"])["status"] == "cancelled"
    with pytest.raises(RuntimeError, match="cancelled"):
        edit(service, task)


def test_cleanup_failure_is_retried_without_running_model(tmp_path, monkeypatch):
    service = MemoryService(tmp_path)
    task = reviewing(service)
    service._memory_skip(task, role="reviewer", proposal_index=0, reason="no evidence")
    log = service.store.state / "logs" / f"{task['id']}.jsonl"
    log.parent.mkdir(parents=True)
    log.write_text("test", encoding="utf-8")
    original = type(log).unlink

    def locked(path, *args, **kwargs):
        if path == log:
            raise PermissionError("locked log")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(type(log), "unlink", locked)
    service._run(task["id"], {})
    assert service.store.task(task["id"])["cleanup_pending"]
    monkeypatch.setattr(type(log), "unlink", original)
    service.resume()
    assert not log.exists()
    assert not service.store.task(task["id"]).get("cleanup_pending")


@pytest.mark.parametrize("stage", ["organizing", "reviewing", "committing"])
def test_shutdown_resumes_saved_stage_without_repeating_work(tmp_path, monkeypatch, stage):
    service = MemoryService(tmp_path)
    task = reviewing(service)
    task["status"] = stage
    if stage == "committing":
        task["proposals"] = []
    service.store.save_task(task)
    service._closing = True
    service.close()
    restored = MemoryService(tmp_path)
    calls = []

    def review(task_id, role, settings):
        calls.append(role)
        edit(restored, restored.store.task(task_id))

    monkeypatch.setattr(restored, "_run_role", review)
    restored.resume()
    restored._thread.join(3)
    assert restored.store.task(task["id"])["status"] in {"completed", "no_change"}
    assert calls == ([] if stage == "committing" else ["reviewer"])


def test_stalled_worker_is_stopped_and_becomes_retryable(tmp_path, monkeypatch):
    import agent.core.memory.service as module
    service = MemoryService(tmp_path)
    task = reviewing(service)
    stopped = threading.Event()

    class StalledRuntime:
        def __init__(self, **kwargs):
            self.history = []

        def interrupt(self):
            stopped.set()

        def handle(self, request):
            assert stopped.wait(3)
            return SimpleNamespace(metadata={"interrupted": True})

        def close(self):
            pass

    monkeypatch.setattr(module, "ProcessRuntime", StalledRuntime)
    monkeypatch.setattr(service, "STALL_SECONDS", 0)
    service._run(task["id"], {})
    result = service.store.task(task["id"])
    assert result["status"] == "failed" and result["retryable"]
    assert "progress" in result["error"]


def test_manual_retry_and_abandon_preserve_unprocessed_progress(tmp_path, monkeypatch):
    service = MemoryService(tmp_path)
    task = reviewing(service)
    task.update(status="failed", failed_stage="reviewing", retryable=False, retry_after=now())
    service.store.save_task(task)
    monkeypatch.setattr(service, "_run_role", lambda *args: None)
    service.control_task(task["id"], action="retry")
    service._thread.join(3)
    assert service.store.task(task["id"])["status"] == "failed"
    service.control_task(task["id"], action="cancel")
    service.resume()
    assert service.store.task(task["id"])["status"] == "cancelled"
    assert not service.store.progress()["completed_ids"]


def test_lost_receipt_does_not_reapply_older_document_operation(tmp_path):
    service = MemoryService(tmp_path)
    task = reviewing(service, count=2)
    edit(service, task, content="first version", operation_id="first")
    edit(service, task, index=1, content="second version", operation_id="second")
    edit(service, task, operation_id="different-id", content="first version")
    assert service.document("user")["content"] == "second version"
    assert len(service.versions("user")) == 1


def test_missing_log_cannot_be_reported_as_success(tmp_path, monkeypatch):
    service = MemoryService(tmp_path)
    task = reviewing(service, manual=False)

    def review(task_id, role, settings):
        saved = service.store.task(task_id)
        with pytest.raises(ValueError, match="missing"):
            service._memory_read(saved, role=role, kind="turn", index=0)
        service._memory_skip(saved, role=role, proposal_index=0, reason="missing original evidence")

    monkeypatch.setattr(service, "_run_role", review)
    service._run(task["id"], {})
    result = service.store.task(task["id"])
    assert result["status"] == "failed" and not result["retryable"]
    assert not service.store.progress()["completed_ids"]


def test_cancelled_pending_operation_cannot_write_even_with_stale_task(tmp_path, monkeypatch):
    service = MemoryService(tmp_path)
    task = reviewing(service)
    monkeypatch.setattr(service.store, "save_document", lambda *a, **k: (_ for _ in ()).throw(OSError("before write")))
    with pytest.raises(OSError):
        edit(service, task)
    restored = MemoryService(tmp_path)
    stale = restored.store.task(task["id"])
    cancelled = restored.store.task(task["id"])
    cancelled["status"] = "cancelled"
    restored.store.save_task(cancelled)
    with pytest.raises(RuntimeError, match="cancelled"):
        with restored._data_lock():
            restored._recover_operation(stale)
    assert restored.document("user")["content"] == ""
