"""
Parser utilities – extract and validate JSON from LLM output.
"""
from __future__ import annotations

import json
import re
from typing import Any, List, Union

from .schemas import Intent, Plan


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\}|\\[.*?\\])\s*```", re.DOTALL)


def extract_json(text: str) -> Union[dict, List[dict], None]:
    """
    Try to pull a JSON object or array out of the raw model text.
    Handles optional markdown code fences and stray surrounding text.
    """
    # 1. Look for fenced block first
    m = _JSON_FENCE_RE.search(text)
    if m:
        candidate = m.group(1)
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

    # 2. Try the whole text
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 3. Fallback – find first {...} or [...] substrings
    for start_char, end_char in [("{", "}"), ("[", "]")]:
        start = text.find(start_char)
        while start != -1:
            end = text.find(end_char, start)
            if end != -1:
                snippet = text[start:end+1]
                try:
                    return json.loads(snippet)
                except json.JSONDecodeError:
                    pass
            start = text.find(start_char, start + 1)

    return None


def parse_intent(data: Any) -> Intent:
    """Validate a single intent dict via Pydantic."""
    if isinstance(data, list):
        raise ValueError("Expected single intent, got list")
    return Intent(**data)


def parse_plan(data: Any) -> Plan:
    """Validate a plan (list of intents)."""
    if not isinstance(data, list):
        raise ValueError("Expected list for plan")
    intents = [Intent(**item) for item in data]
    return Plan(intents=intents)


def parse_output(text: str) -> Union[Intent, Plan, None]:
    """
    High‑level helper used by the Brain:
    - returns an Intent (single) or Plan (multiple) or None on failure.
    """
    parsed = extract_json(text)
    if parsed is None:
        return None
    if isinstance(parsed, list):
        return parse_plan(parsed)
    return parse_intent(parsed)