"""Robust JSON extractor + strict schema validation."""
from __future__ import annotations
import json, re, logging
from typing import Any, Dict, List, Optional
from .models import StructuredResponse, ToolAction
from .exceptions import ParseError, ValidationError

_log = logging.getLogger("nova.llm.parser")
_JSON_BLOCK = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_JSON_OBJ   = re.compile(r"(\{.*?\})", re.DOTALL)


class LLMParser:
    REQUIRED = ("requires_execution", "response_text", "actions")

    def parse(self, raw: str) -> "StructuredResponse":
        if not raw or not raw.strip():
            raise ParseError("Empty LLM response", raw)

        json_str = self._extract_json(raw)
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as exc:
            recovered = self._recover(json_str)
            if recovered:
                data = json.loads(recovered)
            else:
                raise ParseError("Invalid JSON", raw) from exc

        self._validate(data)
        return StructuredResponse(
            requires_execution=data["requires_execution"],
            response_text=data["response_text"],
            actions=[ToolAction(**a) for a in data["actions"]],
        )

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _extract_json(self, txt: str) -> str:
        txt = txt.strip()
        for m in self._JSON_BLOCK.finditer(txt):
            return m.group(1).strip()
        for m in self._JSON_OBJ.finditer(txt):
            return m.group(1).strip()
        if txt.startswith("{") and txt.endswith("}"):
            return txt
        raise ParseError("No JSON object found", raw=txt)

    def _recover(self, txt: str) -> Optional[str]:
        # very small recovery – strip trailing commas, fix single‑quotes
        txt = re.sub(r",\s*([}\]])", r"\1", txt)
        txt = txt.replace("'", '"')
        try:
            json.loads(txt)
            return txt
        except json.JSONDecodeError:
            return None

    def _validate(self, d: Dict[str, Any]) -> None:
        for k in self.REQUIRED:
            if k not in d:
                raise ValidationError(f"Missing key: {k}", field=k)
        if not isinstance(d["requires_execution"], bool):
            raise ValidationError("requires_execution must be bool", "requires_execution")
        if not isinstance(d["response_text"], str):
            raise ValidationError("response_text must be str", "response_text")
        if not isinstance(d["actions"], list):
            raise ValidationError("actions must be list", "actions")
        for i, a in enumerate(d["actions"]):
            if not isinstance(a, dict):
                raise ValidationError(f"action {i} not object", f"actions[{i}]")
            if "tool" not in a or not isinstance(a["tool"], str):
                raise ValidationError(f"action {i} missing tool", f"actions[{i}].tool")
            if "parameters" not in a or not isinstance(a["parameters"], dict):
                raise ValidationError(f"action {i} parameters missing", f"actions[{i}].parameters")

# ----------------------------------------------------------------------
# singleton
# ----------------------------------------------------------------------
_parser: Optional["LLMParser"] = None
def get_parser() -> "LLMParser":
    global _parser
    if _parser is None:
        _parser = LLMParser()
    return _parser