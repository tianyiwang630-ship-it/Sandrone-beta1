from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from agent.core.skill_loader import SkillLoader


def test_install_alpha_skill_is_available_and_contains_path_rules():
    loader = SkillLoader(PROJECT_ROOT / "skills")
    loader.reload()

    content = loader.get_content("install-alpha-skill")

    assert "agent-alpha/home/.agents/skills/<skill-name>" in content
    assert "bash already runs with cwd set to `AGENT_ALPHA_ROOT`" in content
    assert "home/.agents/skills/<skill-name>" in content
    assert "temp/skill-install/<source-name>" in content
    assert "Do not write bash commands like `agent-alpha/home/...`" in content
    assert "agent-alpha/skills/<skill-name>" in content
    assert "~/.claude/skills" in content
    assert "agent-alpha/.venv" in content
    assert "AGENT_ALPHA_ROOT=agent-alpha" in content
    assert "agent-alpha/bin" in content
    assert "runtime_env.local.json" in content
    assert "Do not use it to override path policy variables" in content
    assert "npm install -g" in content
    assert "go install" in content
