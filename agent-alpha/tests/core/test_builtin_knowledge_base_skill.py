from pathlib import Path


SKILL_FILE = (
    Path(__file__).resolve().parents[2]
    / "home"
    / ".agents"
    / "skills"
    / "managing-knowledge-wikis"
    / "SKILL.md"
)


def test_knowledge_base_skill_is_installed_with_product_marker_contract():
    assert SKILL_FILE.is_file()
    text = SKILL_FILE.read_text(encoding="utf-8")

    assert ".alpha/knowledge-base.json" in text
    assert '"type": "knowledge_base"' in text
    assert '"version": 1' in text
    assert '"created_at"' in text
    assert "不得创建标识" in text
    assert "不覆盖 `.alpha/`" in text


def test_marker_creation_is_after_final_validation_and_is_the_last_write():
    text = SKILL_FILE.read_text(encoding="utf-8")
    validation_position = text.index("链接")
    marker_position = text.index("最后创建 `.alpha/knowledge-base.json`")

    assert marker_position > validation_position
    assert "最后一个写入动作" in text[marker_position:]
