"""LLM tool-calling loop for POST /api/v1/chat."""

from __future__ import annotations

import json
import re
from typing import Any

from app.ai.llm import chat_completion, message_content_text
from app.ai.prompts import SYSTEM_PROMPT
from app.ai.tools import TOOL_SPECS, dispatch_tool
from app.schemas.chat import ChatResponse, Citation, MapAnnotation

MAX_TOOL_ROUNDS = 8


def _tool_call_arguments(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        return json.loads(raw) if raw.strip() else {}
    return {}


def _citations_from_trace(trace: list[dict[str, Any]]) -> list[Citation]:
    citations: list[Citation] = []
    seen: set[tuple[str, str | None]] = set()
    for entry in trace:
        if entry.get("tool") != "search_regulations":
            continue
        for hit in entry.get("result", {}).get("excerpts", []):
            reg_id = str(hit.get("regulation_id", ""))
            section = hit.get("section")
            key = (reg_id, section)
            if not reg_id or key in seen:
                continue
            seen.add(key)
            citations.append(
                Citation(
                    regulation_id=reg_id,
                    section=section,
                    excerpt=(hit.get("excerpt") or "")[:400] or None,
                )
            )
    return citations


def _map_annotations_from_trace(
    trace: list[dict[str, Any]],
    route: dict[str, Any] | None,
) -> list[MapAnnotation]:
    annotations: list[MapAnnotation] = []
    for entry in trace:
        if entry.get("tool") != "check_flight_plan":
            continue
        result = entry.get("result") or {}
        if result.get("verdict") != "rejected":
            continue
        geo = None
        if route:
            if route.get("type") == "Feature":
                geo = route
            elif route.get("type") == "LineString":
                geo = {"type": "Feature", "properties": {}, "geometry": route}
        if geo:
            annotations.append(
                MapAnnotation(
                    kind="rejected_route",
                    geojson=geo,
                    label="Rejected route",
                    color="#ef4444",
                )
            )
        break
    return annotations


def _fallback_reply(trace: list[dict[str, Any]], user_message: str) -> str:
    for entry in trace:
        if entry.get("tool") != "check_flight_plan":
            continue
        result = entry.get("result") or {}
        verdict = result.get("verdict")
        violations = result.get("violations") or []
        if verdict == "rejected" and violations:
            lines = [
                "The rules engine **rejected** this flight plan.",
                "",
            ]
            for v in violations:
                ref = v.get("regulation_ref", "")
                lines.append(f"- {v.get('message')} ({ref})")
            clauses = result.get("clauses_hit") or []
            if clauses:
                lines.append("")
                lines.append(f"Clauses hit: {', '.join(clauses)}.")
            return "\n".join(lines)
        if verdict == "approved":
            return "The rules engine approved this flight plan — no violations were found."
    return (
        "I could not reach the language model, and no tool results are available. "
        f"Your question was: {user_message[:200]}"
    )


def run_chat(
    message: str,
    route: dict[str, Any] | None = None,
) -> ChatResponse:
    """Run the grounded tool loop and return a contract-shaped ChatResponse."""
    user_content = message
    if route:
        user_content += (
            "\n\n[The user attached a route GeoJSON on the request. "
            "When assessing flyability, call check_flight_plan with this route and "
            "sensible params inferred from the question (default max_altitude_ft 250 "
            "unless they specify otherwise).]\n"
            f"Route JSON:\n{json.dumps(route)}"
        )

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
    trace: list[dict[str, Any]] = []

    assistant_message: dict[str, Any] | None = None
    for _ in range(MAX_TOOL_ROUNDS):
        assistant_message = chat_completion(messages, tools=TOOL_SPECS)
        tool_calls = assistant_message.get("tool_calls") or []
        if not tool_calls:
            break
        messages.append(assistant_message)
        for tc in tool_calls:
            fn = tc.get("function") or {}
            name = fn.get("name", "")
            args = _tool_call_arguments(fn.get("arguments"))
            result = dispatch_tool(name, args)
            trace.append({"tool": name, "arguments": args, "result": result})
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.get("id") or name,
                    "name": name,
                    "content": json.dumps(result, ensure_ascii=False),
                }
            )

    reply = message_content_text(assistant_message or {})
    if not reply.strip():
        reply = _fallback_reply(trace, message)

    # Strip markdown emphasis if model overuses it — keep plain for UI
    reply = re.sub(r"\*\*(.+?)\*\*", r"\1", reply)

    return ChatResponse(
        reply=reply.strip(),
        map_annotations=_map_annotations_from_trace(trace, route),
        citations=_citations_from_trace(trace),
    )
