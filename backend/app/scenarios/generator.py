"""Natural-language → scenario JSON + test checklist (project-plan §4.4, F2).

Pipeline: LLM drafts JSON → strict pydantic validation → automatic retry with
the validation error fed back. If every attempt fails (or no LLM is
reachable), a deterministic heuristic parser still produces a usable scenario
and the response is flagged with a warning — the demo must never hard-fail,
but a fallback is always disclosed (anti-hallucination discipline: never
silently fabricate).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from app.ai.llm import chat_completion, message_content_text
from app.schemas.scenario import InjectedEvent, Scenario

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3

SCHEMA_EXAMPLE = {
    "scenario": {
        "area": "Sha Tin — Science Park",
        "time_window": "2026-10-20T09:00:00+08:00/PT30M",
        "weather": "typhoon_approaching",
        "traffic_density": "high",
        "aircraft_count": 10,
        "injected_events": [
            {
                "kind": "gps_loss",
                "at_second": 300,
                "duration_s": 120,
                "target_track_id": "SIM-005",
                "detail": "GPS signal lost for 2 minutes",
            }
        ],
        "expected_system_behavior": [
            {
                "check": "System raises lost-link alert within 30 s of GPS loss",
                "pass_criteria": "alert latency <= 30 s",
            },
            {
                "check": "Remaining aircraft receive avoidance advisories",
                "pass_criteria": "advisory issued for every close-approach pair",
            },
        ],
    },
    "checklist": [
        "System raises lost-link alert within 30 s of GPS loss",
        "Remaining aircraft receive avoidance advisories",
    ],
}

SYSTEM_PROMPT = """\
You are the scenario generator of UTM Copilot (低空通), a Hong Kong drone \
traffic-management test harness. Convert the user's plain-language description \
(Chinese, Cantonese, or English) into a test-scenario JSON plus a measurable \
test checklist.

Output ONLY a single JSON object — no markdown fences, no commentary — with \
exactly this shape:
""" + json.dumps(SCHEMA_EXAMPLE, indent=2) + """

