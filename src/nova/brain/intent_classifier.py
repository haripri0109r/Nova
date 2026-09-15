"""
Intent Classification abstraction and placeholder implementation.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from .models import RecognizedInput, IntentResult
from .types import IntentCategory, ConfidenceLevel, IntentClassifierConfig
from .exceptions import IntentClassificationError
from .compound import extract_clean_application_target, is_compound_command


def normalize_noisy_stt(text: str) -> str:
    """
    Conservative speech-to-text normalization for common Windows assistant commands.
    Transforms obvious phonetic slips and polite conversational prefixes without
    distorting arbitrary user text.
    """
    import re
    if not text:
        return text

    # 1. Strip polite / conversational leading prefixes
    cleaned = re.sub(
        r"^(?:can you|could you|please|would you)\s+",
        "",
        text.strip(),
        flags=re.IGNORECASE,
    ).strip()

    # 2. Conservative acoustic/phonetic replacements for common keywords
    replacements = [
        (r"\bcloze\b", "close"),
        (r"\bturm\b", "turn"),
        (r"\bcrome\b", "chrome"),
        (r"\bincrese\b", "increase"),
        (r"\bdecrese\b", "decrease"),
        (r"\bnote\s+pad\b", "notepad"),
        (r"\bwi-fi\b", "wifi"),
        (r"\bblue\s+tooth\b", "bluetooth"),
        (r"\bturn\s+(.*?)\s+of$", r"turn \1 off"),
    ]
    for pattern, repl in replacements:
        cleaned = re.sub(pattern, repl, cleaned, flags=re.IGNORECASE)

    return cleaned.strip()


class BaseIntentClassifier(ABC):
    """Abstract base class for intent classifiers."""

    def __init__(self, config: Optional[IntentClassifierConfig] = None):
        self.config = config or IntentClassifierConfig()
        self._initialized = False

    @abstractmethod
    async def initialize(self) -> bool:
        """Initialize the classifier (load model, warm‑up, etc.)."""
        ...

    @abstractmethod
    async def cleanup(self) -> None:
        """Release resources."""
        ...

    @abstractmethod
    async def classify(self, inp: RecognizedInput) -> IntentResult:
        """Classify the recognized text into an intent."""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Human readable name of the provider."""
        ...

    @property
    def is_initialized(self) -> bool:
        return self._initialized


