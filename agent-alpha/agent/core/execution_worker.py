"""Agent execution endpoint. No runtime/tool imports before the ownership gate."""
from __future__ import annotations

import queue
import os
import threading
import uuid


def run_worker(connection):
    # The supervisor assigns the process to its Job before sending this frame.
    config = connection.recv()
    identity = config.pop("collaboration", None)
    os.chdir(config["workspace_root"])
    if identity:
        os.environ["AGENT_ALPHA_BROWSER_SCOPE"] = identity["agent_id"]
    from agent.core.agent_runtime import AgentRuntime
    from agent.core.runtime_types import RuntimeRequest

    send_lock = threading.Lock()
    pending = {}
    pending_lock = threading.Lock()
    commands = queue.Queue()
    inputs = queue.Queue()
    runtime = None
    run_id = None

    def send(payload):
        with send_lock:
            connection.send(payload)

    def rpc(method, payload):
        call_id = uuid.uuid4().hex
        response = queue.Queue(maxsize=1)
        with pending_lock:
            pending[call_id] = response
        try:
            send({"type": "rpc", "id": call_id, "run_id": run_id, "method": method, "payload": payload})
            result = response.get()
            if "error" in result:
                raise RuntimeError(result["error"])
            return result.get("result")
        finally:
            with pending_lock:
                pending.pop(call_id, None)

    def receive():
        try:
            while True:
                frame = connection.recv()
                if frame["type"] == "rpc_result":
                    with pending_lock:
                        reply = pending.get(frame["id"])
                    if reply is not None:
                        reply.put(frame)
                elif frame["type"] == "interrupt":
                    if runtime is not None and frame.get("run_id") == run_id:
                        runtime.interrupt()
                elif frame["type"] == "input":
                    inputs.put((frame["run_id"], frame["entry"]))
                else:
                    commands.put(frame)
        except (EOFError, OSError):
            if runtime is not None:
                runtime.interrupt()
            commands.put({"type": "close"})

    def drain_inputs(include_remote=True):
        entries = []
        while True:
            try:
                target_run, entry = inputs.get_nowait()
                if target_run == run_id:
                    entries.append(entry)
            except queue.Empty:
                return entries + (rpc("inputs", {}) if identity and include_remote else [])

    def checkpoint(history):
        # Acknowledged persistence before a subsequent tool can produce effects.
        rpc("checkpoint", {"history": history, "events": runtime.runtime_events,
                           "context": {"system_prompt": getattr(runtime, "system_prompt", ""),
                                       "available_tools": len(getattr(runtime, "tools", [])),
                                       "role": getattr(getattr(runtime, "role_config", None), "name", "default")}})

    threading.Thread(target=receive, daemon=True).start()
    try:
        runtime = AgentRuntime(**config)
        # Interactive keyboard handling belongs to the entry process.
        runtime._start_esc_listener = lambda: None
        runtime.llm.stream_responses = True
        runtime.input_provider = drain_inputs
        runtime.checkpoint = checkpoint
        if identity:
            from agent.core.collaboration_tools import install_collaboration_tools
            install_collaboration_tools(runtime, identity, rpc)
        if runtime.tool_loader.permission_manager is not None:
            runtime.tool_loader.permission_manager.set_approval_handler(lambda prompt: rpc("permission", prompt))
        send({"type": "ready"})
        while True:
            frame = commands.get()
            if frame["type"] == "close":
                return
            run_id = frame["run_id"]
            runtime.history = frame["history"]
            runtime.runtime_events = frame["events"]
            if runtime.tool_loader.permission_manager is not None:
                runtime.tool_loader.permission_manager.set_mode(frame["permission_mode"])
            try:
                if frame["type"] == "chat":
                    result = runtime.handle(RuntimeRequest(**frame["request"]))
                else:
                    runtime.clear_interrupt()
                    result = runtime.compact_history(**frame["request"])
                checkpoint(runtime.history)
                send({"type": "result", "run_id": run_id, "result": result, "remaining_inputs": drain_inputs(False)})
            except Exception as exc:
                send({"type": "error", "run_id": run_id, "error": str(exc), "remaining_inputs": drain_inputs(False)})
            finally:
                run_id = None
    except Exception as exc:
        send({"type": "error", "run_id": run_id, "error": str(exc)})
    finally:
        connection.close()
