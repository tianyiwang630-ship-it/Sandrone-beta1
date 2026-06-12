import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from tests.conftest import cleanup_test_dir, make_test_dir
from agent.core.skill_loader import SkillLoader


def test_skill_loader_reads_frontmatter_and_body():
    tmp_dir = make_test_dir("skill-loader")
    try:
        skills_dir = tmp_dir / "skills"
        skill_dir = skills_dir / "pdf"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            """---
name: pdf
description: Process PDF files
tags: docs, files
---
Step 1: inspect pages
Step 2: extract content
""",
            encoding="utf-8",
        )

        loader = SkillLoader(skills_dir)

        summaries = loader.get_summaries()
        assert summaries == [
            {
                "name": "pdf",
                "description": "Process PDF files",
                "tags": "docs, files",
                "path": str(skill_dir / "SKILL.md"),
            }
        ]
        assert loader.get_content("pdf") == (
            '<skill name="pdf">\n'
            "Step 1: inspect pages\n"
            "Step 2: extract content\n"
            "</skill>"
        )
    finally:
        cleanup_test_dir(tmp_dir)


def test_skill_loader_reads_folded_yaml_description_without_body_in_summary():
    tmp_dir = make_test_dir("skill-loader")
    try:
        skills_dir = tmp_dir / "skills"
        skill_dir = skills_dir / "agent-reach"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            """---
name: agent-reach
description: >
  Search and read Twitter/X, Reddit, YouTube, and any web page.
  Use when the user asks for recent posts or web research.
tags:
  - web
  - twitter
---
# Agent Reach

This body should only appear after load_skill.
""",
            encoding="utf-8",
        )

        loader = SkillLoader(skills_dir)

        summaries = loader.get_summaries()

        assert summaries[0]["description"] == (
            "Search and read Twitter/X, Reddit, YouTube, and any web page. "
            "Use when the user asks for recent posts or web research."
        )
        assert summaries[0]["tags"] == "web, twitter"
        assert "This body should only appear after load_skill" not in summaries[0]["description"]
        assert "This body should only appear after load_skill" in loader.get_content("agent-reach")
    finally:
        cleanup_test_dir(tmp_dir)


def test_skill_loader_ignores_invalid_yaml_frontmatter():
    tmp_dir = make_test_dir("skill-loader")
    try:
        skills_dir = tmp_dir / "skills"
        skill_dir = skills_dir / "broken"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            """---
name: broken
description: [unterminated
---
Broken body.
""",
            encoding="utf-8",
        )

        loader = SkillLoader(skills_dir)

        assert loader.get_summaries() == []
    finally:
        cleanup_test_dir(tmp_dir)


def test_skill_loader_reports_available_names_for_unknown_skill():
    tmp_dir = make_test_dir("skill-loader")
    try:
        skills_dir = tmp_dir / "skills"
        skill_dir = skills_dir / "review"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            """---
name: review
description: Review code changes
---
Review carefully.
""",
            encoding="utf-8",
        )

        loader = SkillLoader(skills_dir)

        missing = loader.get_content("pdf")

        assert "Unknown skill 'pdf'" in missing
        assert "review" in missing
    finally:
        cleanup_test_dir(tmp_dir)


def test_skill_loader_reads_primary_and_agent_home_skill_dirs():
    tmp_dir = make_test_dir("skill-loader")
    try:
        primary_dir = tmp_dir / "skills"
        agent_home_dir = tmp_dir / "home" / ".agents" / "skills"

        (primary_dir / "pdf").mkdir(parents=True)
        (primary_dir / "pdf" / "SKILL.md").write_text(
            """---
name: pdf
description: Process PDF files
---
Primary PDF skill.
""",
            encoding="utf-8",
        )
        (agent_home_dir / "agent-reach").mkdir(parents=True)
        (agent_home_dir / "agent-reach" / "SKILL.md").write_text(
            """---
name: agent-reach
description: Reach external web sources
---
Agent Reach skill.
""",
            encoding="utf-8",
        )

        loader = SkillLoader(primary_dir, extra_skills_dirs=[agent_home_dir])

        assert loader.get_content("pdf") == '<skill name="pdf">\nPrimary PDF skill.\n</skill>'
        assert loader.get_content("agent-reach") == (
            '<skill name="agent-reach">\nAgent Reach skill.\n</skill>'
        )
    finally:
        cleanup_test_dir(tmp_dir)


def test_skill_loader_primary_dir_wins_name_conflicts():
    tmp_dir = make_test_dir("skill-loader")
    try:
        primary_dir = tmp_dir / "skills"
        agent_home_dir = tmp_dir / "home" / ".agents" / "skills"

        for root, body in [(primary_dir, "Primary body."), (agent_home_dir, "Home body.")]:
            (root / "shared").mkdir(parents=True)
            (root / "shared" / "SKILL.md").write_text(
                f"""---
name: shared
description: Shared skill
---
{body}
""",
                encoding="utf-8",
            )

        loader = SkillLoader(primary_dir, extra_skills_dirs=[agent_home_dir])

        assert loader.get_content("shared") == '<skill name="shared">\nPrimary body.\n</skill>'
    finally:
        cleanup_test_dir(tmp_dir)
