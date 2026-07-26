"""
Nova Brain – connects the local LLM (llama-cpp-python) to the controller manager.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, Optional

from llama_cpp import Llama

from .prompt import build_prompt
from .parser import parse_output
from .schemas import Intent
from nova.controllers.manager import get_controller_manager
from nova.agent import get_agent
from nova.events import get_event_bus, IntentResolvedEvent, UserCommandReceivedEvent, GoalCompletedEvent

logger = logging.getLogger("nova.brain")

# -------------------------------------------------------------------------
# Configuration – all via env vars with sensible defaults
# -------------------------------------------------------------------------
MODEL_PATH = os.getenv(
    "NOVA_BRAIN_MODEL",
    "models/Qwen2.5-0.5B-Instruct-Q4_K_M.gguf",
)
CTX_SIZE = int(os.getenv("NOVA_BRAIN_CTX", "2048"))
N_THREADS = int(os.getenv("NOVA_BRAIN_THREADS", str(os.cpu_count() or 4)))
N_GPU_LAYERS = int(os.getenv("NOVA_BRAIN_GPU_LAYERS", "0"))
TEMPERATURE = float(os.getenv("NOVA_BRAIN_TEMP", "0.0"))  # deterministic

# -------------------------------------------------------------------------
# Singleton LLM wrapper
# -------------------------------------------------------------------------
class _LLMSingleton:
    _instance: Optional[Llama] = None

    @classmethod
    def get(cls) -> Llama:
        if cls._instance is None:
            if not os.path.isfile(MODEL_PATH):
                raise RuntimeError(f"Brain model not found at {MODEL_PATH}")
            logger.info(
                "Loading brain model: %s (ctx=%d, threads=%d, gpu_layers=%d)",
                MODEL_PATH,
                CTX_SIZE,
                N_THREADS,
                N_GPU_LAYERS,
            )
            cls._instance = Llama(
                model_path=MODEL_PATH,
                n_ctx=CTX_SIZE,
                n_threads=N_THREADS,
                n_gpu_layers=N_GPU_LAYERS,
                verbose=False,
                seed=42,
            )
            logger.info("Brain model loaded")
        return cls._instance


# -------------------------------------------------------------------------
# Public Brain class
# -------------------------------------------------------------------------
class Brain:
    """
    High‑level façade:
        brain.process(user_text)  -> execution result dict
    """

    def __init__(self) -> None:
        self._llm = _LLMSingleton.get()
        self._controller_mgr = get_controller_manager()
        self._agent = get_agent()
        self._event_bus = get_event_bus()
        self._conversation_context = ""  # could be extended for multi‑turn

    # -----------------------------------------------------------------
    def _call_llm(self, prompt: str) -> str:
        """Call llama‑cpp chat completion (single turn)."""
        start = time.perf_counter()
        resp = self._llm.create_chat_completion(
            messages=[
                {"role": "system", "content": prompt.split("### User request")[0].strip()},
                {"role": "user", "content": prompt.split("### User request\n")[-1].split("### JSON output")[0].strip()},
            ],
            temperature=TEMPERATURE,
            max_tokens=256,
            stop=["\n\n"],
        )
        elapsed = time.perf_counter() - start
        logger.debug("LLM inference took %.3fs", elapsed)
        return resp["choices"][0]["message"]["content"].strip()

    # -----------------------------------------------------------------
    def process(self, user_text: str) -> Dict[str, Any]:
        """
        Full pipeline: user text -> LLM -> parsed Intent/Plan -> Agent -> result.
        """
        # 1. Emit user command event
        self._event_bus.publish(UserCommandReceivedEvent(source="brain", payload={"text": user_text}))

        # 1. Build prompt
        prompt = build_prompt(user_text, self._conversation_context)

        # 2. Call LLM
        raw = self._call_llm(prompt)
        logger.debug("Raw LLM output: %s", raw)

        # 3. Parse JSON
        parsed = parse_output(raw)
        if parsed is None:
            logger.warning("Failed to parse LLM output")
            return {"status": "error", "detail": "Could not understand model output"}

        # 4. Emit intent resolved event
        if isinstance(parsed, list):
            first_intent = parsed[0]
        else:
            first_intent = parsed
        self._event_bus.publish(
            IntentResolvedEvent(
                source="brain",
                payload={
                    "intent": first_intent.intent,
                    "confidence": first_intent.confidence,
                    "parameters": first_intent.parameters,
                },
            )
        )

        # 4. Delegate to Agent (which orchestrates planner, tool executor, etc.)
        agent_result = self._agent.achieve(user_text)

        # 5. Update simple conversation context
        self._conversation_context = f"User: {user_text}\nAssistant: {agent_result.get('summary', '')}"

        # 6. Emit completion event
        self._event_bus.publish(
            GoalCompletedEvent(
                source="brain",
                payload={"goal_id": "", "summary": agent_result.get("summary", "")},
            )
        )

        return agent_result


# -------------------------------------------------------------------------
# Convenience function used by existing entry points
# -------------------------------------------------------------------------
_brain_instance: Optional[Brain] = None


def get_brain() -> Brain:
    global _brain_instance
    if _brain_instance is None:
        _brain_instance = Brain()
    return _brain_instance