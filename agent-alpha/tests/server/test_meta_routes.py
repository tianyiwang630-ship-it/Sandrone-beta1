from agent.server.routes.meta import _skill_items, _skill_summary


def test_skill_summary_reads_folded_yaml_description(tmp_path):
    skill_doc = tmp_path / "SKILL.md"
    skill_doc.write_text(
        """---
name: agent-reach
description: >
  Give your AI agent eyes to see the entire internet.
  Search and read 17 platforms.
---

# Agent Reach
""",
        encoding="utf-8",
    )

    assert _skill_summary(skill_doc) == "Give your AI agent eyes to see the entire internet. Search and read 17 platforms."


def test_skill_summary_strips_single_line_yaml_quotes(tmp_path):
    skill_doc = tmp_path / "SKILL.md"
    skill_doc.write_text(
        """---
name: ljg-read
description: "Reading companion agent."
---
""",
        encoding="utf-8",
    )

    assert _skill_summary(skill_doc) == "Reading companion agent."


def test_skill_items_do_not_show_yaml_fold_marker_as_summary(tmp_path):
    skill_dir = tmp_path / "agent-reach"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        """---
name: agent-reach
description: >
  Search and read the web.
---
""",
        encoding="utf-8",
    )

    items = _skill_items(tmp_path)

    assert len(items) == 1
    assert items[0].summary == "Search and read the web."
