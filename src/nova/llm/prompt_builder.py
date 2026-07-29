"""Builds the *only* prompt the model ever sees – forces pure JSON."""
from __future__ import annotations
from typing import List, Dict, Any
from .models import ExecutionRequest

# ------------------------------------------------------------------
# System prompt – **never** shown to the user, only to the model.
# ------------------------------------------------------------------
SYSTEM_PROMPT = r"""
You are Nova – a deterministic semantic translator.
Your ONLY job: turn the user's natural language into the **exact** JSON schema below.
NEVER output markdown, explanations, apologies, or anything except the JSON object.

{
  "requires_execution": true|false,
  "response_text": "string spoken by Windows SAPI",
  "actions": [
    { "tool": "string", "parameters": { ... }, "description": "optional" }
  ]
}

RULES
1. If the user only chats ("hi", "how are you?") → requires_execution:false, actions:[].
2. Every actionable request → requires_execution:true, at least one action.
3. Supported tools (exact names):
   open_application, close_application, set_brightness, set_volume,
   web_search, open_url, take_screenshot, get_system_info, run_command,
   open_file, create_file, read_file, write_file, list_files, delete_file,
   copy_file, move_file, get_weather, get_time, set_timer, set_alarm,
   send_notification, play_sound, speak_text
4. Parameter names **must** match the tool schema exactly.
5. Output **only** the JSON object – no markdown fences, no commentary.

EXAMPLES
User: "It's too dark, can you reduce the brightness?"
{
  "requires_execution": true,
  "response_text": "Sure! I reduced the brightness to 30 percent.",
  "actions": [{ "tool": "set_brightness", "parameters": {"value": 30}, "description": "Lower brightness" }]
}
User: "Open Chrome and then open my Nova project"
{
  "requires_execution": true,
  "response_text": "Opening Chrome and your Nova project.",
  "actions": [
    {"tool":"open_application","parameters":{"application":"chrome"},"description":"Launch Chrome"},
    {"tool":"open_application","parameters":{"application":"vscode"},"description":"Launch VS Code"},
    {"tool":"open_file","parameters":{"path":"C:/Nova"},"description":"Open Nova project"}
  ]
}
"""

# ------------------------------------------------------------------
# Tool schemas – fed to providers that support function‑calling.
# ------------------------------------------------------------------
TOOL_DEFINITIONS = [
    {"type":"function","function":{"name":"open_application","description":"Launch an app","parameters":{"type":"object","properties":{"application":{"type":"string"}},"required":["application"]}}},
    {"type":"function","function":{"name":"close_application","description":"Close an app","parameters":{"type":"object","properties":{"application":{"type":"string"}},"required":["application"]}}},
    {"type":"function","function":{"name":"set_brightness","description":"Screen brightness 0‑100","parameters":{"type":"object","properties":{"value":{"type":"integer","minimum":0,"maximum":100}},"required":["value"]}}},
    {"type":"function","function":{"name":"set_volume","description":"System volume 0‑100","parameters":{"type":"object","properties":{"value":{"type":"integer","minimum":0,"maximum":100}},"required":["value"]}}},
    {"type":"function","function":{"name":"web_search","description":"Search the web","parameters":{"type":"object","properties":{"query":{"type":"string"},"num_results":{"type":"integer","default":5}},"required":["query"]}}},
    {"type":"function","function":{"name":"open_url","description":"Open a URL in the default browser","parameters":{"type":"object","properties":{"url":{"type":"string"}},"required":["url"]}}},
    {"type":"function","function":{"name":"run_command","description":"Execute a shell command","parameters":{"type":"object","properties":{"command":{"type":"string"},"args":{"type":"array","items":{"type":"string"}}},"required":["command"]}}},
    {"type":"function","function":{"name":"open_file","description":"Open a file or folder","parameters":{"type":"object","properties":{"path":{"type":"string"}},"required":["path"]}}},
    {"type":"function","function":{"name":"create_file","description":"Create a file with content","parameters":{"type":"object","properties":{"path":{"type":"string"},"content":{"type":"string"}},"required":["path","content"]}}},
    {"type":"function","function":{"name":"read_file","description":"Read a file","parameters":{"type":"object","properties":{"path":{"type":"string"}},"required":["path"]}}},
    {"type":"function","function":{"name":"write_file","description":"Write/overwrite a file","parameters":{"type":"object","properties":{"path":{"type":"string"},"content":{"type":"string"}},"required":["path","content"]}}},
    {"type":"function","function":{"name":"list_files","description":"List directory contents","parameters":{"type":"object","properties":{"path":{"type":"string"}},"required":["path"]}}},
    {"type":"function","function":{"name":"delete_file","description":"Delete a file","parameters":{"type":"object","properties":{"path":{"type":"string"}},"required":["path"]}}},
    {"type":"function","function":{"name":"copy_file","description":"Copy a file","parameters":{"type":"object","properties":{"src":{"type":"string"},"dst":{"type":"string"}},"required":["src","dst"]}}},
    {"type":"function","function":{"name":"move_file","description":"Move/rename a file","parameters":{"type":"object","properties":{"src":{"type":"string"},"dst":{"type":"string"}},"required":["src","dst"]}}},
    {"type":"function","function":{"name":"get_weather","description":"Current weather","parameters":{"type":"object","properties":{"location":{"type":"string","default":"auto"}},"required":["location"]}}},
    {"type":"function","function":{"name":"get_time","description":"Current time","parameters":{"type":"object","properties":{"timezone":{"type":"string","default":"local"}},"required":[]}}},
    {"type":"function","function":{"name":"set_timer","description":"Set a timer (seconds)","parameters":{"type":"object","properties":{"seconds":{"type":"integer","minimum":1}},"required":["seconds"]}}},
    {"type":"function","function":{"name":"set_alarm","description":"Set an alarm (HH:MM)","parameters":{"type":"object","properties":{"time":{"type":"string"}},"required":["time"]}}},
    {"type":"function","function":{"name":"send_notification","description":"Desktop notification","parameters":{"type":"object","properties":{"title":{"type":"string"},"message":{"type":"string"}},"required":["title","message"]}}},
    {"type":"function","function":{"name":"play_sound","description":"Play a WAV/MP3 file","parameters":{"type":"object","properties":{"path":{"type":"string"}},"required":["path"]}}},
    {"type":"function","function":{"name":"speak_text","description":"Speak via Windows SAPI (handled by Voice Engine)","parameters":{"type":"object","properties":{"text":{"type":"string"}},"required":["text"]}}},
]

class PromptBuilder:
    """Utility – builds the exact message list a provider receives."""
    @staticmethod
    def build_messages(user_text: str, history: list[dict] | None = None) -> list[dict]:
        msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
        if history:
            msgs.extend(history)
        msgs.append({"role": "user", "content": user_text})
        return msgs

    @staticmethod
    def tool_definitions() -> list[dict]:
        return TOOL_DEFINITIONS