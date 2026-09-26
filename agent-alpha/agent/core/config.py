"""
Configuration constants for Agent core components
Single source of truth for all system-wide settings
"""

# ========== Context Management ==========
MAX_CONTEXT_TOKENS = 600000  # Total input context limit (600K)
KEEP_RECENT_TURNS = 10  # Turns to preserve during compression
COMPRESSION_THRESHOLD = 0.8  # Compress when history reaches 80% of available space
COMPRESSION_INPUT_RATIO = 0.9  # Summary LLM can receive up to 90% of max tokens

# ========== Tool Execution ==========
MAX_TOOL_RESULT_CHARS = 30000  # Truncate individual tool results to 30K chars
BASH_TOOL_TIMEOUT = 30  # Default bash tool execution timeout (seconds)
BASH_TOOL_MAX_TIMEOUT = 300  # Maximum per-call bash timeout (seconds)

# ========== LLM Responses ==========
LLM_MAX_TOKENS = 300000  # Default max tokens for LLM generation
LLM_SUMMARY_MAX_TOKENS = 6000  # Max tokens for compression summary

# ========== Encoding ==========
TIKTOKEN_ENCODING = "cl100k_base"  # Encoding for token counting

# ========== MCP Tool Search ==========
DEFAULT_MCP_CATEGORY = "searchable"  # Default category for MCP servers not in registry.json
