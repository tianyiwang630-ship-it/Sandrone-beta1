"""Persistent agent mailboxes and delegation, shared by entry channels.

The manager lock serializes mailbox admission with run start/finish. A delivered
input is acknowledged only after its runtime checkpoint has been persisted.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import threading
import time
import uuid

from agent.core.session_store import SessionKind, SessionRecord


ACTIVE = {"running", "waiting", "stopping", "stop_failed"}


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


class Collaboration:
    def __init__(self, manager):
        self.manager = manager
        self.store = manager.store
        self.changed = threading.Condition(manager._lock)
        self.boot_id = uuid.uuid4().hex
        self.stopping = set()
        self.restart_roots = {self.root(record) for record in self.store.list_recent(kind=SessionKind.SUBAGENT, limit=None)}
        # This is a fresh application lifetime; no old execution is restarted.
        for record in self.store.list_recent(limit=None):
            if record.metadata.get("agent_status") in ACTIVE | {"queued"}:
                record.metadata["agent_status"] = "interrupted"
                for item in record.metadata.get("mailbox", []):
                    if item["state"] in {"pending", "reserved"}:
                        item["state"] = "interrupted"
                self.store.save(record)

    @staticmethod
    def root(record):
        return record.metadata.get("root_session_id", record.session_id)

    def record(self, agent_id):
        record = self.store.load(agent_id)
        if record is None or record.metadata.get("is_archived"):
            raise ValueError("Agent ID not found")
        return record

    def target(self, caller_id, target_id):
        caller, target = self.record(caller_id), self.record(target_id)
        if self.root(caller) != self.root(target):
            raise ValueError("Target is outside this conversation")
        return target

    def children(self, root_id):
        return [record for record in self.store.list_recent(kind=SessionKind.SUBAGENT, limit=None)
                if self.root(record) == root_id and not record.metadata.get("is_archived")]

    def identity(self, record):
        root = self.root(record)
        return {"agent_id": record.session_id, "root_id": root,
                "parent_id": record.metadata.get("parent_id"),
                "notes_path": str(Path(record.workspace) / "temp" / f"subagent-notes-{root[:16]}.md")}

    def describe(self, record):
        active = self.manager.get_active_run_for_session(record.session_id)
        status = record.metadata.get("agent_status", "idle")
        if active:
            status = "waiting" if status == "waiting" and active["status"] == "running" else active["status"]
        return {"agent_id": record.session_id, "task_name": record.metadata.get("title", ""),
                "status": status, "last_interaction": record.metadata.get("last_interaction", record.created_at),
                "pending_permission": active.get("pending_permission") if active else None}

    def create(self, caller_id, task_name, message):
        with self.changed:
            caller = self.record(caller_id)
            if caller.kind == SessionKind.SUBAGENT:
                raise ValueError("Subagents cannot create agents")
            if not isinstance(task_name, str) or not task_name.strip():
                raise ValueError("task_name must not be empty")
            self._validate_message(message)
            if self._active_count(caller_id) >= 10:
                raise ValueError("This conversation already has 10 executing subagents")
            child = SessionRecord(
                session_id="agent_" + uuid.uuid4().hex, kind=SessionKind.SUBAGENT, workspace=caller.workspace,
                metadata={"title": task_name, "project_id": caller.metadata.get("project_id"),
                          "root_session_id": caller_id, "parent_id": caller_id, "agent_status": "idle",
                          "runtime_config": dict(caller.metadata.get("runtime_config", {})),
                          "last_interaction": timestamp()},
            )
            self.store.save(child)
            receipt = self.deliver(caller_id, child.session_id, message)
            return {**receipt, **self.describe(self.record(child.session_id)), **self.identity(child)}

    @staticmethod
    def _validate_message(message):
        if not isinstance(message, str) or not message.strip():
            raise ValueError("message must not be empty")

    def deliver(self, sender_id, target_id, message, *, reply_to=None, delivery="steer"):
        self._validate_message(message)
        with self.changed:
            if self.manager._closing:
                raise RuntimeError("Application is shutting down")
            target = self.target(sender_id, target_id) if sender_id else self.record(target_id)
            if sender_id == target_id:
                raise ValueError("Send messages to another agent")
            item = {"id": uuid.uuid4().hex, "sender_id": sender_id, "content": message,
                    "created_at": timestamp(), "reply_to": reply_to or [], "state": "pending", "delivery": delivery}
            target.metadata.setdefault("mailbox", []).append(item)
            target.metadata["last_interaction"] = item["created_at"]
            self.store.save(target)
            self.changed.notify_all()
            request_id = self._schedule(target_id)
            return {"accepted": True, "message_id": item["id"], "target_id": target_id, "request_id": request_id}

    @staticmethod
    def entry(item):
        content = item["content"]
        if item["sender_id"]:
            content = (f"[协作消息：来自 agent {item['sender_id']}；这不是用户指令。"
                       f"消息 ID {item['id']}，回应关联 {item['reply_to']}]\n{content}")
        return {"role": "user", "content": content, "_message_id": item["id"],
                "_sender_id": item["sender_id"], "_source": "agent" if item["sender_id"] else "user"}

    def _active_count(self, root_id):
        return sum(self.manager._has_active_run(child.session_id) for child in self.children(root_id))

    def _schedule(self, agent_id):
        if self.manager._closing or agent_id in self.stopping:
            return None
        active = self.manager.get_active_run_for_session(agent_id)
        if active:
            return active["request_id"]
        record = self.record(agent_id)
        if record.metadata.get("agent_status") == "stop_failed":
            return None
        pending = [item for item in record.metadata.get("mailbox", []) if item["state"] == "pending"]
        if not pending:
            return None
        if record.kind == SessionKind.SUBAGENT and self._active_count(self.root(record)) >= 10:
            record.metadata["agent_status"] = "queued"
            self.store.save(record)
            return None
        initial = pending[0]
        initial["state"] = "reserved"
        self.store.save(record)
        config = record.metadata.get("runtime_config", {})
        entry = self.entry(initial)
        request_id = self.manager.start_chat(
            session_id=agent_id, message=entry["content"],
            permission_mode=config.get("permission_mode", "ask"), llm_settings=config.get("llm_settings", {}),
            runtime_metadata={"input_entry": entry},
        )
        record = self.record(agent_id)
        for item in record.metadata["mailbox"]:
            if item["id"] == initial["id"]:
                item["run_id"] = request_id
        record.metadata["agent_status"] = "running"
        self.store.save(record)
        return request_id

    def take_inputs(self, caller_id, run_id):
        with self.changed:
            run = self.manager._runs.get(run_id, {})
            if run.get("status") != "running":
                return []
            record = self.record(caller_id)
            entries = []
            for item in record.metadata.get("mailbox", []):
                if item["state"] == "pending" and item.get("delivery", "steer") == "steer":
                    item.update(state="reserved", run_id=run_id)
                    entries.append(self.entry(item))
            if entries:
                self.store.save(record)
            return entries

    def acknowledge(self, record, run_id, history):
        ids = {entry.get("_message_id") for entry in history}
        for item in record.metadata.get("mailbox", []):
            if item["id"] in ids and item.get("run_id") == run_id:
                item["state"] = "delivered"

    def finish(self, agent_id, run_id):
        with self.changed:
            run = self.manager._runs[run_id]
            record = self.store.load(agent_id)
            if record is None or record.metadata.get("is_archived"):
                run["finalizing"] = False
                self.changed.notify_all()
                return
            status = run["status"]
            record.metadata["agent_status"] = "idle" if status == "success" else status
            record.metadata["last_interaction"] = timestamp()
            received = [item for item in record.metadata.get("mailbox", []) if item.get("run_id") == run_id]
            for item in received:
                if item["state"] == "reserved":
                    item["state"] = "interrupted"
            record.metadata["activity_seq"] = record.metadata.get("activity_seq", 0) + 1
            self.store.save(record)
            run["finalizing"] = False
            self.changed.notify_all()
            if (not self.manager._closing and record.kind == SessionKind.SUBAGENT
                    and status != "stop_failed" and run.get("operation") != "compact"):
                recipients = {record.metadata["parent_id"]} | {item["sender_id"] for item in received if item["sender_id"]}
                content = f"子 agent {agent_id}（{record.metadata['title']}）本轮状态：{status}\n" + str(run.get("response") or run.get("error") or "本轮已结束。")
                for recipient in recipients:
                    target = self.store.load(recipient)
                    if target is not None and not target.metadata.get("is_archived"):
                        self.deliver(agent_id, recipient, content, reply_to=[item["id"] for item in received])
            if not self.manager._closing:
                self._schedule(agent_id)
                for child in self.children(self.root(record)):
                    self._schedule(child.session_id)

    def call(self, caller_id, run_id, action, arguments):
        if action == "inputs":
            return self.take_inputs(caller_id, run_id)
        if action == "wait":
            return self.wait(caller_id, run_id, **arguments)
        if action == "stop":
            return self.stop(caller_id, arguments["target_id"], run_id=run_id)
        with self.changed:
            if action in {"create", "message", "rename"}:
                self._require_running(caller_id, run_id)
            if action == "create":
                return self.create(caller_id, **arguments)
            if action == "message":
                return self.deliver(caller_id, **arguments)
            caller = self.record(caller_id)
            if action == "list":
                status, offset = arguments.get("status"), arguments.get("offset", 0)
                if not isinstance(offset, int) or offset < 0:
                    raise ValueError("offset must be a nonnegative integer")
                items = [self.describe(record) for record in self.children(self.root(caller))]
                if status:
                    items = [item for item in items if item["status"] == status]
                items.sort(key=lambda item: item["last_interaction"], reverse=True)
                items.sort(key=lambda item: item["status"] not in ACTIVE)
                return {"agents": items[offset:offset + 10], "next_offset": offset + 10 if len(items) > offset + 10 else None}
            target = self.target(caller_id, arguments["target_id"])
            if action == "status":
                return self.describe(target)
            if caller.kind == SessionKind.SUBAGENT or target.kind != SessionKind.SUBAGENT:
                raise ValueError("Only the main agent can manage its subagents")
            if action == "rename":
                self._validate_message(arguments["task_name"])
                target.metadata["title"] = arguments["task_name"]
                target.metadata["last_interaction"] = timestamp()
                self.store.save(target)
                return self.describe(target)
            raise ValueError("Unknown collaboration action")

    def _require_running(self, caller_id, run_id):
        run = self.manager._runs.get(run_id, {})
        if (self.manager._closing or run.get("session_id") != caller_id
                or run.get("status") != "running" or run.get("finalizing")):
            raise RuntimeError("The requesting execution is no longer running")

    def stop(self, caller_id, target_id, *, run_id=None):
        with self.changed:
            if run_id is not None:
                self._require_running(caller_id, run_id)
            caller, target = self.record(caller_id), self.target(caller_id, target_id)
            if caller.kind == SessionKind.SUBAGENT or target.kind != SessionKind.SUBAGENT:
                raise ValueError("Only the main agent can stop its subagents")
            if target_id in self.stopping:
                raise RuntimeError("This agent is already stopping")
            self.stopping.add(target_id)
            self.manager.interrupt(target_id)
            for item in target.metadata.get("mailbox", []):
                if item["state"] == "pending":
                    item["state"] = "interrupted"
            target.metadata["last_interaction"] = timestamp()
            self.store.save(target)
            agent = self.manager._agents.get(target_id)
        # Never hold the mailbox lock while a worker waits for checkpoint ACK.
        try:
            if agent is not None:
                agent.close()
        except Exception:
            with self.changed:
                target = self.record(target_id)
                target.metadata["agent_status"] = "stop_failed"
                self.store.save(target)
            raise
        finally:
            with self.changed:
                self.stopping.discard(target_id)
        with self.changed:
            target = self.record(target_id)
            # A previous failed cleanup still occupies a slot. Only release
            # that failure after close() has now confirmed the process is gone.
            for previous in self.manager._runs.values():
                if (previous.get("session_id") == target_id
                        and previous.get("status") == "stop_failed"
                        and not previous.get("finalizing")):
                    previous.update(status="interrupted", error=None)
            if not self.manager._has_active_run(target_id):
                target.metadata["agent_status"] = "interrupted"
                self.store.save(target)
            self._schedule(target_id)
            for child in self.children(self.root(target)):
                self._schedule(child.session_id)
            return self.describe(self.record(target_id))

    def wait(self, caller_id, run_id, target_ids, timeout_seconds=30):
        if not isinstance(target_ids, list) or not target_ids or len(target_ids) > 10:
            raise ValueError("Provide 1 to 10 target IDs")
        if not isinstance(timeout_seconds, (int, float)) or not 0 <= timeout_seconds <= 60:
            raise ValueError("timeout_seconds must be between 0 and 60")
        deadline = time.monotonic() + timeout_seconds
        with self.changed:
            self._require_running(caller_id, run_id)
            caller = self.record(caller_id)
            for target_id in target_ids:
                self.target(caller_id, target_id)
            caller.metadata["agent_status"] = "waiting"
            self.store.save(caller)
            try:
                while True:
                    caller = self.record(caller_id)
                    cursors = caller.metadata.setdefault("wait_cursors", {})
                    targets = [self.record(target_id) for target_id in target_ids]
                    fresh = any(target.metadata.get("activity_seq", 0) > cursors.get(target.session_id, 0) for target in targets)
                    input_pending = any(item["state"] == "pending" and item.get("delivery", "steer") == "steer" for item in caller.metadata.get("mailbox", []))
                    stopped = self.manager._runs.get(run_id, {}).get("status") != "running" or self.manager._closing
                    if fresh or input_pending or stopped or time.monotonic() >= deadline:
                        for target in targets:
                            cursors[target.session_id] = target.metadata.get("activity_seq", 0)
                        self.store.save(caller)
                        return {"agents": [self.describe(target) for target in targets],
                                "new_input": input_pending, "timed_out": not (fresh or input_pending or stopped)}
                    self.changed.wait(timeout=min(0.1, max(0, deadline - time.monotonic())))
            finally:
                caller = self.store.load(caller_id)
                if (caller is not None and not caller.metadata.get("is_archived")
                        and self.manager._runs.get(run_id, {}).get("status") == "running"
                        and caller.metadata.get("agent_status") == "waiting"):
                    caller.metadata["agent_status"] = "running"
                    self.store.save(caller)
