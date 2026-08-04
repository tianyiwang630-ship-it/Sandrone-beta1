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


def test_generated_agents_rules_allow_general_work_without_automatic_ingestion():
    text = SKILL_FILE.read_text(encoding="utf-8")
    agents_rules = text[
        text.index("### 新 AGENTS.md 的必备内容") : text.index("生成完成后")
    ]

    assert "知识库身份不限制普通工作" in agents_rules
    assert "普通任务产生的新文件不得自动入库" in agents_rules
    assert "翻译、写作、分析、联网搜索、处理文件和编写代码" in agents_rules
    assert "用户明确指定文件时，直接进入新增资料流程" in agents_rules
    assert "用户没有指定文件时，只列出新的知识文档并询问" in agents_rules


def test_global_maintenance_is_limited_to_confirmed_knowledge_base_content():
    text = SKILL_FILE.read_text(encoding="utf-8")

    assert "活跃知识库范围" in text
    assert "根目录和 `inbox/` 中未确认入库的文件" in text
    assert "“暂未归类”只指已经确认入库" in text
    assert "不得自动移动、摘要或加入索引" in text
