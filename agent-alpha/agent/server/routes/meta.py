from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter
import yaml

from agent.core.runtime_layout import APP_ROOT, PROJECT_ROOT
from agent.server.models import CapabilityItem, CapabilityResponse

router = APIRouter(prefix="/api/meta", tags=["meta"])


def _skill_summary(skill_doc: Path) -> str | None:
    try:
        text = skill_doc.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None

    lines = text.splitlines()
    if lines and lines[0].strip() == "---":
        end_index = next((index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---"), None)
        if end_index is not None:
            try:
                frontmatter = yaml.safe_load("\n".join(lines[1:end_index])) or {}
            except Exception:
                frontmatter = {}
            if isinstance(frontmatter, dict):
                description = frontmatter.get("description")
                if description:
                    return " ".join(str(description).split())

    for line in lines:
        if line.lower().startswith("description:"):
            description = line.split(":", 1)[1].strip().strip("\"'")
            if description and description not in {">", "|"}:
                return description
            return None
    return None


def _skill_items(root: Path) -> list[CapabilityItem]:
    items: list[CapabilityItem] = []
    if not root.exists():
        return items
    for child in sorted(root.iterdir(), key=lambda item: item.name.lower()):
        skill_doc = child / "SKILL.md"
        if child.is_dir() and skill_doc.exists():
            summary = _skill_summary(skill_doc)
            items.append(CapabilityItem(name=child.name, kind="skill", path=str(child), summary=summary))
    return items


def _mcp_items() -> list[CapabilityItem]:
    registry = APP_ROOT / "mcp-servers" / "registry.json"
    if not registry.exists():
        return []
    try:
        data = json.loads(registry.read_text(encoding="utf-8"))
    except Exception:
        return []
    raw_items = data.get("servers") if isinstance(data, dict) else data
    if not isinstance(raw_items, list):
        return []
    result: list[CapabilityItem] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("id") or "mcp")
        result.append(CapabilityItem(name=name, kind="mcp", path=str(item.get("path") or ""), summary=item.get("description")))
    return result


@router.get("/capabilities", response_model=CapabilityResponse)
def list_capabilities():
    items = []
    items.extend(_skill_items(APP_ROOT / "skills"))
    items.extend(_skill_items(PROJECT_ROOT / "home" / ".agents" / "skills"))
    items.extend(_mcp_items())
    return CapabilityResponse(items=items)
