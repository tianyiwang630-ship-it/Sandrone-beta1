"""
Skill loader for two-layer skill disclosure.

Layer 1: parse metadata for system prompt summaries.
Layer 2: return the full skill body on demand via load_skill(name).
"""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any, Dict, Iterable, List

import yaml


class SkillLoader:
    """Scan skills/<name>/SKILL.md files and expose summaries/body lookups."""

    def __init__(self, skills_dir: Path, extra_skills_dirs: Iterable[Path] | None = None):
        self.skills_dir = Path(skills_dir)
        self.skill_dirs = [self.skills_dir, *[Path(path) for path in extra_skills_dirs or []]]
        self.skills: Dict[str, Dict[str, Any]] = {}
        self.reload()

    def reload(self) -> None:
        """Rescan skills from disk."""
        self.skills = {}
        for skills_dir in self.skill_dirs:
            if not skills_dir.exists():
                continue

            for skill_file in sorted(skills_dir.rglob("SKILL.md")):
                meta, body = self._parse_skill_file(skill_file)
                name = meta.get("name") or skill_file.parent.name
                description = meta.get("description")
                if not name or not description or name in self.skills:
                    continue
                self.skills[name] = {
                    "meta": meta,
                    "body": body,
                    "path": str(skill_file),
                }

    def get_summaries(self) -> List[Dict[str, str]]:
        """Return prompt-safe summaries for all skills."""
        summaries: List[Dict[str, str]] = []
        for name, skill in self.skills.items():
            meta = skill["meta"]
            summary = {
                "name": name,
                "description": meta["description"],
                "path": skill["path"],
            }
            if meta.get("tags"):
                summary["tags"] = meta["tags"]
            summaries.append(summary)
        return summaries

    def get_content(self, name: str) -> str:
        """Return the full skill body in tool_result-friendly markup."""
        skill = self.skills.get(name)
        if not skill:
            available = ", ".join(sorted(self.skills)) or "(none)"
            return f"Error: Unknown skill '{name}'. Available: {available}"
        return f'<skill name="{name}">\n{skill["body"]}\n</skill>'

    def _parse_skill_file(self, skill_file: Path) -> tuple[Dict[str, str], str]:
        text = skill_file.read_text(encoding="utf-8")
        match = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n?(.*)$", text, re.DOTALL)
        if not match:
            return {}, text.strip()

        meta = self._parse_frontmatter(match.group(1))
        return meta, match.group(2).strip()

    @classmethod
    def _parse_frontmatter(cls, frontmatter: str) -> Dict[str, str]:
        try:
            parsed = yaml.safe_load(frontmatter) or {}
        except yaml.YAMLError:
            return {}

        if not isinstance(parsed, dict):
            return {}

        meta: Dict[str, str] = {}
        for key, value in parsed.items():
            if key is None or value is None:
                continue
            meta[str(key).strip()] = cls._metadata_value_to_string(value)
        return meta

    @classmethod
    def _metadata_value_to_string(cls, value: Any) -> str:
        if isinstance(value, list):
            return ", ".join(cls._metadata_value_to_string(item) for item in value)
        if isinstance(value, str):
            return " ".join(value.split())
        return str(value).strip()
