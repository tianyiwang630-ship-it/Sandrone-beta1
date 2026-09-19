"""Supervisor-side runtime facade; model and tools only run in an owned process."""
from __future__ import annotations

from dataclasses import asdict
import multiprocessing
from pathlib import Path
import threading
import time
from types import SimpleNamespace
import uuid

from agent.core.execution_worker import run_worker
from agent.core.message_pipeline import prepare_runtime_history
from agent.core.runtime_types import RuntimeRequest, RuntimeResponse
from agent.core.windows_job import WindowsJob


class _PermissionRelay:
    def __init__(self):
        self.mode = "ask"
        self.handler = None

    def set_mode(self, mode):
        self.mode = mode

    def set_approval_handler(self, handler):
        self.handler = handler


class ProcessRuntime:
    """One stable agent identity, with replaceable execution processes."""

    def __init__(self, **config):
        self.config = config
        self.workspace_root = Path(config["workspace_root"])
        self.llm_settings = config.get("llm_settings", {})
        self.llm = SimpleNamespace(stream_responses=True)
        self.tool_loader = SimpleNamespace(permission_manager=_PermissionRelay())
        self.history = []
        self.runtime_events = []
        self.context_snapshot = {}
        self.checkpoint_handler = None
        self.rpc_handler = None
        self.remaining_inputs = []
        self._process = None
        self._connection = None
        self._job = None
        self._run_id = None
        self._interrupted = threading.Event()
        self._lifecycle = threading.RLock()
        self._send_lock = threading.Lock()
        self._invocation = threading.Lock()
        self._stop_error = None

    def _send(self, frame):
        with self._send_lock:
            self._connection.send(frame)

    def _start(self):
        with self._lifecycle:
            if self._process is not None and self._process.is_alive():
                return
            self._dispose()
            context = multiprocessing.get_context("spawn")
            parent, child = context.Pipe()
            job = WindowsJob()  # Failure is explicit; never fall back to threads.
            process = context.Process(target=run_worker, args=(child,), daemon=False)
            try:
                process.start()
                child.close()
                job.assign(process.sentinel)
                self._process, self._connection, self._job = process, parent, job
                self._send(self.config)
            except BaseException:
                job.close()
                if process.pid is not None:
                    process.terminate()
                    process.join(timeout=2)
                parent.close()
                child.close()
                raise

    def handle(self, request):
        request = request if isinstance(request, RuntimeRequest) else RuntimeRequest(content=request)
        return self._invoke("chat", asdict(request), request.metadata.get("request_id"))

    def compact_history(self, *, trigger, allow_fallback):
        return self._invoke("compact", {"trigger": trigger, "allow_fallback": allow_fallback})

    def _invoke(self, operation, request, run_id=None):
        if not self._invocation.acquire(blocking=False):
            raise RuntimeError("This agent already has an active execution")
        completed = False
        try:
            self._stop_error = None
            if self._interrupted.is_set():
                if operation == "chat":
                    return RuntimeResponse(content="[用户中断] 已停止当前任务。",
                                           session_id=request["session_id"], metadata={"interrupted": True})
                raise RuntimeError("Execution was interrupted before startup")
            self._run_id = run_id or uuid.uuid4().hex
            self._start()
            if self._interrupted.is_set():
                self.interrupt()
            self._send({"type": operation, "run_id": self._run_id, "request": request,
                        "history": self.history, "events": self.runtime_events,
                        "permission_mode": self.tool_loader.permission_manager.mode})
            while True:
                if self._stop_error is not None:
                    raise self._stop_error
                if self._connection.poll(0.05):
                    try:
                        frame = self._connection.recv()
                    except (EOFError, OSError):
                        break
                    if frame.get("run_id") not in (None, self._run_id):
                        continue
                    if frame["type"] == "rpc":
                        if frame["method"] == "checkpoint":
                            self._respond(frame)
                        else:
                            threading.Thread(target=self._respond, args=(frame,), daemon=True).start()
                    elif frame["type"] in {"result", "error"}:
                        self.remaining_inputs = frame.get("remaining_inputs", [])
                        if self._interrupted.is_set():
                            break
                        if frame["type"] == "error":
                            raise RuntimeError(frame["error"])
                        completed = True
                        return frame["result"]
                if not self._process.is_alive():
                    break
            if self._interrupted.is_set() and operation == "chat":
                return RuntimeResponse(content="[用户中断] 已停止当前任务。",
                                       session_id=request["session_id"], metadata={"interrupted": True})
            raise RuntimeError("Agent execution process exited before returning a result")
        finally:
            try:
                if self._interrupted.is_set() or not completed:
                    self._dispose()
                    results = {item.get("tool_call_id") for item in self.history if item.get("role") == "tool"}
                    uncertain = {call["id"] for item in self.history for call in item.get("tool_calls", [])
                                 if call.get("id") and call["id"] not in results}
                    self.history = prepare_runtime_history(
                        self.history, uncertain_tool_call_ids=uncertain,
                    ).history
            finally:
                self._run_id = None
                self._invocation.release()

    def _respond(self, frame):
        connection = self._connection
        try:
            if self._interrupted.is_set() or frame.get("run_id") != self._run_id:
                raise RuntimeError("Execution is stopping")
            if frame["method"] == "checkpoint":
                self.history = frame["payload"]["history"]
                self.runtime_events = frame["payload"]["events"]
                self.context_snapshot = dict(frame["payload"].get("context", {}))
                if self.checkpoint_handler:
                    self.checkpoint_handler(self.history)
                result = True
            elif frame["method"] == "permission":
                handler = self.tool_loader.permission_manager.handler
                result = handler(frame["payload"]) if handler else False
            elif self.rpc_handler:
                result = self.rpc_handler(frame["method"], frame["payload"])
            else:
                raise ValueError("Unknown worker request")
            reply = {"result": result}
        except Exception as exc:
            reply = {"error": str(exc)}
        try:
            with self._send_lock:
                connection.send({"type": "rpc_result", "id": frame["id"], **reply})
        except (OSError, EOFError):
            pass  # The stopped worker cannot receive a late approval/result.

    def steer(self, entry):
        if not self._run_id or self._interrupted.is_set():
            return False
        self._send({"type": "input", "run_id": self._run_id, "entry": entry})
        return True

    def interrupt(self):
        self._interrupted.set()
        run_id = self._run_id
        connection = self._connection
        if connection is not None:
            # Forced termination must not wait for a busy control pipe.
            threading.Thread(target=self._force_after_grace, args=(run_id,), daemon=True).start()

            def send_cancel():
                try:
                    with self._send_lock:
                        connection.send({"type": "interrupt", "run_id": run_id})
                except (OSError, EOFError):
                    pass

            threading.Thread(target=send_cancel, daemon=True).start()

    def _force_after_grace(self, run_id):
        time.sleep(0.4)
        with self._lifecycle:
            if self._run_id == run_id and self._job is not None:
                try:
                    self._job.terminate(timeout=2)
                except Exception as exc:
                    self._stop_error = exc

    def clear_interrupt(self):
        if self._invocation.locked():
            raise RuntimeError("Previous execution has not finished stopping")
        self._interrupted = threading.Event()

    def is_interrupted(self):
        return self._interrupted.is_set()

    def _dispose(self):
        with self._lifecycle:
            if self._job is not None:
                self._job.terminate(timeout=2)
                self._job.close()
                self._job = None
            if self._process is not None:
                self._process.join(timeout=2)
                if self._process.is_alive():
                    raise TimeoutError("Agent process has not exited")
                self._process.close()
                self._process = None
            if self._connection is not None:
                self._connection.close()
                self._connection = None

    def close(self):
        self.interrupt()
        with self._lifecycle:
            if self._job is not None:
                self._job.terminate(timeout=2)
        # The invocation owns its pipe reader. Let it consume EOF and persist
        # interruption before closing those handles underneath it.
        if not self._invocation.acquire(timeout=3):
            raise TimeoutError("Execution supervisor did not finish stopping")
        try:
            self._dispose()
        finally:
            self._invocation.release()
