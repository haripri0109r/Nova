"""
Planner – LLM-based multi-step plan generation.

Takes user text and classified intent, produces an ExecutionPlan with multiple PlanSteps.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

from .models import (
    IntentResult,
    ExecutionPlan,
    PlanStep,
)
from .compound import is_compound_command
from nova.llm.manager import get_llm_manager
from ..agent.models import ToolAction
from .validator import PlanValidator
from .exceptions import PlanningError, PlanValidationError
from ..skills.registry import registry as skill_registry

logger = logging.getLogger("nova.brain.planner")


def format_compact_tools(tools: List[Dict[str, Any]]) -> str:
    """
    Format canonical tool definitions into a compact, LLM-optimized representation.
    Derived dynamically from canonical Skill.parameters_schema.
    """
    lines = []
    for tool_def in tools:
        tool_name = tool_def.get("tool", "")
        if not tool_name:
            continue
        schema = tool_def.get("parameters_schema") or tool_def.get("parameters") or {}
        props = schema.get("properties", {}) if isinstance(schema, dict) else {}
        params = []
        if isinstance(props, dict):
            for p_name, p_spec in props.items():
                if not isinstance(p_spec, dict):
                    params.append(f"{p_name}: string")
                    continue
                if "enum" in p_spec and isinstance(p_spec["enum"], (list, tuple)):
                    type_str = "|".join(str(e) for e in p_spec["enum"])
                else:
                    t = p_spec.get("type", "string")
                    if isinstance(t, list):
                        type_str = "|".join(str(x) for x in t)
                    else:
                        type_str = str(t)
                params.append(f"{p_name}: {type_str}")
        lines.append(f"{tool_name}({', '.join(params)})")
    return "\n".join(lines)


class Planner:
    """
    Generates multi-step execution plans using an LLM.
    
    The planner:
    1. Receives user text and classified intent
    2. Queries available skills from the registry
    3. Asks the LLM to break down the request into executable steps
    4. Validates each step against registered skills via PlanValidator
    5. Returns a validated ExecutionPlan
    """

    def __init__(
        self,
        llm_manager: Optional[Any] = None,
        skill_registry: Optional[Any] = None,
        validator: Optional[PlanValidator] = None,
    ):
        from ..skills.registry import registry as default_registry
        self._llm_manager = llm_manager or get_llm_manager()
        self._skill_registry = skill_registry if skill_registry is not None else default_registry
        self._validator = validator or PlanValidator(self._skill_registry)
        self.confidence_threshold: float = 0.7

    async def initialize(self) -> bool:
        """Initialize the planner."""
        try:
            await self._llm_manager.initialize()
            return True
        except Exception as e:
            logger.error(f"Planner initialization failed: {e}")
            return False

    async def cleanup(self) -> None:
        """Cleanup planner resources."""
        pass

    def _get_available_tools(self) -> List[Dict[str, Any]]:
        """Get list of available skills/tools from registry."""
        if hasattr(self._skill_registry, "get_tool_definitions"):
            return self._skill_registry.get_tool_definitions()
        tools = []
        seen_intents = set()
        for skill in self._skill_registry.all():
            if skill.intent not in seen_intents:
                seen_intents.add(skill.intent)
                schema = getattr(skill, "parameters_schema", None)
                if schema is None:
                    schema = getattr(skill, "parameter_schema", {})
                tool_def = {
                    "tool": skill.intent,
                    "description": skill.description,
                    "parameters_schema": schema if isinstance(schema, dict) else {},
                    "parameters": schema if isinstance(schema, dict) else {},
                }
                tools.append(tool_def)
        return tools

    def _build_planning_prompt(
        self,
        user_text: str,
        intent: IntentResult,
        available_tools: List[Dict[str, Any]],
        context: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Build the compact, schema-derived prompt for the LLM to generate a plan."""
        compact_tools = format_compact_tools(available_tools)
        
        context_str = ""
        if context:
            context_str = f"\nContext: {json.dumps(context)}"

        return f"""You are Nova's command planner. Output JSON execution plans only.
Never output markdown or explanations. Only valid JSON.
Create ONLY steps directly required to satisfy the user's request. Do NOT invent preparatory, verification, or extra steps (such as opening folders or reading screens) unless explicitly requested.
For single-step plans, "depends_on" must always be []. For compound multi-step plans, step 1 depends on step 0 ("depends_on": [0]).
If request is ambiguous without context (such as "open it", "close that", "do something", "search for that"), physical, impossible, or has no matching tool, return {{"steps": [], "description": "Unsupported"}}.
Rules:
- To open or launch apps (e.g. Spotify, Chrome, Edge, Notepad): use tool "open_application" with application. Never use open_browser for applications.
- For Bluetooth: use tool "bluetooth" with action "enable" or "disable". Never use shutdown.
- For Wi-Fi: use tool "wifi" with action "enable" or "disable". Never use shutdown.
- For Lock: use tool "lock". Never use shutdown or restart.
- For Sleep: use tool "sleep" with parameters {{}}. Never use shutdown or restart.
- For Shutdown/Restart: only use when explicitly requested to turn off or reboot the computer. Parameters must be {{}}. Never use reason or extra arguments.
- For finding files or documents: use tool "find_file" with pattern.
- For file and folder operations (list directory, file info, open file, create folder, create file, rename, copy, move, delete file): use tool "file_operation" with action ("list_directory", "get_file_info", "open_file", "create_folder", "create_file", "rename_file", "copy_file", "move_file", "delete_file"). Never use file_operation for open_folder or find_file. Never use overwrite=true.
- For opening folders in Windows File Explorer: use tool "open_folder" with path.
- Any request mentioning YouTube or Spotify: use tool "play_media" with query and app ("youtube" or "spotify"). Never use web_search if the user mentions YouTube or Spotify.
- For web search or browsing queries: use tool "web_search" with query.
- For opening settings pages: use tool "open_settings" with page (e.g. "display", "wifi", "sound", "default_apps"). Never use open_application for settings.
- For personalization (theme, taskbar, wallpaper): use tool "personalization" with feature ("theme", "taskbar", or "wallpaper"). For theme use mode ("dark" or "light"). For taskbar use alignment ("left" or "center"). For wallpaper use path.
- For display control (brightness, resolution, refresh rate, orientation, display info, night light): use tool "display" with action ("get_brightness", "set_brightness", "increase_brightness", "decrease_brightness", "get_display_info", "get_resolution", "set_resolution", "get_refresh_rate", "set_refresh_rate", "get_orientation", "set_orientation", "night_light"). Never use open_settings when asked to change or inspect display state directly.
- For audio control (volume, mute, unmute, microphone, output devices, default device): use tool "audio" with action ("get_volume", "set_volume", "increase_volume", "decrease_volume", "mute", "unmute", "list_outputs", "list_inputs", "get_mic_status", "set_mic_volume", "mute_mic", "unmute_mic", "set_default_output"). Never use open_settings when asked to change or inspect audio state directly.
- For Windows window and desktop management (minimize, maximize, restore, snap, focus, close, show desktop, list, get active window): use tool "window" with action ("show_desktop", "restore_all", "minimize", "maximize", "restore", "snap", "focus", "close", "list", "get_active"). For snap use position ("left", "right", "top", "bottom", "center"). Never use open_application for switching or focusing existing windows.
- For ambiguous commands with unclear targets like "it" or "that": return {{"steps": [], "description": "Unsupported"}}.

AVAILABLE TOOLS:
{compact_tools}

JSON FORMAT:
{{"steps": [{{"tool": "tool_name", "parameters": {{"param": "value"}}, "depends_on": []}}], "description": "brief"}}

EXAMPLES:
User: "open chrome and search youtube for interstellar"
Plan: {{"steps": [{{"tool": "open_application", "parameters": {{"application": "chrome"}}, "depends_on": []}}, {{"tool": "play_media", "parameters": {{"query": "interstellar", "app": "youtube"}}, "depends_on": [0]}}], "description": "Search YouTube"}}

User: "launch edge and search the web for python tutorials"
Plan: {{"steps": [{{"tool": "open_application", "parameters": {{"application": "edge"}}, "depends_on": []}}, {{"tool": "web_search", "parameters": {{"query": "python tutorials"}}, "depends_on": [0]}}], "description": "Search web"}}

User: "open display settings and then turn on dark mode"
Plan: {{"steps": [{{"tool": "open_settings", "parameters": {{"page": "display"}}, "depends_on": []}}, {{"tool": "personalization", "parameters": {{"feature": "theme", "mode": "dark"}}, "depends_on": [0]}}], "description": "Open display settings and enable dark mode"}}

User: "put computer to sleep"
Plan: {{"steps": [{{"tool": "sleep", "parameters": {{}}, "depends_on": []}}], "description": "Sleep computer"}}

User: "turn bluetooth on"
Plan: {{"steps": [{{"tool": "bluetooth", "parameters": {{"action": "enable"}}, "depends_on": []}}], "description": "Enable Bluetooth"}}

User: "search the web for news"
Plan: {{"steps": [{{"tool": "web_search", "parameters": {{"query": "news"}}, "depends_on": []}}], "description": "Search web for news"}}

User: "find resume.pdf"
Plan: {{"steps": [{{"tool": "find_file", "parameters": {{"pattern": "resume.pdf"}}, "depends_on": []}}], "description": "Find resume.pdf"}}

User: "list files in c:\\projects"
Plan: {{"steps": [{{"tool": "file_operation", "parameters": {{"action": "list_directory", "path": "c:\\projects"}}, "depends_on": []}}], "description": "List directory"}}

User: "create folder reports"
Plan: {{"steps": [{{"tool": "file_operation", "parameters": {{"action": "create_folder", "path": "reports"}}, "depends_on": []}}], "description": "Create folder"}}

User: "delete file old_notes.txt"
Plan: {{"steps": [{{"tool": "file_operation", "parameters": {{"action": "delete_file", "path": "old_notes.txt"}}, "depends_on": []}}], "description": "Delete file"}}

User: "make me a sandwich"
Plan: {{"steps": [], "description": "Unsupported"}}

User request: "{user_text}"{context_str}
Plan:"""

    def _build_planning_messages(
        self,
        user_text: str,
        intent: IntentResult,
        available_tools: List[Dict[str, Any]],
        context: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, str]]:
        """Build ordered system + few-shot chat turns for the LLM."""
        compact_tools = format_compact_tools(available_tools)
        context_str = ""
        if context:
            context_str = f" Context: {json.dumps(context)}"

        system_msg = f"""You are Nova's command planner. Output JSON execution plans only.
Never output markdown or explanations. Only valid JSON.
Create ONLY steps directly required to satisfy the user's request. Do NOT invent preparatory, verification, or extra steps (such as opening folders or reading screens) unless explicitly requested.
For single-step plans, "depends_on" must always be []. For compound multi-step plans, step 1 depends on step 0 ("depends_on": [0]).
If request is ambiguous without context (such as "open it", "close that", "do something", "search for that"), physical, impossible, or has no matching tool, return {{"steps": [], "description": "Unsupported"}}.
Rules:
- To open or launch apps (e.g. Spotify, Chrome, Edge, Notepad): use tool "open_application" with application. Never use open_browser for applications.
- For Bluetooth: use tool "bluetooth" with action "enable" or "disable". Never use shutdown.
- For Wi-Fi: use tool "wifi" with action "enable" or "disable". Never use shutdown.
- For Lock: use tool "lock". Never use shutdown or restart.
- For Sleep: use tool "sleep" with parameters {{}}. Never use shutdown or restart.
- For Shutdown/Restart: only use when explicitly requested to turn off or reboot the computer. Parameters must be {{}}. Never use reason or extra arguments.
- For finding files or documents: use tool "find_file" with pattern.
- For file and folder operations (list directory, file info, open file, create folder, create file, rename, copy, move, delete file): use tool "file_operation" with action ("list_directory", "get_file_info", "open_file", "create_folder", "create_file", "rename_file", "copy_file", "move_file", "delete_file"). Never use file_operation for open_folder or find_file. Never use overwrite=true.
- For opening folders in Windows File Explorer: use tool "open_folder" with path.
- Any request mentioning YouTube or Spotify: use tool "play_media" with query and app ("youtube" or "spotify"). Never use web_search if the user mentions YouTube or Spotify.
- For web search or browsing queries: use tool "web_search" with query.
- For opening settings pages: use tool "open_settings" with page (e.g. "display", "wifi", "sound", "default_apps"). Never use open_application for settings.
- For personalization (theme, taskbar, wallpaper): use tool "personalization" with feature ("theme", "taskbar", or "wallpaper"). For theme use mode ("dark" or "light"). For taskbar use alignment ("left" or "center"). For wallpaper use path.
- For display control (brightness, resolution, refresh rate, orientation, display info, night light): use tool "display" with action ("get_brightness", "set_brightness", "increase_brightness", "decrease_brightness", "get_display_info", "get_resolution", "set_resolution", "get_refresh_rate", "set_refresh_rate", "get_orientation", "set_orientation", "night_light"). Never use open_settings when asked to change or inspect display state directly.
- For audio control (volume, mute, unmute, microphone, output devices, default device): use tool "audio" with action ("get_volume", "set_volume", "increase_volume", "decrease_volume", "mute", "unmute", "list_outputs", "list_inputs", "get_mic_status", "set_mic_volume", "mute_mic", "unmute_mic", "set_default_output"). Never use open_settings when asked to change or inspect audio state directly.
- For Windows window and desktop management (minimize, maximize, restore, snap, focus, close, show desktop, list, get active window): use tool "window" with action ("show_desktop", "restore_all", "minimize", "maximize", "restore", "snap", "focus", "close", "list", "get_active"). For snap use position ("left", "right", "top", "bottom", "center"). Never use open_application for switching or focusing existing windows.
- For ambiguous commands with unclear targets like "it" or "that": return {{"steps": [], "description": "Unsupported"}}.

AVAILABLE TOOLS:
{compact_tools}

JSON FORMAT:
{{"steps": [{{"tool": "tool_name", "parameters": {{"param": "value"}}, "depends_on": []}}], "description": "brief"}}"""

        return [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": "open chrome and search youtube for interstellar"},
            {"role": "assistant", "content": '{"steps": [{"tool": "open_application", "parameters": {"application": "chrome"}, "depends_on": []}, {"tool": "play_media", "parameters": {"query": "interstellar", "app": "youtube"}, "depends_on": [0]}], "description": "Search YouTube"}'},
            {"role": "user", "content": "launch edge and search the web for python tutorials"},
            {"role": "assistant", "content": '{"steps": [{"tool": "open_application", "parameters": {"application": "edge"}, "depends_on": []}, {"tool": "web_search", "parameters": {"query": "python tutorials"}, "depends_on": [0]}], "description": "Search web"}'},
            {"role": "user", "content": "open display settings and then turn on dark mode"},
            {"role": "assistant", "content": '{"steps": [{"tool": "open_settings", "parameters": {"page": "display"}, "depends_on": []}, {"tool": "personalization", "parameters": {"feature": "theme", "mode": "dark"}, "depends_on": [0]}], "description": "Open display settings and enable dark mode"}'},
            {"role": "user", "content": "put computer to sleep"},
            {"role": "assistant", "content": '{"steps": [{"tool": "sleep", "parameters": {}, "depends_on": []}], "description": "Sleep computer"}'},
            {"role": "user", "content": "turn bluetooth on"},
            {"role": "assistant", "content": '{"steps": [{"tool": "bluetooth", "parameters": {"action": "enable"}, "depends_on": []}], "description": "Enable Bluetooth"}'},
            {"role": "user", "content": "search the web for news"},
            {"role": "assistant", "content": '{"steps": [{"tool": "web_search", "parameters": {"query": "news"}, "depends_on": []}], "description": "Search web for news"}'},
            {"role": "user", "content": "find resume.pdf"},
            {"role": "assistant", "content": '{"steps": [{"tool": "find_file", "parameters": {"pattern": "resume.pdf"}, "depends_on": []}], "description": "Find resume.pdf"}'},
            {"role": "user", "content": "make me a sandwich"},
            {"role": "assistant", "content": '{"steps": [], "description": "Unsupported"}'},
            {"role": "user", "content": f"{user_text}{context_str}"},
        ]

    def _is_deterministic_safe(
        self,
        user_text: str,
        intent: IntentResult,
        context: Optional[Dict[str, Any]],
    ) -> bool:
        """
        Determine whether a command is demonstrably safe for deterministic single-step planning.
        Rules:
        1. Context must be empty (no previous step context, not marked potentially_multi_step).
        2. Intent confidence must meet or exceed confidence threshold.
        3. Intent entities must not flag compound command.
        4. User text must not be a compound command.
        5. User text must be demonstrably compatible with the single intent.
        When uncertain: return False (route to LLM planning).
        """
        if context and (context.get("potentially_multi_step") or context.get("previous")):
            return False

        if intent.confidence < self.confidence_threshold:
            return False

        if intent.entities and intent.entities.get("is_compound"):
            return False

        if is_compound_command(user_text):
            return False

        # Intent-specific demonstrable compatibility check
        intent_cat = intent.category.value
        text_clean = user_text.strip().lower()

        known_standard_apps = {
            "chrome", "google chrome", "edge", "microsoft edge", "firefox",
            "notepad", "calculator", "terminal", "powershell", "cmd",
            "vscode", "vs code", "visual studio code", "word", "excel",
            "powerpoint", "outlook", "teams", "spotify", "explorer",
        }

        if intent_cat in ("open_application", "open_browser"):
            app = (intent.entities or {}).get("application", "").strip().lower()
            if not app or app not in known_standard_apps:
                return False
            pattern = rf"^(?:(?:open|launch|start|run)\s+)?(?:the\s+|an\s+|a\s+)?{re.escape(app)}(?:\s+(?:app|application|program))?$"
            if not re.match(pattern, text_clean):
                return False
            return True

        if intent_cat == "close_application":
            app = (intent.entities or {}).get("application", "").strip().lower()
            if not app or app not in known_standard_apps:
                return False
            pattern = rf"^(?:close|quit|exit|kill)\s+(?:the\s+|an\s+|a\s+)?{re.escape(app)}(?:\s+(?:app|application|program))?$"
            if not re.match(pattern, text_clean):
                return False
            return True

        if intent_cat == "set_volume":
            action = (intent.entities or {}).get("action")
            if not action:
                return False
            return True

        if intent_cat == "set_brightness":
            action = (intent.entities or {}).get("action")
            if not action or action not in ("set", "increase", "decrease"):
                return False
            return True

        if intent_cat == "display":
            action = (intent.entities or {}).get("action")
            valid_actions = {
                "get_brightness", "set_brightness", "increase_brightness", "decrease_brightness",
                "get_display_info", "get_resolution", "set_resolution",
                "get_refresh_rate", "set_refresh_rate",
                "get_orientation", "set_orientation", "night_light",
            }
            if not action or action not in valid_actions:
                return False
            return True

        if intent_cat == "audio":
            action = (intent.entities or {}).get("action")
            valid_actions = {
                "get_volume", "set_volume", "increase_volume", "decrease_volume",
                "mute", "unmute", "list_outputs", "list_inputs",
                "get_mic_status", "set_mic_volume", "mute_mic", "unmute_mic",
                "set_default_output",
            }
            if not action or action not in valid_actions:
                return False
            return True

        if intent_cat == "bluetooth":
            action = (intent.entities or {}).get("action")
            return action in ("enable", "disable", "status")

        if intent_cat == "wifi":
            action = (intent.entities or {}).get("action")
            if action in ("enable", "disable", "status"):
                return True
            if action == "connect":
                ssid = (intent.entities or {}).get("ssid", "").strip()
                return bool(ssid)
            return False

        if intent_cat == "network":
            action = (intent.entities or {}).get("action")
            if action in ("status", "dns", "interfaces"):
                return True
            if action == "ping":
                host = (intent.entities or {}).get("host", "").strip()
                return bool(host)
            return False

        if intent_cat == "lock":
            return True

        if intent_cat == "find_file":
            pattern = (intent.entities or {}).get("pattern", "").strip().lower()
            if not pattern or pattern in ("it", "that", "something", "anything", "document", "file"):
                return False
            return True

        if intent_cat in ("screen_read", "screen.read"):
            return True

        if intent_cat in ("shutdown", "restart", "sleep"):
            return True

        if intent_cat == "file_operation":
            action = (intent.entities or {}).get("action")
            valid_actions = {
                "list_directory", "get_file_info", "open_file",
                "create_folder", "create_file", "rename_file",
                "copy_file", "move_file", "delete_file",
            }
            if not action or action not in valid_actions:
                return False
            entities = intent.entities or {}
            if action in ("get_file_info", "open_file", "create_folder", "delete_file"):
                p = entities.get("path")
                return bool(p and isinstance(p, str) and p.strip())
            if action == "create_file":
                p = entities.get("path")
                return bool(p and isinstance(p, str) and p.strip())
            if action in ("rename_file", "copy_file", "move_file"):
                src = entities.get("source")
                dst = entities.get("destination")
                return bool(src and dst and isinstance(src, str) and isinstance(dst, str) and src.strip() and dst.strip())
            if action == "list_directory":
                return True
            return False

        if intent_cat == "open_settings":
            page = (intent.entities or {}).get("page", "").strip().lower()
            from nova.skills.system.settings import SETTINGS_URI_MAP, SETTINGS_ALIASES
            if not page:
                return False
            return page in SETTINGS_URI_MAP or page in SETTINGS_ALIASES or page == "settings"

        if intent_cat == "personalization":
            feature = (intent.entities or {}).get("feature", "").strip().lower()
            if feature == "theme":
                mode = (intent.entities or {}).get("mode", "").strip().lower()
                return mode in ("dark", "light")
            elif feature == "taskbar":
                alignment = (intent.entities or {}).get("alignment", "").strip().lower()
                return alignment in ("left", "center")
            elif feature == "wallpaper":
                path = (intent.entities or {}).get("path", "").strip()
                return bool(path)
            return False

        if intent_cat == "window":
            action = (intent.entities or {}).get("action")
            valid_actions = {
                "show_desktop", "restore_all", "minimize", "maximize",
                "restore", "snap", "focus", "close", "list", "get_active",
            }
            if not action or action not in valid_actions:
                return False
            if action == "snap":
                pos = (intent.entities or {}).get("position")
                return pos in ("left", "right", "top", "bottom", "center")
            return True

        return False

    async def plan(
        self,
        user_text: str,
        intent: IntentResult,
        context: Optional[Dict[str, Any]] = None,
    ) -> ExecutionPlan:
        """
        Generate an execution plan from user text and intent.
        
        Args:
            user_text: Raw user input
            intent: Classified intent result
            context: Optional execution context from previous steps
            
        Returns:
            ExecutionPlan with validated steps
        """
        # Normalize noisy STT on incoming text first
        from .intent_classifier import normalize_noisy_stt
        user_text = normalize_noisy_stt(user_text)

        available_tools = self._get_available_tools()
        
        # If only one tool matches the intent and the command is demonstrably safe, return single-step plan directly
        intent_tool = intent.category.value
        if intent_tool == "screen_read":
            intent_tool = "screen.read"
        
        matching_tools = [t for t in available_tools if t["tool"] == intent_tool]
        if len(matching_tools) == 1 and self._is_deterministic_safe(user_text, intent, context):
            # Simple single-step case - deterministic fast path (no LLM needed)
            params = dict(intent.entities or {})
            if intent_tool in ("lock", "sleep", "shutdown", "restart"):
                params = {}
            elif intent_tool == "bluetooth":
                params = {"action": params.get("action", "status")}
            elif intent_tool == "wifi":
                w_action = params.get("action", "status")
                if w_action == "connect":
                    params = {"action": "connect", "ssid": params.get("ssid", "")}
                else:
                    params = {"action": w_action}
            elif intent_tool == "network":
                n_action = params.get("action", "status")
                if n_action == "ping":
                    params = {
                        "action": "ping",
                        "host": params.get("host", "8.8.8.8"),
                        "count": int(params.get("count", 4)),
                    }
                else:
                    params = {"action": n_action}
            elif intent_tool in ("open_application", "close_application"):
                params = {"application": params.get("application", "")}
            elif intent_tool == "find_file":
                params = {"pattern": params.get("pattern", "")}
            elif intent_tool == "file_operation":
                valid_params = {}
                f_action = params.get("action", "")
                if f_action:
                    valid_params["action"] = f_action
                if "path" in params and params["path"]:
                    valid_params["path"] = params["path"]
                if "source" in params and params["source"]:
                    valid_params["source"] = params["source"]
                if "destination" in params and params["destination"]:
                    valid_params["destination"] = params["destination"]
                if "content" in params and params["content"] is not None:
                    valid_params["content"] = str(params["content"])
                params = valid_params
            elif intent_tool == "open_settings":
                page = params.get("page", "")
                from nova.skills.system.settings import resolve_settings_page
                canonical_page = resolve_settings_page(page) or page
                params = {"page": canonical_page}
            elif intent_tool == "personalization":
                feature = params.get("feature", "")
                if feature == "theme":
                    params = {"feature": "theme", "mode": params.get("mode", "dark")}
                elif feature == "taskbar":
                    params = {"feature": "taskbar", "alignment": params.get("alignment", "center")}
                elif feature == "wallpaper":
                    params = {"feature": "wallpaper", "path": params.get("path", "")}
            elif intent_tool == "set_brightness":
                b_action = params.get("action", "set")
                if b_action == "set":
                    params = {"action": "set", "level": int(params.get("level", 50))}
                else:
                    params = {"action": b_action, "amount": int(params.get("amount", 10))}
            elif intent_tool == "display":
                valid_params = {}
                for k, v in params.items():
                    if k in ("action", "level", "amount", "width", "height", "refresh_rate", "orientation"):
                        valid_params[k] = v
                params = valid_params
            elif intent_tool == "audio":
                valid_params = {}
                for k, v in params.items():
                    if k in ("action", "level", "amount", "device_name"):
                        valid_params[k] = v
                params = valid_params
            elif intent_tool == "window":
                valid_params = {}
                w_action = params.get("action", "")
                if w_action:
                    valid_params["action"] = w_action
                if "target" in params and params["target"]:
                    valid_params["target"] = params["target"]
                if "position" in params and params["position"]:
                    valid_params["position"] = params["position"]
                params = valid_params

            plan = ExecutionPlan(
                steps=[
                    PlanStep(
                        tool=intent_tool,
                        parameters=params,
                    )
                ],
                description=f"Execute {intent_tool}",
            )
            return self._validator.validate(plan)

        # Use LLM for multi-step planning
        planning_messages = self._build_planning_messages(user_text, intent, available_tools, context)
        prompt = self._build_planning_prompt(user_text, intent, available_tools, context)
        
        try:
            llm_response = await self._llm_manager.process(
                text=prompt,
                task_type="plan",
                context={"extra_context": "Generate a valid JSON plan only.", "messages": planning_messages},
            )
        except (PlanningError, PlanValidationError):
            raise
        except Exception as exc:
            logger.error(f"Planner LLM generation or parsing failed: {exc}")
            raise PlanningError(f"LLM planning failed: {exc}") from exc

        # Extract structured ExecutionPlan directly from the manager response
        plan = getattr(llm_response, "plan", None)
        if not isinstance(plan, ExecutionPlan):
            # If a mock or raw response provided raw_content or response_text as str,
            # use LLMParser to parse it cleanly
            raw_text = None
            if isinstance(llm_response, str) and llm_response.strip():
                raw_text = llm_response
            else:
                raw_attr = getattr(llm_response, "raw_content", None)
                if isinstance(raw_attr, str) and raw_attr.strip():
                    raw_text = raw_attr
                else:
                    resp_attr = getattr(llm_response, "response_text", None)
                    if isinstance(resp_attr, str) and resp_attr.strip():
                        raw_text = resp_attr

            if raw_text:
                from nova.llm.parser import LLMParser
                parser = LLMParser()
                try:
                    plan = parser.parse_plan(raw_text)
                except Exception as e:
                    raise PlanningError(f"Failed to parse execution plan from LLM response: {e}")
            else:
                raise PlanningError(f"LLM Manager did not return a valid ExecutionPlan object. Got: {type(plan).__name__}")

        # Validate with PlanValidator (checks tools, params, dependencies, cycles)
        return self._validator.validate(plan)


# Global singleton
_planner: Optional[Planner] = None


def get_planner() -> Planner:
    """Get or create global planner instance."""
    global _planner
    if _planner is None:
        _planner = Planner()
    return _planner