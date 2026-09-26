from __future__ import annotations

import json
import os
import threading
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path


LIMITS = {"user": 500, "memory": 1200}
CONFIG_FIELDS = {"enabled", "documents_auto_update", "skills_auto_update", "auto_prompt", "manual_prompt"}


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(content, encoding="utf-8", newline="\n")
        for attempt in range(5):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.02 * (attempt + 1))
    finally:
        temporary.unlink(missing_ok=True)


def atomic_json(path: Path, data: dict | list) -> None:
    atomic_text(path, json.dumps(data, ensure_ascii=False, indent=2))


class MemoryStore:
    """Persistent state and document versions. All mutations use the shared lock."""

    def __init__(self, data_root: Path):
        self.root = Path(data_root).resolve()
        self.state = self.root / "memory-state"
        self.lock = threading.RLock()

    def _config_path(self) -> Path:
        return self.state / "config.json"

    def config(self) -> dict:
        with self.lock:
            path = self._config_path()
            if not path.exists():
                return {"schema_version": 1, "enabled": True, "documents_auto_update": True,
                        "skills_auto_update": True, "auto_prompt": "", "manual_prompt": "",
                        "initialized_at": now()}
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("schema_version") != 1:
                raise ValueError("Unsupported memory configuration version")
            return data

    def initialize(self) -> dict:
        with self.lock:
            config = self.config()
            if not self._config_path().exists():
                atomic_json(self._config_path(), config)
            for target in LIMITS:
                path = self.document_path(target)
                if not path.exists():
                    atomic_text(path, "")
            return config

    def update_config(self, updates: dict) -> dict:
        if not updates or set(updates) - CONFIG_FIELDS:
            raise ValueError("Invalid memory settings")
        for name, value in updates.items():
            if name.endswith("_prompt") and (not isinstance(value, str) or len(value) > 10000):
                raise ValueError("Supplemental prompt must be text within 10000 characters")
            if not name.endswith("_prompt") and not isinstance(value, bool):
                raise ValueError("Switch must be a boolean")
        with self.lock:
            config = self.initialize()
            config.update(updates)
            atomic_json(self._config_path(), config)
            return config

    def document_path(self, target: str) -> Path:
        if target not in LIMITS:
            raise ValueError("Unknown memory document")
        return self.root / f"{target}.md"

    def read_document(self, target: str) -> dict:
        with self.lock:
            self.initialize()
            path = self.document_path(target)
            content = path.read_text(encoding="utf-8")
            return {"target": target, "content": content, "length": len(content),
                    "limit": LIMITS[target], "revision": self._revision(path)}

    @staticmethod
    def _revision(path: Path) -> str:
        import hashlib
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def _version_dir(self, target: str) -> Path:
        self.document_path(target)
        return self.state / "versions" / target

    def versions(self, target: str) -> list[dict]:
        with self.lock:
            directory = self._version_dir(target)
            if not directory.exists():
                return []
            result = []
            for path in directory.glob("*.json"):
                try:
                    item = json.loads(path.read_text(encoding="utf-8"))
                    result.append(({key: item[key] for key in ("id", "created_at", "source")}, path.stat().st_mtime_ns))
                except (ValueError, KeyError):
                    continue
            return [item for item, _ in sorted(result, key=lambda entry: entry[1], reverse=True)[:8]]

    def version(self, target: str, version_id: str) -> dict:
        if not version_id or any(ch not in "0123456789abcdef" for ch in version_id):
            raise ValueError("Invalid version")
        path = self._version_dir(target) / f"{version_id}.json"
        if not path.is_file():
            raise FileNotFoundError("Version not found")
        return json.loads(path.read_text(encoding="utf-8"))

    def save_document(self, target: str, content: str, *, source: str,
                      expected_revision: str | None = None, batch_id: str | None = None) -> dict:
        if not isinstance(content, str):
            raise ValueError("Content must be text")
        content = content.replace("\r\n", "\n")
        if len(content) > LIMITS[target]:
            raise ValueError(f"{target}.md exceeds {LIMITS[target]} characters")
        with self.lock:
            current = self.read_document(target)
            if expected_revision is not None and current["revision"] != expected_revision:
                raise RuntimeError("Document changed; reload before saving")
            if current["content"] == content:
                return current
            directory = self._version_dir(target)
            directory.mkdir(parents=True, exist_ok=True)
            marker = directory / f"batch-{batch_id}.marker" if batch_id else None
            new_version = None
            if marker is None or not marker.exists():
                version_id = uuid.uuid4().hex
                new_version = directory / f"{version_id}.json"
                atomic_json(new_version, {
                    "id": version_id, "created_at": now(), "source": source,
                    "content": current["content"]})
                if marker:
                    atomic_text(marker, version_id)
            try:
                atomic_text(self.document_path(target), content)
            except OSError:
                if new_version:
                    new_version.unlink(missing_ok=True)
                    if marker:
                        marker.unlink(missing_ok=True)
                raise
            versions = sorted(directory.glob("*.json"), key=lambda path: path.stat().st_mtime_ns, reverse=True)
            for old in versions[8:]:
                old.unlink()
            remaining = {item.stem for item in versions[:8]}
            for old_marker in directory.glob("batch-*.marker"):
                if old_marker.read_text(encoding="utf-8") not in remaining:
                    old_marker.unlink()
            return self.read_document(target)

    def progress(self) -> dict:
        with self.lock:
            path = self.state / "progress.json"
            if path.exists():
                return json.loads(path.read_text(encoding="utf-8"))
            config = self.initialize()
            return {"schema_version": 1, "initialized_at": config["initialized_at"],
                    "last_auto_completed_at": None, "completed_ids": [], "recent_completed_ids": []}

    def save_progress(self, progress: dict) -> None:
        with self.lock:
            atomic_json(self.state / "progress.json", progress)

    def task_path(self, task_id: str) -> Path:
        if not task_id.startswith("mem_") or not task_id[4:] or any(ch not in "0123456789abcdef" for ch in task_id[4:]):
            raise ValueError("Invalid task")
        return self.state / "tasks" / f"{task_id}.json"

    def save_task(self, task: dict) -> None:
        with self.lock:
            atomic_json(self.task_path(task["id"]), task)

    def task(self, task_id: str) -> dict:
        path = self.task_path(task_id)
        if not path.exists():
            raise FileNotFoundError("Memory task not found")
        return json.loads(path.read_text(encoding="utf-8"))

    def latest_task(self) -> dict | None:
        directory = self.state / "tasks"
        if not directory.exists():
            return None
        paths = sorted(directory.glob("mem_*.json"), key=lambda path: path.stat().st_mtime_ns, reverse=True)
        return json.loads(paths[0].read_text(encoding="utf-8")) if paths else None

    def prune_tasks(self, keep: int = 16) -> None:
        with self.lock:
            directory = self.state / "tasks"
            if not directory.exists():
                return
            paths = sorted(directory.glob("mem_*.json"), key=lambda path: path.stat().st_mtime_ns, reverse=True)
            for path in paths[keep:]:
                task = json.loads(path.read_text(encoding="utf-8"))
                if task.get("status") in {"completed", "no_change", "cancelled"}:
                    path.unlink()