class PlaceholderIntentClassifier(BaseIntentClassifier):
    """No‑op classifier used for testing / offline mode."""

    def __init__(self, config: Optional[IntentClassifierConfig] = None):
        super().__init__(config)

    async def initialize(self) -> bool:
        self._initialized = True
        return True

    async def cleanup(self) -> None:
        self._initialized = False

    async def classify(self, inp: RecognizedInput) -> IntentResult:
        import re
        raw_text = inp.text.strip()
        normalized_text = normalize_noisy_stt(raw_text)
        text = normalized_text.lower()
        entities: Dict[str, Any] = {}
        conf = 0.5
        cat = IntentCategory.GENERAL_CONVERSATION

        # 0. Task Management (TASK_CONTROL and TASK_QUERY)
        # Evaluated first to ensure deterministic precedence over generic patterns.
        task_control_action = None
        task_query_action = None
        task_id = None
        step_index = None
        filter_status = None

        # Retry step: "retry step", "retry that step", "retry step 2", "retry step #2", "redo step 2",
        # with optional confirmation keyword: "retry step 2 confirm", "confirm retry step 2", "retry step confirm"
        is_confirmed = False
        m_retry = re.match(r"^(confirm\s+)?(?:retry|redo)(?:\s+(?:that|the))?\s+step(?:\s+(?:#\s*)?(\d+))?(?:\s+(?:for|of|in)?\s+task\s+([a-zA-Z0-9_-]+))?(\s+confirm)?$", text)
        if m_retry:
            task_control_action = "retry_step"
            prefix_confirm = bool(m_retry.group(1))
            suffix_confirm = bool(m_retry.group(4))
            if prefix_confirm or suffix_confirm:
                is_confirmed = True
            if m_retry.group(2):
                step_index = int(m_retry.group(2))
            if m_retry.group(3):
                task_id = m_retry.group(3)

        # Skip step: "skip step", "skip that step", "skip step 2", "skip step #3"
        m_skip = re.match(r"^skip(?:\s+(?:that|the))?\s+step(?:\s+(?:#\s*)?(\d+))?(?:\s+(?:for|of|in)?\s+task\s+([a-zA-Z0-9_-]+))?$", text)
        if not task_control_action and m_skip:
            task_control_action = "skip_step"
            if m_skip.group(1):
                step_index = int(m_skip.group(1))
            if m_skip.group(2):
                task_id = m_skip.group(2)

        # Pause task: "pause", "pause task", "pause my task", "pause the task", "pause current task", "pause task 491c", "pause task #491c"
        if not task_control_action:
            if text == "pause":
                task_control_action = "pause"
            else:
                m_pause = re.match(r"^pause\s+(?:(?:the|my|current)\s+)?task(?:\s*[:#]?\s*([a-zA-Z0-9_-]+))?$", text)
                if m_pause:
                    task_control_action = "pause"
                    if m_pause.group(1):
                        task_id = m_pause.group(1)
                else:
                    m_pause_id = re.match(r"^pause\s+(task-[\w-]+|[0-9a-f]{4,})$", text)
                    if m_pause_id:
                        task_control_action = "pause"
                        task_id = m_pause_id.group(1)

        # Resume task: "resume", "resume task", "continue task", "resume my task", "resume task 491c", "continue task 491c"
        if not task_control_action:
            if text == "resume":
                task_control_action = "resume"
            else:
                m_resume = re.match(r"^(?:resume|continue)\s+(?:(?:the|my|current)\s+)?task(?:\s*[:#]?\s*([a-zA-Z0-9_-]+))?$", text)
                if m_resume:
                    task_control_action = "resume"
                    if m_resume.group(1):
                        task_id = m_resume.group(1)
                else:
                    m_resume_id = re.match(r"^resume\s+(task-[\w-]+|[0-9a-f]{4,})$", text)
                    if m_resume_id:
                        task_control_action = "resume"
                        task_id = m_resume_id.group(1)

        # Cancel task: "cancel", "cancel task", "cancel my task", "stop task", "abort task", "cancel task 491c", "stop task 491c", "abort task 491c"
        if not task_control_action:
            if text == "cancel":
                task_control_action = "cancel"
            else:
                m_cancel = re.match(r"^(?:cancel|stop|abort)\s+(?:(?:the|my|current)\s+)?task(?:\s*[:#]?\s*([a-zA-Z0-9_-]+))?$", text)
                if m_cancel:
                    task_control_action = "cancel"
                    if m_cancel.group(1):
                        task_id = m_cancel.group(1)
                else:
                    m_cancel_id = re.match(r"^cancel\s+(task-[\w-]+|[0-9a-f]{4,})$", text)
                    if m_cancel_id:
                        task_control_action = "cancel"
                        task_id = m_cancel_id.group(1)

        # Confirm / resume execution of pending high-risk action:
        # "confirm", "confirm task", "confirm shutdown", "confirm restart",
        # "confirm shutdown <token>", "confirm <token>"
        m_confirm = re.match(
            r"^confirm(?:\s+(shutdown|restart|the\s+task|task))?(?:\s+([a-zA-Z0-9_-]+))?$",
            text,
        )
        if not task_control_action and m_confirm:
            task_control_action = "resume"
            is_confirmed = True
            tool_target = m_confirm.group(1)
            if tool_target in ("shutdown", "restart"):
                entities["target_tool"] = tool_target
            token_val = m_confirm.group(2)
            if token_val:
                entities["confirmation_token"] = token_val

        # Task query - Status: "task status", "what is my task doing?", "how is my task going?", "status of task 491c", "status of task"
        if not task_control_action:
            m_status_1 = re.match(r"^(?:task\s+status|status\s+of\s+(?:the\s+|my\s+|current\s+)?task|task\s+progress)(?:\s*[:#]?\s*([a-zA-Z0-9_-]+))?$", text)
            m_status_2 = re.match(r"^(?:what|how)\s+is\s+(?:the\s+|my\s+|current\s+)?task(?:\s+([a-zA-Z0-9_-]+))?\s+(?:doing|going|progressing)\??$", text)
            m_status_3 = re.match(r"^status\s+(?:task\s+)?([a-zA-Z0-9_-]+)$", text)
            if m_status_1:
                task_query_action = "status"
                if m_status_1.group(1):
                    task_id = m_status_1.group(1)
            elif m_status_2:
                task_query_action = "status"
                if m_status_2.group(1):
                    task_id = m_status_2.group(1)
            elif m_status_3 and m_status_3.group(1) not in ("screen", "volume"):
                task_query_action = "status"
                task_id = m_status_3.group(1)

        # Task query - List: "list tasks", "show tasks", "show running tasks", "what tasks are running?", "show paused tasks", "tasks list"
        if not task_control_action and not task_query_action:
            m_list_1 = re.match(r"^(?:list|show|get|display)\s+(?:all\s+)?(?:(running|paused|completed|failed|cancelled)\s+)?tasks$", text)
            m_list_2 = re.match(r"^what\s+tasks\s+are\s+(running|paused|active|pending)\??$", text)
            m_list_3 = re.match(r"^(?:list|show)\s+(?:all\s+)?tasks\s+(?:that\s+are\s+)?(running|paused|completed|failed|cancelled)$", text)
            if text in ("tasks", "tasks list", "list tasks", "show tasks"):
                task_query_action = "list"
            elif m_list_1:
                task_query_action = "list"
                if m_list_1.group(1):
                    filter_status = m_list_1.group(1)
            elif m_list_2:
                task_query_action = "list"
                status_word = m_list_2.group(1)
                filter_status = "running" if status_word == "active" else status_word
            elif m_list_3:
                task_query_action = "list"
                if m_list_3.group(1):
                    filter_status = m_list_3.group(1)

        if task_control_action:
            cat = IntentCategory.TASK_CONTROL
            conf = 0.95
            entities["action"] = task_control_action
            if task_id:
                entities["task_id"] = task_id
            if step_index is not None:
                entities["step_index"] = step_index
            if is_confirmed:
                entities["confirmed"] = True
        elif task_query_action:
            cat = IntentCategory.TASK_QUERY
            conf = 0.95
            entities["action"] = task_query_action
            if task_id:
                entities["task_id"] = task_id
            if filter_status:
                entities["filter_status"] = filter_status

        # 1. Lock workstation (evaluated before screen read so 'lock the screen' locks)
        elif re.match(r"^(?:lock|lock\s+(?:the\s+|my\s+)?(?:pc|computer|screen|workstation|system))$", text):
            cat = IntentCategory.LOCK
            conf = 0.95
            entities = {}

        # 2. Screen reading
        elif (any(k in text for k in ("what's on", "what is on", "read my screen", "read screen")) or text == "screen") and not any(k in text for k in ("resolution", "refresh", "orientation", "brightness", "dim", "brighten", "lock")):
            cat = IntentCategory.SCREEN_READ
            conf = 0.9

        # 3. Audio - Microphone and device control
        elif (
            any(k in text for k in ("microphone", "mic", "speakers", "audio devices", "output devices", "input devices", "headphones"))
        ) and "settings" not in text and not any(text.startswith(p) for p in ("find ", "search ", "locate ", "open ", "launch ", "run ")):
            cat = IntentCategory.AUDIO
            conf = 0.95
            is_compound = is_compound_command(text)

            if any(k in text for k in ("mute microphone", "mute mic")):
                entities = {"action": "mute_mic"}
            elif any(k in text for k in ("unmute microphone", "unmute mic")):
                entities = {"action": "unmute_mic"}
            elif any(k in text for k in ("list microphones", "what microphone", "which microphone", "input devices", "list inputs", "what input")):
                entities = {"action": "list_inputs"}
            elif any(k in text for k in ("list speakers", "list audio", "what speakers", "output devices", "list outputs", "what output")):
                entities = {"action": "list_outputs"}
            elif any(k in text for k in ("mic volume", "microphone volume")):
                m = re.search(r"(\d+)", text)
                if m and any(k in text for k in ("set", "to", "at", "%", "percent")):
                    entities = {"action": "set_mic_volume", "level": int(m.group(1))}
                else:
                    entities = {"action": "get_mic_status"}
            elif any(k in text for k in ("switch to", "make", "set output to", "change output to", "default output")):
                # Extract target device name
                m_dev = re.search(r"(?:switch to|make|set output to|change output to)\s+(.+?)(?:\s+(?:as\s+)?default)?$", text)
                dev_target = m_dev.group(1).strip() if m_dev else "speakers"
                entities = {"action": "set_default_output", "device_name": dev_target}
            else:
                entities = {"action": "get_mic_status"}

            if is_compound:
                entities["is_compound"] = True
                entities["raw_input"] = text
                conf = 0.5

        # 4. Volume control
        elif (
            any(k in text for k in ("volume", "mute", "unmute", "louder", "quieter"))
            or ("sound" in text and not any(text.startswith(p) for p in ("open ", "launch ", "start ", "run ", "find ", "search ", "locate ")))
        ) and "settings" not in text and not any(text.startswith(p) for p in ("find ", "search ", "locate ")):
            cat = IntentCategory.SET_VOLUME
            conf = 0.9
            is_compound = is_compound_command(text)

            if any(k in text for k in ("what's my volume", "what is my volume", "current volume", "check volume", "what is the volume")):
                entities["action"] = "get_volume"
            elif "mute" in text and "unmute" not in text:
                entities["action"] = "mute"
            elif "unmute" in text:
                entities["action"] = "unmute"
            elif any(k in text for k in ("decrease", "lower", "reduce", "down", "quieter")):
                entities["action"] = "decrease"
                m = re.search(r"(\d+)", text)
                entities["amount"] = int(m.group(1)) if m else 10
            elif any(k in text for k in ("increase", "raise", "up", "louder")):
                entities["action"] = "increase"
                m = re.search(r"(\d+)", text)
                entities["amount"] = int(m.group(1)) if m else 10
            else:
                m = re.search(r"(\d+)", text)
                if m:
                    entities["action"] = "set"
                    entities["level"] = int(m.group(1))
                else:
                    entities["action"] = "get_volume"

            if is_compound:
                entities["is_compound"] = True
                entities["raw_input"] = text
                conf = 0.5

        # 5. Display - Resolution, Refresh rate, Orientation, Display info, Night Light
        elif (
            any(k in text for k in ("resolution", "refresh rate", "orientation", "display info", "how many monitors", "monitors do i have", "night light", "rotate screen", "portrait", "landscape"))
            or ("display" in text and any(k in text for k in ("info", "information", "count", "monitors", "primary")))
        ) and "settings" not in text and not any(text.startswith(p) for p in ("find ", "search ", "locate ")):
            cat = IntentCategory.DISPLAY
            conf = 0.95
            is_compound = is_compound_command(text)

            if "night light" in text:
                entities = {"action": "night_light"}
            elif "resolution" in text:
                m_res = re.search(r"(\d{3,4})\s*(?:by|x|\*)\s*(\d{3,4})", text)
                if m_res and any(k in text for k in ("set", "change", "to")):
                    entities = {
                        "action": "set_resolution",
                        "width": int(m_res.group(1)),
                        "height": int(m_res.group(2)),
                    }
                else:
                    entities = {"action": "get_resolution"}
            elif "refresh rate" in text or "refresh" in text:
                m_hz = re.search(r"(\d{2,3})\s*(?:hz|hertz)?", text)
                if m_hz and any(k in text for k in ("set", "change", "to")):
                    entities = {"action": "set_refresh_rate", "refresh_rate": int(m_hz.group(1))}
                else:
                    entities = {"action": "get_refresh_rate"}
            elif "orientation" in text or any(k in text for k in ("portrait", "landscape", "rotate screen")):
                m_orient = re.search(r"(landscape_flipped|portrait_flipped|landscape|portrait)", text)
                if m_orient and any(k in text for k in ("set", "change", "rotate", "to")):
                    entities = {"action": "set_orientation", "orientation": m_orient.group(1)}
                elif m_orient:
                    entities = {"action": "set_orientation", "orientation": m_orient.group(1)}
                else:
                    entities = {"action": "get_orientation"}
            else:
                entities = {"action": "get_display_info"}

            if is_compound:
                entities["is_compound"] = True
                entities["raw_input"] = text
                conf = 0.5

        # 6. Brightness control
        elif any(k in text for k in ("brightness", "dim screen", "brighten screen", "brighter", "dimmer")) and "settings" not in text:
            cat = IntentCategory.SET_BRIGHTNESS
            conf = 0.95
            is_compound = is_compound_command(text)

            if any(k in text for k in ("what's my brightness", "what is my brightness", "current brightness", "check brightness", "what is the brightness")):
                entities = {"action": "get_brightness"}
            elif any(k in text for k in ("decrease", "lower", "reduce", "down", "dim", "dimmer")):
                m = re.search(r"(\d+)", text)
                amt = int(m.group(1)) if m else 10
                entities = {"action": "decrease", "amount": amt}
            elif any(k in text for k in ("increase", "raise", "up", "brighten", "brighter")):
                m = re.search(r"(\d+)", text)
                amt = int(m.group(1)) if m else 10
                entities = {"action": "increase", "amount": amt}
            else:
                m = re.search(r"(\d+)", text)
                if m:
                    entities = {"action": "set", "level": int(m.group(1))}
                else:
                    entities = {"action": "get_brightness"}

            if is_compound:
                entities["is_compound"] = True
                entities["raw_input"] = text
                conf = 0.5

        # 5. Bluetooth control
        elif any(k in text for k in ("bluetooth", "blue tooth")) and "settings" not in text:
            cat = IntentCategory.BLUETOOTH
            conf = 0.95
            is_compound = is_compound_command(text)
            if any(k in text for k in ("status", "check", "state", "is bluetooth", "what is bluetooth")):
                entities = {"action": "status"}
            elif any(k in text for k in ("off", "disable", "turn off")):
                entities = {"action": "disable"}
            elif any(k in text for k in ("on", "enable", "turn on", "toggle on")):
                entities = {"action": "enable"}
            else:
                entities = {"action": "status"}

            if is_compound:
                entities["is_compound"] = True
                entities["raw_input"] = text
                conf = 0.5

        # 6. Wi-Fi control
        elif any(k in text for k in ("wifi", "wi-fi", "wireless")) and "settings" not in text:
            cat = IntentCategory.WIFI
            conf = 0.95
            is_compound = is_compound_command(text)
            m_connect = re.search(r"connect(?:\s+to)?\s+(?:wifi\s+|network\s+)?([a-zA-Z0-9_\-\.\@\!#]+)", text)
            if any(k in text for k in ("connect to", "connect wifi", "join network")) or (m_connect and "connect" in text and not any(k in text for k in ("disconnect", "turn off", "disable"))):
                ssid_target = m_connect.group(1).strip() if m_connect else ""
                entities = {"action": "connect", "ssid": ssid_target}
            elif any(k in text for k in ("status", "check", "state", "connected to", "which wifi", "current wifi", "is wifi")):
                entities = {"action": "status"}
            elif any(k in text for k in ("off", "disable", "turn off", "disconnect")):
                entities = {"action": "disable"}
            elif any(k in text for k in ("on", "enable", "turn on", "toggle on")):
                entities = {"action": "enable"}
            else:
                entities = {"action": "status"}

            if is_compound:
                entities["is_compound"] = True
                entities["raw_input"] = text
                conf = 0.5

        # 6.5 Network diagnostics & status
        elif (
            any(k in text for k in ("network", "internet", "ping", "ip address", "dns server", "my ip"))
            or ("ip" in text and any(k in text for k in ("what is", "check", "get", "show")))
        ) and "settings" not in text and not any(text.startswith(p) for p in ("find ", "search ", "locate ", "open ", "launch ")):
            cat = IntentCategory.NETWORK
            conf = 0.95
            is_compound = is_compound_command(text)
            if "ping" in text:
                m_ping = re.search(r"ping\s+([A-Za-z0-9\.\-]+)", text)
                target_host = m_ping.group(1).strip() if m_ping else "8.8.8.8"
                m_cnt = re.search(r"(?:-n|count|\*)\s*(\d+)", text)
                cnt = int(m_cnt.group(1)) if m_cnt else 4
                entities = {"action": "ping", "host": target_host, "count": cnt}
            elif any(k in text for k in ("dns", "dns servers")):
                entities = {"action": "dns"}
            elif any(k in text for k in ("interfaces", "adapters", "network cards")):
                entities = {"action": "interfaces"}
            else:
                entities = {"action": "status"}

            if is_compound:
                entities["is_compound"] = True
                entities["raw_input"] = text
                conf = 0.5

        # 7. Personalization (Theme mode, Taskbar alignment, Wallpaper)
        elif (
            any(k in text for k in ("dark mode", "light mode", "theme mode"))
            or (any(k in text for k in ("dark", "light")) and any(k in text for k in ("turn on", "switch to", "enable", "mode", "theme")))
            or ("taskbar" in text and any(k in text for k in ("left", "center", "centre", "align", "move")))
            or any(k in text for k in ("wallpaper", "desktop background"))
        ) and not any(k in text for k in ("settings", "find", "search", "locate")):
            cat = IntentCategory.PERSONALIZATION
            conf = 0.95
            is_compound = is_compound_command(text)

            # Theme detection
            if any(k in text for k in ("dark mode", "light mode", "theme")) or any(k in text for k in ("dark", "light")):
                mode = "dark" if "dark" in text else "light"
                entities = {"feature": "theme", "mode": mode}
            # Taskbar alignment
            elif "taskbar" in text:
                align = "left" if "left" in text else "center"
                entities = {"feature": "taskbar", "alignment": align}
            # Wallpaper
            elif any(k in text for k in ("wallpaper", "desktop background")):
                m_wall = re.search(r"(?:set|change)\s+(?:desktop\s+)?(?:wallpaper|background)\s+(?:to\s+)?(.+)$", raw_text, re.IGNORECASE)
                path_val = m_wall.group(1).strip().strip("\"'") if m_wall else ""
                entities = {"feature": "wallpaper", "path": path_val}

            if is_compound:
                entities["is_compound"] = True
                entities["raw_input"] = text
                conf = 0.5

        # 7.8 Windows Window & Desktop Management (Phase 5.8-E)
        elif (
            text in ("minimize all", "minimize all windows", "minimize everything", "show desktop", "show the desktop")
            or text in ("restore all", "restore all windows", "unminimize all")
            or text.startswith("snap ")
            or text.startswith("switch to ")
            or text.startswith("bring ")
            or any(text.startswith(p) for p in ("focus ", "focus on "))
            or any(text.startswith(p) for p in ("minimize ", "maximize ", "restore "))
            or text in ("minimize", "maximize", "restore", "show desktop", "restore all")
            or any(k in text for k in ("what windows are open", "list open windows", "list windows", "show open windows", "which windows are open", "what window is this", "what is the current window", "what is the active window", "current window", "active window", "what window is active"))
            or re.search(r"\bclose\s+(?:the\s+|this\s+)?window\b", text)
            or re.search(r"\bclose\s+(?:the\s+)?([a-zA-Z0-9_\-\. ]+?)\s+window\b", text)
        ) and not any(k in text for k in ("search", "find", "google", "settings")) and not any(text.startswith(p) for p in ("open ", "launch ", "start ", "run ")):
            cat = IntentCategory.WINDOW
            conf = 0.95
            is_compound = is_compound_command(text)
            entities = {}

            clean_text = text.rstrip("?!.,")

            # 1. Desktop shell toggles
            if clean_text in ("minimize all", "minimize all windows", "minimize everything", "show desktop", "show the desktop"):
                entities = {"action": "show_desktop"}
            elif clean_text in ("restore all", "restore all windows", "unminimize all"):
                entities = {"action": "restore_all"}

            # 2. Window list & active query
            elif any(k in clean_text for k in ("what windows are open", "list open windows", "list windows", "show open windows", "which windows are open", "all open windows")):
                entities = {"action": "list"}
            elif any(k in clean_text for k in ("what window is this", "what is the current window", "what is the active window", "current window", "active window", "what window is active", "which window is active")):
                entities = {"action": "get_active"}

            # 3. Snap window
            elif clean_text.startswith("snap ") or "snap" in clean_text:
                m_snap = re.match(r"^snap(?:\s+(?:the|this))?(?:\s+window)?(?:\s+(.+?))?\s+(?:to\s+)?(?:the\s+)?(left|right|top|bottom|center)$", clean_text)
                if m_snap:
                    raw_target = (m_snap.group(1) or "").strip()
                    pos = m_snap.group(2).strip()
                    target = "active" if not raw_target or raw_target in ("this", "this window", "the window", "it", "current", "current window", "window") else raw_target
                    entities = {"action": "snap", "position": pos, "target": target}
                else:
                    entities = {"action": "snap"}

            # 4. Focus / Switch to window
            elif clean_text.startswith("switch to ") or clean_text.startswith("bring ") or any(clean_text.startswith(p) for p in ("focus ", "focus on ")):
                target = ""
                m_switch = re.match(r"^switch\s+to\s+(?:the\s+)?(?:window\s+)?(.+?)(?:\s+window)?$", clean_text)
                if m_switch:
                    target = m_switch.group(1).strip()
                else:
                    m_bring = re.match(r"^bring\s+(?:the\s+)?(.+?)\s+(?:window\s+)?to\s+(?:the\s+)?front$", clean_text)
                    if m_bring:
                        target = m_bring.group(1).strip()
                    else:
                        m_focus = re.match(r"^focus(?:\s+on)?\s+(?:the\s+)?(?:window\s+)?(.+?)(?:\s+window)?$", clean_text)
                        if m_focus:
                            target = m_focus.group(1).strip()
                if not target or target in ("this", "this window", "the window", "it", "current", "current window", "window"):
                    target = "active"
                entities = {"action": "focus", "target": target}

            # 5. Minimize
            elif clean_text.startswith("minimize"):
                m_min = re.match(r"^minimize(?:\s+(?:the|this))?(?:\s+window)?(?:\s+(.+?))?(?:\s+window)?$", clean_text)
                raw_target = (m_min.group(1) or "").strip() if m_min else ""
                if raw_target in ("all", "all windows", "everything"):
                    entities = {"action": "show_desktop"}
                else:
                    target = "active" if not raw_target or raw_target in ("this", "this window", "the window", "it", "current", "current window", "window") else raw_target
                    entities = {"action": "minimize", "target": target}

            # 6. Maximize
            elif clean_text.startswith("maximize"):
                m_max = re.match(r"^maximize(?:\s+(?:the|this))?(?:\s+window)?(?:\s+(.+?))?(?:\s+window)?$", clean_text)
                raw_target = (m_max.group(1) or "").strip() if m_max else ""
                target = "active" if not raw_target or raw_target in ("this", "this window", "the window", "it", "current", "current window", "window") else raw_target
                entities = {"action": "maximize", "target": target}

            # 7. Restore
            elif clean_text.startswith("restore") or clean_text.startswith("unminimize"):
                m_res = re.match(r"^(?:restore|unminimize)(?:\s+(?:the|this))?(?:\s+window)?(?:\s+(.+?))?(?:\s+window)?$", clean_text)
                raw_target = (m_res.group(1) or "").strip() if m_res else ""
                if raw_target in ("all", "all windows", "everything"):
                    entities = {"action": "restore_all"}
                else:
                    target = "active" if not raw_target or raw_target in ("this", "this window", "the window", "it", "current", "current window", "window") else raw_target
                    entities = {"action": "restore", "target": target}

            # 8. Close window
            elif "close" in clean_text and "window" in clean_text:
                m_cw = re.match(r"^close\s+(?:the\s+|this\s+)?window$", clean_text)
                if m_cw:
                    entities = {"action": "close", "target": "active"}
                else:
                    m_caw = re.match(r"^close\s+(?:the\s+)?(.+?)\s+window$", clean_text)
                    if m_caw:
                        target = m_caw.group(1).strip()
                        entities = {"action": "close", "target": target}
                    else:
                        entities = {"action": "close", "target": "active"}

            if is_compound:
                entities["is_compound"] = True
                entities["raw_input"] = text
                conf = 0.5

        # 8. Windows Settings Navigation
        elif (
            "settings" in text
            or any(text.startswith(p) for p in ("open settings", "show settings", "launch settings", "view settings"))
            or any(k in text for k in ("default apps", "startup apps", "default browser", "change default browser", "set default browser", "change my default browser"))
            or text in ("settings", "windows settings")
        ) and not any(k in text for k in ("search", "find", "google")):
            cat = IntentCategory.OPEN_SETTINGS
            conf = 0.95
            is_compound = is_compound_command(text)

            # Check protected browser change -> default_apps
            if any(k in text for k in ("default browser", "change default browser", "set default browser", "change my default browser")):
                entities = {"page": "default_apps"}
            elif any(k in text for k in ("default apps", "default applications")):
                entities = {"page": "default_apps"}
            elif any(k in text for k in ("startup apps", "startup applications")):
                entities = {"page": "startup_apps"}
            else:
                m_page = re.search(r"(?:open|show|display|launch|view)\s+(?:the\s+)?([a-z_ &]+?)\s+settings\b", text)
                if m_page:
                    extracted = m_page.group(1).strip()
                    entities = {"page": extracted}
                else:
                    m_lead = re.match(r"^([a-z_ &]+?)\s+settings$", text)
                    if m_lead:
                        entities = {"page": m_lead.group(1).strip()}
                    else:
                        entities = {"page": "root"}

            if is_compound:
                entities["is_compound"] = True
                entities["raw_input"] = text
                conf = 0.5

        # 8.5 File & Folder Operations (Phase 5.8-G)
        elif (
            (any(text.startswith(p) for p in ("list files", "list directory", "list folder", "show files", "show directory", "show contents of", "what files are in", "dir ")) or text in ("list files", "list directory", "dir"))
            or re.match(r"^(?:file\s+details|file\s+info|get\s+(?:file\s+)?info|properties\s+of\s+file|how\s+big\s+is\s+file)\b", text)
            or re.match(r"^(?:open|launch|view|read)\s+file\b", text)
            or re.match(r"^(?:create|make|new)\s+(?:folder|directory)\b", text)
            or re.match(r"^(?:create|make|new)\s+file\b", text)
            or re.match(r"^rename\s+(?:file\s+)?(.+?)\s+to\s+", text)
            or re.match(r"^copy\s+(?:file\s+)?(.+?)\s+to\s+", text)
            or re.match(r"^move\s+(?:file\s+)?(.+?)\s+to\s+", text)
            or re.match(r"^(?:delete|remove)\s+file\b", text)
        ) and not any(k in text for k in ("web", "internet", "google", "youtube", "online")):
            cat = IntentCategory.FILE_OPERATION
            conf = 0.95
            is_compound = is_compound_command(text)
            entities = {}

            # 1. Delete file
            m_del = re.match(r"^(?:delete|remove)\s+file\s+(.+)$", text)
            if m_del:
                entities = {"action": "delete_file", "path": m_del.group(1).strip()}
            # 2. Rename file
            elif re.match(r"^rename\s+(?:file\s+)?(.+?)\s+to\s+(.+)$", text):
                m_ren = re.match(r"^rename\s+(?:file\s+)?(.+?)\s+to\s+(.+)$", text)
                entities = {"action": "rename_file", "source": m_ren.group(1).strip(), "destination": m_ren.group(2).strip()}
            # 3. Copy file
            elif re.match(r"^copy\s+(?:file\s+)?(.+?)\s+to\s+(.+)$", text):
                m_cp = re.match(r"^copy\s+(?:file\s+)?(.+?)\s+to\s+(.+)$", text)
                entities = {"action": "copy_file", "source": m_cp.group(1).strip(), "destination": m_cp.group(2).strip()}
            # 4. Move file
            elif re.match(r"^move\s+(?:file\s+)?(.+?)\s+to\s+(.+)$", text):
                m_mv = re.match(r"^move\s+(?:file\s+)?(.+?)\s+to\s+(.+)$", text)
                entities = {"action": "move_file", "source": m_mv.group(1).strip(), "destination": m_mv.group(2).strip()}
            # 5. Create file
            elif re.match(r"^(?:create|make|new)\s+file\s+(.+)$", text):
                m_cf = re.match(r"^(?:create|make|new)\s+file\s+(.+)$", text)
                raw_tail = m_cf.group(1).strip()
                if " with content " in raw_tail:
                    p, c = raw_tail.split(" with content ", 1)
                    entities = {"action": "create_file", "path": p.strip(), "content": c.strip()}
                    if " with content " in raw_text:
                        _, orig_c = raw_text.split(" with content ", 1)
                        entities["content"] = orig_c.strip()
                else:
                    entities = {"action": "create_file", "path": raw_tail}
            # 6. Create folder
            elif re.match(r"^(?:create|make|new)\s+(?:folder|directory)\s+(.+)$", text):
                m_cfol = re.match(r"^(?:create|make|new)\s+(?:folder|directory)\s+(.+)$", text)
                entities = {"action": "create_folder", "path": m_cfol.group(1).strip()}
            # 7. Open file
            elif re.match(r"^(?:open|launch|view|read)\s+file\s+(.+)$", text):
                m_of = re.match(r"^(?:open|launch|view|read)\s+file\s+(.+)$", text)
                entities = {"action": "open_file", "path": m_of.group(1).strip()}
            # 8. File info / details
            elif re.match(r"^(?:file\s+details\s+(?:for|of)|file\s+info\s+(?:for|of)|get\s+(?:file\s+)?info\s*(?:for|of|on)?|properties\s+of\s+file|how\s+big\s+is\s+file)\s*(.+)$", text):
                m_fi = re.match(r"^(?:file\s+details\s+(?:for|of)|file\s+info\s+(?:for|of)|get\s+(?:file\s+)?info\s*(?:for|of|on)?|properties\s+of\s+file|how\s+big\s+is\s+file)\s*(.+)$", text)
                entities = {"action": "get_file_info", "path": m_fi.group(1).strip()}
            # 9. List directory
            else:
                m_ls = re.match(r"^(?:list\s+(?:files\s+in|directory|folder|contents\s+of)?|show\s+files\s+in|dir)\s*(.*)$", text)
                p = m_ls.group(1).strip() if m_ls else ""
                entities = {"action": "list_directory"}
                if p:
                    entities["path"] = p

            if is_compound:
                entities["is_compound"] = True
                entities["raw_input"] = text
                conf = 0.5

        # 9. Application / Browser Launching
        elif any(text.startswith(prefix) for prefix in ("open", "launch", "start", "run")) or text in ("notepad", "calculator", "terminal", "cmd", "powershell", "explorer", "chrome", "edge"):
            m = re.match(r"^(?:open|launch|start|run)\s*(.*)$", text)
            raw_target = m.group(1).strip() if m else text
            target, is_compound = extract_clean_application_target(raw_target)
            if not target and text in ("notepad", "calculator", "terminal", "cmd", "powershell", "explorer", "chrome", "edge"):
                target = text

            if target:
                if target in ("browser", "web browser", "internet"):
                    cat = IntentCategory.OPEN_BROWSER
                    entities = {"application": "chrome", "browser": "chrome"}
                    conf = 0.95
                elif target in ("chrome browser", "google chrome browser"):
                    cat = IntentCategory.OPEN_BROWSER
                    entities = {"application": "chrome", "browser": "chrome"}
                    conf = 0.95
                elif target in ("edge browser", "microsoft edge browser"):
                    cat = IntentCategory.OPEN_BROWSER
                    entities = {"application": "edge", "browser": "edge"}
                    conf = 0.95
                else:
                    cat = IntentCategory.OPEN_APPLICATION
                    entities = {"application": target}
                    if target in ("chrome", "google chrome"):
                        entities["browser"] = "chrome"
                    elif target in ("edge", "msedge", "microsoft edge"):
                        entities["browser"] = "edge"
                    conf = 0.9

                if is_compound:
                    # Flag compound command so downstream Planner routes to LLM planning
                    entities["is_compound"] = True
                    entities["raw_input"] = text
                    conf = 0.5
                    conf_level = ConfidenceLevel.MEDIUM
            else:
                cat = IntentCategory.OPEN_APPLICATION
                entities = {}
                conf = 0.6

        # 8. Closing application
        elif any(text.startswith(prefix) for prefix in ("close", "quit", "exit", "kill")):
            m = re.match(r"^(?:close|quit|exit|kill)\s*(.*)$", text)
            raw_target = m.group(1).strip() if m else ""
            target = re.sub(r"^(the|an|a)\s+", "", raw_target).strip()
            target = re.sub(r"\s+(app|application|program)$", "", target).strip()
            if target == "crome":
                target = "chrome"
            cat = IntentCategory.CLOSE_APPLICATION
            entities = {"application": target} if target else {}
            conf = 0.9 if target else 0.6

        # 9. File search
        elif (
            re.match(r"^(?:find|locate)\s+(?:my\s+|the\s+)?(?:document\s+|file\s+)?(.+)$", text)
            or re.match(r"^search\s+(?:for\s+)?(?:document\s+|file\s+|my\s+)(.+)$", text)
            or ("resume" in text and any(k in text for k in ("find", "search", "locate")))
        ) and not any(k in text for k in ("web", "internet", "google", "youtube", "online")):
            cat = IntentCategory.FIND_FILE
            conf = 0.9
            m = re.match(r"^search\s+(?:for\s+)?(?:document\s+|file\s+|my\s+)(.+)$", text)
            if not m:
                m = re.match(r"^(?:find|locate)\s+(?:my\s+|the\s+)?(?:document\s+|file\s+)?(.+)$", text)
            pattern = m.group(1).strip() if m else ""
            if not pattern and "resume" in text:
                pattern = "resume"
            entities = {"pattern": pattern} if pattern else {}
            if not pattern:
                conf = 0.5

        # 10. Web search
        elif any(k in text for k in ("search", "google", "lookup")):
            cat = IntentCategory.WEB_SEARCH
            m = re.search(r"(?:search\s+(?:the\s+)?(?:web|internet)\s+(?:for\s+)?|search\s+for\s+|search\s+|google\s+|lookup\s+)(.+)$", text)
            query = m.group(1).strip() if m else ""
            entities = {"query": query} if query else {}
            conf = 0.85

        # 11. Shutdown system - Must explicitly require pc/computer/system/laptop or clean standalone command
        elif re.match(r"^(?:please\s+)?(?:shutdown|shut\s*down|power\s+off)(?:\s+(?:the\s+|my\s+)?(?:pc|computer|system|laptop))?$", text) or \
             re.match(r"^(?:please\s+)?turn\s+off\s+(?:the\s+|my\s+)?(?:pc|computer|system|laptop)$", text) or \
             text in ("shutdown", "shut down", "power off", "turn off the pc", "turn off the computer", "turn off my pc", "turn off my computer", "shutdown my pc", "shutdown the pc", "shutdown my laptop", "shut down my laptop", "turn off my laptop", "turn off the laptop"):
            cat = IntentCategory.SHUTDOWN
            conf = 0.95
            entities = {}

        # 12. Restart system - Must explicitly require pc/computer/system or clean standalone command
        elif re.match(r"^(?:please\s+)?(?:restart|reboot)(?:\s+(?:the\s+|my\s+)?(?:pc|computer|system))?$", text) or \
             text in ("restart", "reboot", "restart the pc", "restart the computer", "restart my pc", "restart my computer", "reboot the pc", "reboot my pc"):
            cat = IntentCategory.RESTART
            conf = 0.95
            entities = {}

        # 13. Sleep system - Must explicitly require sleep or put computer/pc to sleep
        elif re.match(r"^(?:please\s+)?(?:put\s+(?:the\s+|my\s+)?(?:pc|computer|system)\s+to\s+sleep|sleep(?:\s+(?:the\s+|my\s+)?(?:pc|computer|system))?)$", text) or \
             text in ("sleep", "go to sleep", "put computer to sleep", "put pc to sleep", "sleep pc", "sleep the computer", "sleep my pc", "put my pc to sleep"):
            cat = IntentCategory.SLEEP
            conf = 0.95
            entities = {}

        else:
            cat = IntentCategory.GENERAL_CONVERSATION
            conf = 0.5

        level = (
            ConfidenceLevel.HIGH if conf >= 0.8
            else ConfidenceLevel.MEDIUM if conf >= 0.5
            else ConfidenceLevel.LOW
        )
        return IntentResult(
            category=cat,
            confidence=conf,
            confidence_level=level,
            entities=entities,
            raw_scores={cat.value: conf},
        )

    @property
    def name(self) -> str:
        return "placeholder"


# Provider registry with lazy import support
_intent_providers: Dict[str, Any] = {
    "placeholder": PlaceholderIntentClassifier,
    # future providers can be added as "module.path.ClassName"
}


def _import_provider(class_path: str):
    module_path, class_name = class_path.rsplit(".", 1)
    module = __import__(module_path, fromlist=[class_name])
    return getattr(module, class_name)


def _get_provider_class(providers: Dict[str, Any], key: str):
    entry = providers.get(key)
    if not entry:
        return None
    if isinstance(entry, str):
        cls = _import_provider(entry)
        providers[key] = cls
        return cls
    return entry


def register_intent_provider(name: str, provider_class: type) -> None:
    """Register a new intent classifier implementation."""
    _intent_providers[name] = provider_class


def create_intent_classifier(config: Optional[IntentClassifierConfig] = None) -> BaseIntentClassifier:
    """Factory to create an intent classifier instance."""
    cfg = config or IntentClassifierConfig()
    provider_cls = _get_provider_class(_intent_providers, cfg.provider)
    if not provider_cls:
        raise IntentClassificationError(f"Unknown intent classifier provider: {cfg.provider}")
    return provider_cls(config)


def get_available_intent_providers() -> List[str]:
    return list(_intent_providers.keys())