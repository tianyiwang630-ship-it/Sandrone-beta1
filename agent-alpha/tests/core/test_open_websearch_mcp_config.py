import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from agent.discovery.mcp_scanner import MCPScanner


OPEN_WEBSEARCH_DIR = PROJECT_ROOT / "mcp-servers" / "open-websearch"


def test_open_websearch_mcp_config_pins_version_and_fake_ip_cidr():
    scanner = MCPScanner(str(PROJECT_ROOT / "mcp-servers"))

    discovered = scanner.scan()
    config = discovered["open-websearch"]

    assert config["args"] == ["-y", "open-websearch@2.1.11"]
    assert config["env"]["FAKE_IP_CIDRS"] == "198.18.0.0/16"
    assert config["env"]["DEFAULT_SEARCH_ENGINE"] == "duckduckgo"
    assert config["env"]["ALLOWED_SEARCH_ENGINES"] == "baidu,bing,linuxdo,csdn,duckduckgo,exa,brave,juejin,startpage,sogou"
    assert config["env"]["MODE"] == "stdio"


def test_open_websearch_auto_config_matches_custom_config():
    custom = json.loads((OPEN_WEBSEARCH_DIR / "mcp.config.json").read_text(encoding="utf-8"))
    auto = json.loads((OPEN_WEBSEARCH_DIR / "auto-config.json").read_text(encoding="utf-8"))

    assert auto["args"] == custom["args"]
    assert auto["env"] == custom["env"]
    assert auto["command"] == custom["command"]
    assert auto["type"] == custom["type"]
