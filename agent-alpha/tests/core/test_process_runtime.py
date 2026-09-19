import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from agent.core import process_runtime
from agent.core.process_runtime import ProcessRuntime
from agent.core.runtime_types import RuntimeRequest, RuntimeResponse


pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows process supervisor")


class ProbeRuntime:
    def __init__(self, **config):
        self.history = []
        self.runtime_events = []
        self.llm = SimpleNamespace(stream_responses=False)
        self.tool_loader = SimpleNamespace(permission_manager=None)

    def interrupt(self):
        pass  # Deliberately ignore cooperative cancellation.

    def handle(self, request):
        self.history.append({"role": "user", "content": request.content})
        if request.content == "hang":
            child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                                     creationflags=subprocess.CREATE_NO_WINDOW)
            self.history.append({"role": "assistant", "content": str(child.pid)})
            self.checkpoint(self.history)
            time.sleep(60)
        elif request.content == "steer":
            self.checkpoint(self.history)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                entries = self.input_provider()
                if entries:
                    self.history.extend(entries)
                    break
                time.sleep(0.01)
        self.history.append({"role": "assistant", "content": "done"})
        return RuntimeResponse(content="done", session_id=request.session_id)


def probe_worker(connection):
    # Exercise the real IPC endpoint with a deterministic model-free runtime.
    import agent.core.agent_runtime as module
    from agent.core.execution_worker import run_worker
    module.AgentRuntime = ProbeRuntime
    run_worker(connection)


def run_async(runtime, content):
    result = []
    errors = []

    def run():
        try:
            result.append(runtime.handle(RuntimeRequest(content=content, session_id="test")))
        except Exception as exc:
            errors.append(exc)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread, result, errors


@pytest.mark.parametrize("blocked_control_pipe", [False, True])
def test_force_stop_then_reconstruct_and_steer(monkeypatch, tmp_path, blocked_control_pipe):
    monkeypatch.setattr(process_runtime, "run_worker", probe_worker)
    runtime = ProcessRuntime(workspace_root=str(tmp_path))
    saved = threading.Event()
    snapshots = []

    def checkpoint(history):
        snapshots.append([dict(entry) for entry in history])
        saved.set()

    runtime.checkpoint_handler = checkpoint
    try:
        thread, results, errors = run_async(runtime, "hang")
        assert saved.wait(10)
        assert runtime._job.active_processes >= 2
        old_job = runtime._job
        started = time.monotonic()
        if blocked_control_pipe:
            runtime._send_lock.acquire()
        try:
            cancellation = threading.Thread(target=runtime.interrupt, daemon=True)
            cancellation.start()
            cancellation.join(timeout=1)
            assert not cancellation.is_alive(), "stop must not wait for the control pipe"
            thread.join(timeout=4)
        finally:
            if blocked_control_pipe:
                runtime._send_lock.release()
        assert not thread.is_alive()
        assert not errors
        assert results[0].metadata["interrupted"]
        assert time.monotonic() - started < 3
        assert old_job._handle is None
        assert snapshots[-1][-1]["content"].isdigit()
        assert runtime._process is None

        runtime.clear_interrupt()
        saved.clear()
        thread, results, errors = run_async(runtime, "steer")
        assert saved.wait(10)
        assert runtime.steer({"role": "user", "content": "new direction"})
        thread.join(timeout=10)
        assert not thread.is_alive()
        assert not errors
        assert results[0].content == "done"
        assert any(entry["content"] == "new direction" for entry in runtime.history)
        assert any(entry["content"] == "hang" for entry in runtime.history)
    finally:
        runtime.close()


def test_interrupt_before_start_does_not_create_worker(tmp_path):
    runtime = ProcessRuntime(workspace_root=str(tmp_path))
    runtime.interrupt()
    response = runtime.handle(RuntimeRequest(content="never run", session_id="test"))
    assert response.metadata["interrupted"]
    assert runtime._process is None
