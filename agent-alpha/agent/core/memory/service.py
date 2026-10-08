"""The single authority for memory edits and review tasks."""
from __future__ import annotations

import os
import shutil
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

from agent.core.memory.sources import available_turns, parse_time, read_turn
from agent.core.memory.store import LIMITS, MemoryStore, atomic_json, atomic_text, now
from agent.core.role_config import RoleConfig
from agent.core.process_runtime import ProcessRuntime
from agent.core.runtime_types import RuntimeRequest
from agent.core.runtime_layout import APP_ROOT
from agent.core.skill_loader import SkillLoader

try:
    import msvcrt
except ImportError:  # pragma: no cover
    msvcrt = None


ACTIVE = {"organizing", "reviewing", "committing"}
TERMINAL = {"completed", "partial", "no_change", "skipped", "cancelled"}


class MemoryConflict(RuntimeError):
    """An external edit needs attention, rather than an automatic overwrite."""


class MemoryService:
    # LLM requests time out after 60s; allow request retries and context compression.
    STALL_SECONDS = 600

    def __init__(self, data_root: Path):
        self.store = MemoryStore(data_root)
        self.root = self.store.root
        self._lock = threading.RLock()
        self._edit: dict | None = None
        self._worker: ProcessRuntime | None = None
        self._thread: threading.Thread | None = None
        self._lease_file = None
        self._closing = False
        self._last_activity = time.monotonic()
        self.store.initialize()

    @contextmanager
    def _data_lock(self):
        """Serialize settings, edits and review writes across Web and CLI processes."""
        path = self.store.state / "data.lock"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a+b") as handle:
            if msvcrt:
                handle.seek(0)
                if not handle.read(1):
                    handle.write(b"0")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                if msvcrt:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)

    def _lease(self) -> bool:
        if self._lease_file is not None:
            return True
        path = self.store.state / "task.lock"
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = path.open("a+b")
        if msvcrt:
            try:
                handle.seek(0)
                if not handle.read(1):
                    handle.write(b"0")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                handle.close()
                return False
        self._lease_file = handle
        return True

    def _release_lease(self) -> None:
        handle = self._lease_file
        self._lease_file = None
        if handle:
            if msvcrt:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            handle.close()

    def config(self) -> dict:
        return self.store.config()

    def update_config(self, updates: dict) -> dict:
        with self._lock, self._data_lock():
            return self.store.update_config(updates)

    def allowed(self, *, manual: bool) -> list[str]:
        config = self.config()
        return (["user", "memory"] if manual or config["documents_auto_update"] else []) + (
            ["references"] if manual or config["skills_auto_update"] else [])

    def document(self, target: str) -> dict:
        return self.store.read_document(target)

    def versions(self, target: str) -> list[dict]:
        return self.store.versions(target)

    def version(self, target: str, version_id: str) -> dict:
        return self.store.version(target, version_id)

    def _editing(self) -> bool:
        path = self.store.state / "edit.json"
        if path.exists():
            import json
            self._edit = json.loads(path.read_text(encoding="utf-8"))
        else:
            self._edit = None
        if self._edit and parse_time(self._edit["expires_at"]) <= datetime.now().astimezone():
            path.unlink(missing_ok=True)
            self._edit = None
        return self._edit is not None

    def begin_edit(self, target: str) -> dict:
        with self._lock, self._data_lock():
            if self._editing():
                raise RuntimeError("Another memory edit is active")
            document = self.document(target)
            current = self.current_task()
            if current and current["status"] in ACTIVE | {"failed"}:
                current["status"] = "cancelled"
                current["cleanup_pending"] = True
                self.store.save_task(current)
                if self._worker:
                    self._worker.interrupt()
            token = uuid.uuid4().hex
            self._edit = {"id": token, "target": target,
                          "expires_at": (datetime.now().astimezone() + timedelta(minutes=30)).isoformat()}
            atomic_json(self.store.state / "edit.json", self._edit)
            return {"id": token, "revision": document["revision"], "expires_at": self._edit["expires_at"]}

    def _check_edit(self, target: str, edit_id: str) -> None:
        if not self._editing() or self._edit["id"] != edit_id or self._edit["target"] != target:
            raise RuntimeError("Edit expired; reopen the document")

    def cancel_edit(self, edit_id: str) -> None:
        with self._lock, self._data_lock():
            self._editing()
            if self._edit and self._edit["id"] == edit_id:
                self._edit = None
                (self.store.state / "edit.json").unlink(missing_ok=True)

    def save_document(self, target: str, content: str, *, edit_id: str, revision: str) -> dict:
        with self._lock, self._data_lock():
            self._check_edit(target, edit_id)
            saved = self.store.save_document(target, content, source="manual", expected_revision=revision)
            self._edit = None
            (self.store.state / "edit.json").unlink(missing_ok=True)
            progress = self.store.progress()
            progress["last_auto_completed_at"] = now()
            progress["baseline_at"] = now()
            progress["recent_completed_ids"] = []
            self.store.save_progress(progress)
            return saved

    def restore(self, target: str, version_id: str, *, edit_id: str, revision: str) -> dict:
        content = self.version(target, version_id)["content"]
        return self.save_document(target, content, edit_id=edit_id, revision=revision)

    def current_task(self) -> dict | None:
        pending = self.store.pending_tasks()
        return pending[0] if pending else self.store.latest_task()

    def protected_sessions(self) -> set[str]:
        return {turn["session_id"] for task in self.store.pending_tasks() for turn in task.get("turns", [])}

    def start_task(self, *, manual: bool, start: str | None = None, end: str | None = None,
                   targets: list[str] | None = None, llm_settings: dict | None = None) -> dict:
        with self._lock, self._data_lock():
            if self._editing():
                raise RuntimeError("Memory is being edited")
            current = self.current_task()
            if current and current["status"] in ACTIVE | {"failed"}:
                raise RuntimeError("A memory update is already running")
            if self._thread and self._thread.is_alive():
                raise RuntimeError("Previous memory update is still stopping")
            if not self._lease():
                raise RuntimeError("A memory update is already running")
        try:
            if start and end and parse_time(start) > parse_time(end):
                raise ValueError("Start time is later than end time")
            range_end = end or datetime.now().astimezone().isoformat()
            selected = available_turns(self.root, start=start if manual else None, end=range_end)
            with self._lock, self._data_lock():
                if self._editing():
                    raise RuntimeError("Memory is being edited")
                if not manual:
                    processed = set(self.store.progress()["completed_ids"])
                    selected = [turn for turn in selected if turn["id"] not in processed]
                if not selected:
                    raise ValueError("No completed conversations in this range")
                allowed = self.allowed(manual=manual)
                if targets is not None:
                    if not manual or not targets or set(targets) - {"documents", "references"}:
                        raise ValueError("Invalid manual update targets")
                    requested = ({"user", "memory"} if "documents" in targets else set()) | (
                        {"references"} if "references" in targets else set())
                    if requested - set(allowed):
                        raise ValueError("Selected update target is disabled")
                    allowed = [target for target in allowed if target in requested]
                if not allowed:
                    raise ValueError("No memory update target is enabled")
                task = {"id": f"mem_{uuid.uuid4().hex}", "manual": manual, "status": "organizing",
                        "created_at": now(), "start": start, "end": range_end, "turns": selected,
                        "prompt": self.config()["manual_prompt" if manual else "auto_prompt"],
                        "allowed_at_start": allowed, "proposals": None, "operations": {}, "error": None,
                        "results": {}, "document_revisions": {target: self.document(target)["revision"]
                                                               for target in ("user", "memory")},
                        "organizer_history": [], "reviewer_history": []}
                self.store.save_task(task)
                self._thread = threading.Thread(target=self._run, args=(task["id"], llm_settings or {}), daemon=True)
                self._thread.start()
                return self._public_task(task)
        except BaseException:
            with self._lock:
                self._release_lease()
            raise

    @staticmethod
    def _public_task(task: dict) -> dict:
        public = {key: task.get(key) for key in ("id", "manual", "status", "created_at", "start", "end", "error",
                                                "allowed_at_start", "retry_after", "retryable", "proposal_count", "operation_count")}
        public["results"] = list(task.get("results", {}).values())
        return public

    def task(self, task_id: str) -> dict:
        return self._public_task(self.store.task(task_id))

    def maybe_start_auto(self, llm_settings: dict | None = None) -> dict | None:
        with self._lock:
            if self._editing() or not self.allowed(manual=False):
                return None
            current = self.current_task()
            if current and current["status"] in ACTIVE | {"failed"}:
                return None
            progress = self.store.progress()
            if len(progress.get("recent_completed_ids", [])) < 20:
                return None
            baseline = parse_time(progress.get("last_auto_completed_at") or progress.get("baseline_at")
                                  or progress["initialized_at"])
            if datetime.now().astimezone() - baseline < timedelta(hours=24):
                return None
            processed = set(progress["completed_ids"])
            recent = set(progress.get("recent_completed_ids", []))
            all_turns = available_turns(self.root, end=datetime.now().astimezone().isoformat())
            new_turns = [turn for turn in all_turns if turn["id"] not in processed and turn["id"] in recent]
            if len(new_turns) < 20:
                return None
            try:
                return self.start_task(manual=False, llm_settings=llm_settings)
            except (RuntimeError, ValueError):
                return None

    def note_completed_turn(self, session_id: str, request_id: str) -> None:
        identity = f"{session_id}:{request_id}"
        with self._lock, self._data_lock():
            progress = self.store.progress()
            recent = progress.setdefault("recent_completed_ids", [])
            if identity not in recent:
                recent.append(identity)
                self.store.save_progress(progress)

    def _run_role(self, task_id: str, role: str, llm_settings: dict) -> None:
        task = self.store.task(task_id)
        workspace = self.root / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)
        runner = ProcessRuntime(
            workspace_root=str(workspace),
            logs_dir=str(self.store.state / "logs"),
            events_dir=str(self.store.state / "events"),
            llm_settings=llm_settings,
            role_config=RoleConfig(name=f"memory_{role}", allowed_tools=["__memory_only__"]),
            memory_role={"role": role, "task_id": task_id},
        )
        self._worker = runner
        self._last_activity = time.monotonic()
        runner.history = task[f"{role}_history"]
        runner.checkpoint_handler = lambda history: self._checkpoint(task_id, role, history)
        runner.rpc_handler = lambda method, payload: self._memory_rpc(task_id, role, method, payload)
        if role == "organizer":
            prompt = f"整理任务 {task_id}。本批有 {len(task['turns'])} 轮。先读取已有文档，再 memory_read(kind='turns') 获取清单并分段读取。补充要求：{task['prompt']}。结束前必须调用 memory_submit。"
        else:
            prompt = f"审核任务 {task_id}。先 memory_read(kind='proposals') 和 memory_read(kind='results') 查看提案与已处理项，继续未处理项，按原始依据逐项核查。补充要求：{task['prompt']}。合格项用 memory_edit；不合格项用 memory_skip 记录原因。每项必须有结果。"
        prompt += f" 本批允许修改：{task['allowed_at_start']}；容量：{LIMITS}，每个 Skill references 合计 5000 字符。"
        stop_watch = threading.Event()
        stalled = threading.Event()

        def watch_cancellation():
            while not stop_watch.wait(0.2):
                try:
                    cancelled = self.store.task(task_id)["status"] == "cancelled"
                except (OSError, ValueError):
                    cancelled = False
                if cancelled:
                    runner.interrupt()
                    return
                if time.monotonic() - self._last_activity > self.STALL_SECONDS:
                    stalled.set()
                    runner.interrupt()
                    return

        watcher = threading.Thread(target=watch_cancellation, daemon=True)
        watcher.start()
        try:
            response = runner.handle(RuntimeRequest(content=prompt, session_id=task_id, source="memory"))
            if stalled.is_set():
                raise RuntimeError("Memory worker stopped making progress; retry will resume this batch")
            if response.metadata.get("interrupted") or response.metadata.get("recoverable"):
                raise RuntimeError("Memory role did not finish")
            self._checkpoint(task_id, role, runner.history)
        finally:
            stop_watch.set()
            watcher.join(timeout=1)
            try:
                # ProcessRuntime repairs unfinished tool calls on interruption/failure.
                # Persist that repaired history rather than replaying an invalid checkpoint.
                self._checkpoint(task_id, role, runner.history)
            finally:
                try:
                    runner.close()
                finally:
                    self._worker = None

    def _checkpoint(self, task_id: str, role: str, history: list) -> None:
        with self._lock, self._data_lock():
            self._last_activity = time.monotonic()
            task = self.store.task(task_id)
            if task["status"] in ACTIVE:
                task[f"{role}_history"] = history
                self.store.save_task(task)

    def _run(self, task_id: str, llm_settings: dict) -> None:
        try:
            task = self.store.task(task_id)
            if task["status"] == "organizing":
                if task["proposals"] is None:
                    self._run_role(task_id, "organizer", llm_settings)
                with self._lock, self._data_lock():
                    task = self.store.task(task_id)
                    if task["status"] == "cancelled":
                        return
                    if task["proposals"] is None:
                        raise RuntimeError("Organizer did not submit proposals")
                    task["status"] = "reviewing" if task["proposals"] else "committing"
                    self.store.save_task(task)
            if task["status"] == "reviewing":
                with self._lock, self._data_lock():
                    task = self.store.task(task_id)
                    if task["status"] == "cancelled":
                        return
                    self._recover_operation(task)
                if len(task.get("results", {})) < len(task["proposals"]):
                    self._run_role(task_id, "reviewer", llm_settings)
                with self._lock, self._data_lock():
                    task = self.store.task(task_id)
                    if task["status"] == "cancelled":
                        return
                    if len(task.get("results", {})) != len(task["proposals"]):
                        raise RuntimeError("Reviewer left proposals unfinished; resume remaining items")
                    task["status"] = "committing"
                    self.store.save_task(task)
            with self._lock, self._data_lock():
                task = self.store.task(task_id)
                if task["status"] == "cancelled":
                    return
                if task["status"] != "committing":
                    raise RuntimeError("Unexpected memory task stage")
                if task.get("evidence_gaps"):
                    raise ValueError("Original logs are missing or unreadable; incomplete evidence needs attention")
                if not task["manual"]:
                    progress = self.store.progress()
                    available = {turn["id"] for turn in available_turns(
                        self.root, end=datetime.now().astimezone().isoformat())}
                    progress["completed_ids"] = [identity for identity in dict.fromkeys(
                        progress["completed_ids"] + [turn["id"] for turn in task["turns"]]) if identity in available]
                    completed = {turn["id"] for turn in task["turns"]}
                    progress["recent_completed_ids"] = [identity for identity in progress.get("recent_completed_ids", [])
                                                        if identity not in completed]
                    progress["last_auto_completed_at"] = now()
                    self.store.save_progress(progress)
                results = list(task.get("results", {}).values())
                changed = sum(item.get("changed", False) for item in results)
                skipped = any(item["status"] in {"skipped", "blocked"} for item in results)
                task["status"] = ("partial" if skipped else "completed") if changed else ("skipped" if skipped else "no_change")
                task["completed_at"] = now()
                task["proposal_count"] = len(task["proposals"] or [])
                task["operation_count"] = changed
                task["attempts"] = 0
                task["error"] = None
                task.pop("retry_after", None)
                task.pop("organizer_history", None)
                task.pop("reviewer_history", None)
                task.pop("turns", None)
                task.pop("proposals", None)
                task.pop("reference_contents", None)
                task.pop("document_revisions", None)
                task["cleanup_pending"] = True
                self.store.save_task(task)
        except Exception as exc:
            with self._lock, self._data_lock():
                task = self.store.task(task_id)
                if task["status"] != "cancelled":
                    if self._closing:
                        task["error"] = "Interrupted by application shutdown; resume on next start"
                    else:
                        task["failed_stage"] = task["status"]
                        task["status"] = "failed"
                        task["attempts"] = task.get("attempts", 0) + 1
                        task["retryable"] = not isinstance(exc, (ValueError, MemoryConflict))
                        delay = min(3600, 60 * 2 ** min(task["attempts"] - 1, 6))
                        task["retry_after"] = (datetime.now().astimezone() + timedelta(seconds=delay)).isoformat()
                        task["error"] = str(exc)
                    self.store.save_task(task)
        finally:
            try:
                task = self.store.task(task_id)
                if task["status"] in TERMINAL:
                    self._cleanup(task)
            finally:
                with self._lock:
                    self._release_lease()

    def _memory_rpc(self, task_id: str, role: str, method: str, payload: dict):
        if method != "memory_tool":
            raise ValueError("Unknown memory request")
        with self._lock:
            self._last_activity = time.monotonic()
            task = self.store.task(task_id)
            expected = "organizing" if role == "organizer" else "reviewing"
            if task["status"] != expected:
                raise RuntimeError("Memory task is no longer active")
            name = payload["name"]
            allowed_names = {"memory_read", "memory_note", "memory_submit"} if role == "organizer" else {"memory_read", "memory_note", "memory_edit", "memory_skip"}
            if name not in allowed_names:
                raise ValueError("Tool not available to this role")
            arguments = payload.get("arguments") or {}
            return getattr(self, f"_{name}")(task, role=role, **arguments)

    def _memory_read(self, task: dict, *, role: str, kind: str, target: str = "",
                     index: int = 0, offset: int = 0, version_id: str = "", skill: str = "", path: str = ""):
        if kind == "turns":
            if index < 0:
                raise ValueError("Invalid turn index")
            page = task["turns"][index:index + 50]
            return {"items": [{key: turn[key] for key in ("id", "started_at", "content")} for turn in page],
                    "next_index": index + len(page) if index + len(page) < len(task["turns"]) else None}
        if kind == "turn":
            if index < 0 or index >= len(task["turns"]):
                raise ValueError("Turn index outside this task")
            page = read_turn(self.root, task["turns"][index], offset=offset)
            if page["missing"]:
                with self._data_lock():
                    if self.store.task(task["id"])["status"] != task["status"]:
                        raise RuntimeError("Memory task was cancelled")
                    task.setdefault("evidence_gaps", {})[task["turns"][index]["id"]] = "Missing or unreadable log"
                    self.store.save_task(task)
                raise ValueError("Original conversation log is missing; evidence cannot be verified")
            return page
        if kind == "document":
            return self.store.read_document(target)
        if kind == "versions":
            return self.store.versions(target)
        if kind == "version":
            return self.store.version(target, version_id)
        if kind == "proposals" and role == "reviewer":
            return task["proposals"]
        if kind == "results" and role == "reviewer":
            return list(task.get("results", {}).values())
        if kind == "skills":
            loader = SkillLoader(APP_ROOT / "skills", extra_skills_dirs=[self.root / "home" / ".agents" / "skills"])
            return [{"name": name, "writable": Path(item["path"]).resolve().is_relative_to(self.root)}
                    for name, item in loader.skills.items()]
        if kind == "references":
            base = self._skill_path(skill, "__scope__.md").parent
            return [str(file.relative_to(base)).replace("\\", "/") for file in sorted(base.rglob("*"))
                    if file.is_file() and file.resolve().is_relative_to(base)
                    and file.suffix.lower() in {".md", ".org", ".txt"}][:100] if base.exists() else []
        if kind == "skill":
            if offset < 0:
                raise ValueError("Invalid reference page")
            content = self._skill_path(skill, path).read_text(encoding="utf-8")
            with self._data_lock():
                if self.store.task(task["id"])["status"] != task["status"]:
                    raise RuntimeError("Memory task was cancelled")
                task.setdefault("reference_contents", {}).setdefault(f"{skill}/{path}", content)
                self.store.save_task(task)
            page = content[offset:offset + 12000]
            return {"content": page, "next_offset": offset + len(page) if offset + len(page) < len(content) else None}
        raise ValueError("Unknown read kind")

    def _memory_note(self, task: dict, *, role: str, action: str, content: str = ""):
        note = self.root / "temp" / "memory" / task["id"] / "note.md"
        if action == "read":
            return {"content": note.read_text(encoding="utf-8") if note.exists() else ""}
        if action == "save" and role == "organizer":
            if len(content) > 50000:
                raise ValueError("Scratch note exceeds 50000 characters")
            atomic_text(note, content)
            return {"ok": True}
        raise ValueError("Unknown or forbidden note action")

    def _memory_submit(self, task: dict, *, role: str, proposals: list):
        if task["proposals"] is not None:
            raise RuntimeError("Proposals already submitted")
        if not isinstance(proposals, list) or len(proposals) > 40:
            raise ValueError("Invalid proposals")
        for item in proposals:
            if not isinstance(item, dict) or item.get("target") not in {"user", "memory", "references"}:
                raise ValueError("Invalid proposal target")
            if not item.get("source") or not item.get("reason"):
                raise ValueError("Proposal needs source and reason")
        task["proposals"] = proposals
        with self._data_lock():
            if self.store.task(task["id"])["status"] != "organizing":
                raise RuntimeError("Memory task was cancelled")
            self.store.save_task(task)
        return {"ok": True, "count": len(proposals)}

    def _skill_path(self, skill: str, relative: str, *, writable: bool = False) -> Path:
        if not relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise ValueError("Invalid Skill reference path")
        loader = SkillLoader(APP_ROOT / "skills", extra_skills_dirs=[self.root / "home" / ".agents" / "skills"])
        item = loader.skills.get(skill)
        if item is None:
            raise ValueError("Unknown skill")
        skill_root = Path(item["path"]).parent.resolve()
        if writable and not skill_root.is_relative_to(self.root):
            raise ValueError("Installed skill is not writable runtime data")
        base = (skill_root / "references").resolve()
        if not base.is_relative_to(skill_root):
            raise ValueError("Skill references leave the runtime skill")
        target = (base / relative).resolve()
        if target == base or not target.is_relative_to(base) or target.suffix.lower() not in {".md", ".org", ".txt"}:
            raise ValueError("Invalid Skill reference path")
        return target

    def _memory_edit(self, task: dict, *, role: str, proposal_index: int, operation_id: str,
                     target: str, operation: str, content: str = "", skill: str = "", path: str = ""):
        if proposal_index < 0 or proposal_index >= len(task["proposals"]):
            raise ValueError("Unknown proposal")
        proposal = task["proposals"][proposal_index]
        if target != proposal["target"] or (target == "references" and (skill != proposal.get("skill") or path != proposal.get("path"))):
            raise ValueError("Edit is outside the proposal")
        if not operation_id or len(operation_id) > 100:
            raise ValueError("Invalid operation identifier")
        if operation_id in task["operations"]:
            previous = task["operations"][operation_id]
            if previous.get("proposal_index", proposal_index) != proposal_index:
                raise ValueError("Operation identifier belongs to a different proposal")
            if str(proposal_index) not in task.get("results", {}):
                return self._record_result(task, proposal_index, "applied", "Previously saved",
                                           changed=previous.get("changed", True))
            return previous
        with self._data_lock():
            if self.store.task(task["id"])["status"] != "reviewing":
                raise RuntimeError("Memory task was cancelled")
            self._recover_operation(task)
            if str(proposal_index) in task.get("results", {}):
                return task["results"][str(proposal_index)]
            if target not in task["allowed_at_start"] or target not in self.allowed(manual=task["manual"]):
                return self._record_result(task, proposal_index, "blocked", "This update target is disabled")
            if target in LIMITS:
                if operation != "replace":
                    raise ValueError("Document edit must replace the full content")
                content = content.replace("\r\n", "\n")
                if len(content) > LIMITS[target]:
                    raise ValueError(f"{target}.md exceeds {LIMITS[target]} characters")
                document = self.document(target)
                expected = task.get("document_revisions", {}).get(target, document["revision"])
                if expected != document["revision"]:
                    raise MemoryConflict("Memory document changed outside this task; review before retrying")
                old_content = document["content"]
                existed = True
            else:
                destination = self._skill_path(skill, path, writable=True)
                if operation not in {"replace", "delete"}:
                    raise ValueError("Invalid reference operation")
                base = self._skill_path(skill, "__scope__.md", writable=True).parent
                current_total = sum(len(file.read_text(encoding="utf-8")) for file in base.rglob("*")
                                    if file.is_file() and file.resolve().is_relative_to(base)
                                    and file.suffix.lower() in {".md", ".org", ".txt"}) if base.exists() else 0
                old_content = destination.read_text(encoding="utf-8") if destination.exists() else ""
                existed = destination.exists()
                expected = task.get("reference_contents", {}).get(f"{skill}/{path}", old_content)
                if expected != old_content:
                    raise MemoryConflict("Skill reference changed outside this task; review before retrying")
                new_total = current_total - len(old_content) + (len(content) if operation == "replace" else 0)
                if new_total > 5000 and new_total >= current_total:
                    raise ValueError("Skill references exceed 5000 characters")
            task["pending_operation"] = {"proposal_index": proposal_index, "operation_id": operation_id,
                                         "target": target, "operation": operation, "content": content,
                                         "skill": skill, "path": path, "old_content": old_content,
                                         "existed": existed}
            self.store.save_task(task)
            return self._recover_operation(task)

    def _record_result(self, task: dict, index: int, status: str, reason: str, *, changed: bool = False) -> dict:
        result = {"proposal_index": index, "target": task["proposals"][index]["target"],
                  "status": status, "reason": reason, "changed": changed, "ok": status == "applied"}
        task.setdefault("results", {})[str(index)] = result
        self.store.save_task(task)
        return result

    def _memory_skip(self, task: dict, *, role: str, proposal_index: int, reason: str):
        if not 0 <= proposal_index < len(task["proposals"]) or not reason.strip() or len(reason) > 1000:
            raise ValueError("Skip requires a valid proposal and a short reason")
        with self._data_lock():
            if self.store.task(task["id"])["status"] != "reviewing":
                raise RuntimeError("Memory task was cancelled")
            self._recover_operation(task)
            if str(proposal_index) in task.get("results", {}):
                return task["results"][str(proposal_index)]
            return self._record_result(task, proposal_index, "skipped", reason)

    def _recover_operation(self, task: dict) -> dict | None:
        """Reconcile a write-ahead record while holding the shared data lock."""
        pending = task.get("pending_operation")
        if not pending:
            return None
        if self.store.task(task["id"])["status"] != "reviewing":
            raise RuntimeError("Memory task was cancelled")
        target = pending["target"]
        destination = (self.store.document_path(target) if target in LIMITS else
                       self._skill_path(pending["skill"], pending["path"], writable=True))
        exists = destination.exists()
        current = destination.read_text(encoding="utf-8") if exists else ""
        after_exists = pending["operation"] != "delete"
        after = pending["content"] if after_exists else ""
        already_written = (exists, current) == (after_exists, after)
        if not already_written:
            if (exists, current) != (pending["existed"], pending["old_content"]):
                raise MemoryConflict("Pending memory write conflicts with newer file content")
            if target not in task["allowed_at_start"] or target not in self.allowed(manual=task["manual"]):
                task.pop("pending_operation")
                return self._record_result(task, pending["proposal_index"], "blocked", "This update target is disabled")
            if target in LIMITS:
                self.store.save_document(target, after, source="ai", batch_id=task["id"],
                                         expected_revision=self.store._revision(destination))
            elif after_exists:
                base = self._skill_path(pending["skill"], "__scope__.md", writable=True).parent
                total = sum(len(file.read_text(encoding="utf-8")) for file in base.rglob("*")
                            if file.is_file() and file.resolve().is_relative_to(base)
                            and file.suffix.lower() in {".md", ".org", ".txt"}) if base.exists() else 0
                new_total = total - len(current) + len(after)
                if new_total > 5000 and new_total >= total:
                    raise ValueError("Skill references exceed 5000 characters")
                atomic_text(destination, after)
            else:
                destination.unlink(missing_ok=True)
        if target in LIMITS:
            task.setdefault("document_revisions", {})[target] = self.store._revision(destination)
        else:
            task.setdefault("reference_contents", {})[f"{pending['skill']}/{pending['path']}"] = after
        changed = (pending["existed"], pending["old_content"]) != (after_exists, after)
        task.pop("pending_operation")
        # Keep the operation receipt and proposal outcome in the same persisted task update.
        result = {"proposal_index": pending["proposal_index"], "target": target, "status": "applied",
                  "reason": "Saved" if changed else "Content already matches", "changed": changed, "ok": True}
        task.setdefault("results", {})[str(pending["proposal_index"])] = result
        task["operations"][pending["operation_id"]] = result
        self.store.save_task(task)
        return result

    def _cleanup(self, task: dict) -> None:
        try:
            scratch = self.root / "temp" / "memory" / task["id"]
            if scratch.exists():
                shutil.rmtree(scratch)
            for directory in ("logs", "events"):
                (self.store.state / directory / f"{task['id']}.jsonl").unlink(missing_ok=True)
            task.pop("cleanup_pending", None)
        except OSError:
            task["cleanup_pending"] = True
        self.store.save_task(task)
        self.store.prune_tasks()

    def control_task(self, task_id: str, *, action: str, llm_settings: dict | None = None) -> dict:
        with self._lock, self._data_lock():
            if self._thread and self._thread.is_alive():
                raise RuntimeError("Memory worker is still running")
            task = self.store.task(task_id)
            if task["status"] != "failed" or action not in {"retry", "cancel"}:
                raise ValueError("Only a failed task can be retried or abandoned")
            if action == "cancel":
                task["status"] = "cancelled"
                task["cleanup_pending"] = True
            else:
                task["retry_after"] = now()
                task["retryable"] = True
            self.store.save_task(task)
        if action == "retry":
            self.resume(llm_settings)
        else:
            self._cleanup(task)
        return self.task(task_id)

    def resume(self, llm_settings: dict | None = None) -> None:
        with self._lock, self._data_lock():
            if self._closing or self._editing() or (self._thread and self._thread.is_alive()):
                return
            task = self.current_task()
            for finished in self.store.tasks():
                if finished["status"] in TERMINAL and finished.get("cleanup_pending"):
                    self._cleanup(finished)
            if task and task["status"] == "failed" and task.get("retryable", True):
                if parse_time(task["retry_after"]) <= datetime.now().astimezone():
                    if self._lease():
                        task["status"] = task["failed_stage"]
                        task["error"] = None
                        self.store.save_task(task)
            if task and task["status"] in ACTIVE and self._lease():
                self._thread = threading.Thread(target=self._run, args=(task["id"], llm_settings or {}), daemon=True)
                self._thread.start()

    def close(self) -> None:
        self._closing = True
        worker = self._worker
        if worker:
            worker.interrupt()
        if self._thread:
            self._thread.join(timeout=5)
