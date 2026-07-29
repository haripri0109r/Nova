"""Core enums shared by the whole LLM package."""
from enum import Enum


class LLMProvider(str, Enum):
    GEMINI = "gemini"
    OPENAI = "openai"
    CLAUDE = "claude"
    OLLAMA = "ollama"
    OPENROUTER = "openrouter"
    PLACEHOLDER = "placeholder"


class LLMTaskType(str, Enum):
    TRANSLATE = "translate"          # NL → structured actions
    CHAT = "chat"                    # free‑form chat (not used by Nova)
    CONVERSATION = "conversation"    # free‑form chat (alias)
    STRUCTURED = "structured_output" # forced JSON output