Field rules:
- injected_events[].kind is one of: gps_loss, rfz_intrusion, off_course, \
weather_shift, comms_loss.
- at_second is the sim-time offset in seconds ("第5分钟" / "at minute 5" → 300).
- duration_s defaults to 60; pick a value that fits the narrative (a GPS \
dropout typically lasts 60–180 s).
- target_track_id uses simulator ids SIM-001..SIM-0NN and must not exceed \
aircraft_count ("第5架" → "SIM-005"). Distribute distinct targets across \
events.
- time_window is an ISO 8601 "start/duration" interval in Hong Kong time \
(+08:00). Default start 2026-10-20T09:00:00+08:00; duration PT30M unless the \
user says otherwise.
- weather is a short snake_case token: fine, overcast, rain, gale, \
typhoon_approaching.
- traffic_density is low (1-3 aircraft), medium (4-7), or high (8+).
- aircraft_count honours the user's number (1-100).
- expected_system_behavior / checklist entries must be MEASURABLE statements \
the simulator can verify: alert latency in seconds, advisories issued, \
intrusion/deviation detected, link recovery. Avoid vague wishes.
- checklist mirrors expected_system_behavior checks as plain strings.
"""


@dataclass
class GenerationResult:
    scenario: Scenario
    checklist: list[str]
    source: str = "llm"  # "llm" | "fallback"
    attempts: int = 1
    warnings: list[str] = field(default_factory=list)


def _extract_json(text: str) -> dict[str, Any]:
    """Tolerate ```json fences and prose around the object."""
    cleaned = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL)
    if fence:
        cleaned = fence.group(1)
    else:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start != -1 and end > start:
            cleaned = cleaned[start : end + 1]
    return json.loads(cleaned)


def _validate(payload: dict[str, Any]) -> tuple[Scenario, list[str]]:
    scenario = Scenario.model_validate(payload.get("scenario", payload))
    raw_checklist = payload.get("checklist")
    if isinstance(raw_checklist, list):
        checklist = [str(item) for item in raw_checklist if str(item).strip()]
    else:
        checklist = []
    if not checklist:
        checklist = [b.check for b in scenario.expected_system_behavior]
    if not checklist:
        raise ValueError("checklist is empty — at least one measurable check is required")
    return scenario, checklist


def _llm_generate(description: str) -> GenerationResult:
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Scenario description:\n{description}"},
    ]
    last_error: str | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        if last_error:
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "The previous output failed validation: "
                        f"{last_error}\nReturn a corrected JSON object only."
                    ),
                }
            )
        message = chat_completion(messages)
        raw = message_content_text(message)
        try:
            scenario, checklist = _validate(_extract_json(raw))
            return GenerationResult(
                scenario=scenario, checklist=checklist, source="llm", attempts=attempt
            )
        except (json.JSONDecodeError, ValidationError, ValueError) as exc:
            last_error = str(exc)[:500]
            logger.warning("scenario generation attempt %d invalid: %s", attempt, last_error)
            messages.append({"role": "assistant", "content": raw})
    raise RuntimeError(f"scenario JSON failed validation after {MAX_ATTEMPTS} attempts")


# ---------------------------------------------------------------------------
# Deterministic fallback parser — regex extraction, always disclosed.
# ---------------------------------------------------------------------------

_COUNT_RE = re.compile(r"(\d+)\s*(?:架|架次| drones?\b|aircraft|uav|无人机|無人機)", re.I)
# "第 5 分钟" (number first) and "at minute 5" / "5 minutes in" (word first).
_MINUTE_RES = [
    re.compile(r"第?\s*(\d+)\s*(?:分钟|分鐘|minutes?|mins?)\b", re.I),
    re.compile(r"(?:minute|min)\s*(\d+)", re.I),
]
_ORDINAL_RE = re.compile(r"第\s*(\d+)\s*架")


def _minute_offset(text: str) -> int | None:
    for pattern in _MINUTE_RES:
        m = pattern.search(text)
        if m:
            return int(m.group(1)) * 60
    return None

_WEATHER_HINTS = [
    (r"台风|颱風|typhoon", "typhoon_approaching"),
    (r"暴雨|大雨|rain|storm", "rain"),
    (r"大风|大風|gale|wind", "gale"),
    (r"阴|陰|overcast", "overcast"),
]

_FAULT_HINTS = [
    (r"gps|丢星|丟星|失联|失聯|lost[- ]?link|失去信号|失去訊號", "gps_loss"),
    (r"闯入|闖入|intrud|禁飞区|禁飛區|rfz|restricted", "rfz_intrusion"),
    (r"偏离|偏離|off[- ]?course|deviat|偏航", "off_course"),
    (r"通信|通訊|comms?|数据链|數據鏈", "comms_loss"),
    (r"天气突变|天氣突變|weather shift|风向突变|風向突變", "weather_shift"),
]

_DEFAULT_CHECKS = {
    "gps_loss": "System raises lost-link alert within 30 s of GPS loss",
    "rfz_intrusion": "System flags the restricted-zone intrusion within 30 s",
    "off_course": "System flags the off-course deviation within 30 s",
    "comms_loss": "System raises lost-link alert within 30 s of comms loss",
    "weather_shift": "Timeline records the weather shift event",
}


def _fallback_generate(description: str) -> GenerationResult:
    text = description
    count_m = _COUNT_RE.search(text)
    aircraft_count = max(1, min(100, int(count_m.group(1)))) if count_m else 5
    weather = next((w for pat, w in _WEATHER_HINTS if re.search(pat, text, re.I)), "fine")
    density = "high" if aircraft_count >= 8 else "medium" if aircraft_count >= 4 else "low"

    at_second = _minute_offset(text) or 300
    ordinal_m = _ORDINAL_RE.search(text)
    target_idx = int(ordinal_m.group(1)) if ordinal_m else 1
    target = f"SIM-{min(target_idx, aircraft_count):03d}"

    events: list[InjectedEvent] = []
    checks: list[str] = []
    for pat, kind in _FAULT_HINTS:
        if re.search(pat, text, re.I):
            events.append(
                InjectedEvent(
                    kind=kind, at_second=at_second, duration_s=120.0,
                    target_track_id=target, detail="heuristic fallback extraction",
                )
            )
            checks.append(_DEFAULT_CHECKS[kind])
            break  # one fault is enough for the fallback path
    checks.append("Remaining aircraft receive avoidance advisories")

    scenario = Scenario(
        time_window="2026-10-20T09:00:00+08:00/PT30M",
        weather=weather,
        traffic_density=density,
        aircraft_count=aircraft_count,
        injected_events=events,
    )
    return GenerationResult(
        scenario=scenario,
        checklist=checks,
        source="fallback",
        attempts=0,
        warnings=[
            "LLM generation unavailable or invalid; scenario built by the "
            "deterministic fallback parser — review before use."
        ],
    )


def generate_scenario(description: str) -> GenerationResult:
    """LLM-first generation with schema validation + retry, heuristic fallback."""
    try:
        return _llm_generate(description)
    except Exception as exc:  # noqa: BLE001 — fallback must catch LLM outages too
        logger.warning("LLM scenario generation failed, using fallback: %s", exc)
        result = _fallback_generate(description)
        result.warnings.insert(0, f"LLM error: {str(exc)[:200]}")
        return result
