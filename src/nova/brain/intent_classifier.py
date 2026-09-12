"""
Intent Classification abstraction and placeholder implementation.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from .models import RecognizedInput, IntentResult
from .types import IntentCategory, ConfidenceLevel, IntentClassifierConfig
from .exceptions import IntentClassificationError


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
        text = raw_text.lower()
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

        # Retry step: "retry step", "retry that step", "retry step 2", "retry step #2", "redo step 2"
        m_retry = re.match(r"^(?:retry|redo)(?:\s+(?:that|the))?\s+step(?:\s+(?:#\s*)?(\d+))?(?:\s+(?:for|of|in)?\s+task\s+([a-zA-Z0-9_-]+))?$", text)
        if m_retry:
            task_control_action = "retry_step"
            if m_retry.group(1):
                step_index = int(m_retry.group(1))
            if m_retry.group(2):
                task_id = m_retry.group(2)

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
        elif task_query_action:
            cat = IntentCategory.TASK_QUERY
            conf = 0.95
            entities["action"] = task_query_action
            if task_id:
                entities["task_id"] = task_id
            if filter_status:
                entities["filter_status"] = filter_status

        # 1. Screen reading
        elif any(k in text for k in ("screen", "what's on", "what is on", "read my screen")):
            cat = IntentCategory.SCREEN_READ
            conf = 0.9

        # 2. Volume control
        elif any(k in text for k in ("volume", "sound", "mute", "unmute")):
            cat = IntentCategory.SET_VOLUME
            conf = 0.9
            if "mute" in text and "unmute" not in text:
                entities["action"] = "mute"
            elif "unmute" in text:
                entities["action"] = "unmute"
            elif any(k in text for k in ("decrease", "lower", "reduce", "down")):
                entities["action"] = "decrease"
                m = re.search(r"(\d+)", text)
                entities["amount"] = int(m.group(1)) if m else 10
            elif any(k in text for k in ("increase", "raise", "up")):
                entities["action"] = "increase"
                m = re.search(r"(\d+)", text)
                entities["amount"] = int(m.group(1)) if m else 10
            else:
                entities["action"] = "set"
                m = re.search(r"(\d+)", text)
                entities["level"] = int(m.group(1)) if m else 50

        # 3. Application / Browser Launching
        elif any(text.startswith(prefix) for prefix in ("open", "launch", "start", "run")):
            m = re.match(r"^(?:open|launch|start|run)\s*(.*)$", text)
            raw_target = m.group(1).strip() if m else ""
            target = re.sub(r"^(the|an|a)\s+", "", raw_target).strip()
            target = re.sub(r"\s+(app|application|program)$", "", target).strip()

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
            else:
                cat = IntentCategory.OPEN_APPLICATION
                entities = {}
                conf = 0.6

        # 4. Closing application
        elif any(text.startswith(prefix) for prefix in ("close", "quit", "exit", "kill")):
            m = re.match(r"^(?:close|quit|exit|kill)\s*(.*)$", text)
            raw_target = m.group(1).strip() if m else ""
            target = re.sub(r"^(the|an|a)\s+", "", raw_target).strip()
            target = re.sub(r"\s+(app|application|program)$", "", target).strip()
            cat = IntentCategory.CLOSE_APPLICATION
            entities = {"application": target} if target else {}
            conf = 0.9 if target else 0.6

        # 5. Web search
        elif any(k in text for k in ("search", "google", "lookup")):
            cat = IntentCategory.WEB_SEARCH
            m = re.search(r"(?:search\s+for|search|google|lookup)\s+(.+)$", text)
            query = m.group(1).strip() if m else ""
            entities = {"query": query} if query else {}
            conf = 0.85

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