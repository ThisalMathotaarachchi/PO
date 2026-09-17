"""Parse model output into a tool call or completion. Internal reasoning stays internal."""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel

from app.models.base import ModelResponse
from app.tools.registry import ToolCall


class AgentActionType:
    TOOL = "tool"
    COMPLETE = "complete"
    MALFORMED = "malformed"


class AgentAction(BaseModel):
    type: str
    tool_call: ToolCall | None = None
    summary: str = ""
    raw: str = ""
    repair_hint: str = ""


_JSON_BLOCK = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_FIRST_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


class Planner:
    def parse(self, response: ModelResponse) -> AgentAction:
        if response.tool_calls:
            first = response.tool_calls[0]
            if first.get("tool"):
                return AgentAction(
                    type=AgentActionType.TOOL,
                    tool_call=ToolCall(tool=str(first["tool"]), arguments=dict(first.get("arguments") or {})),
                    raw=response.content,
                )

        text = (response.content or "").strip()
        parsed = _extract_json(text)
        if parsed is None:
            return AgentAction(
                type=AgentActionType.MALFORMED,
                raw=text,
                repair_hint="Return a single JSON object with either a tool call or {\"complete\": true, \"summary\": \"...\"}.",
            )
        if parsed.get("complete") is True or parsed.get("action") == "complete":
            return AgentAction(type=AgentActionType.COMPLETE, summary=str(parsed.get("summary") or "Done."), raw=text)
        tool = parsed.get("tool") or parsed.get("name") or (parsed.get("function") or {}).get("name")
        args = parsed.get("arguments") or parsed.get("args") or parsed.get("parameters") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {}
        if tool:
            return AgentAction(
                type=AgentActionType.TOOL,
                tool_call=ToolCall(tool=str(tool), arguments=args if isinstance(args, dict) else {}),
                raw=text,
            )
        if parsed.get("message") and not tool:
            # model tried to chat instead of using tools
            return AgentAction(
                type=AgentActionType.MALFORMED,
                raw=text,
                summary=str(parsed.get("message")),
                repair_hint="Use a tool instead of chatting. If the task is finished, return {\"complete\": true, \"summary\": \"...\"}.",
            )
        return AgentAction(
            type=AgentActionType.MALFORMED,
            raw=text,
            repair_hint="JSON must include a 'tool' field or complete=true.",
        )


def _extract_json(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    candidates: list[str] = []
    match = _JSON_BLOCK.search(text)
    if match:
        candidates.append(match.group(1))
    stripped = text.strip()
    if stripped.startswith("{"):
        # Try to extract just the first complete JSON object
        try:
            decoder = json.JSONDecoder()
            data, end_idx = decoder.raw_decode(stripped)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass
        candidates.append(stripped)
    obj = _FIRST_OBJECT.search(text)
    if obj:
        candidates.append(obj.group(0))
    for candidate in candidates:
        try:
            data = json.loads(candidate)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            continue
        # attempt to find last complete object
        try:
            decoder = json.JSONDecoder()
            data, _ = decoder.raw_decode(candidate[candidate.find("{") :])
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            continue
    return None
