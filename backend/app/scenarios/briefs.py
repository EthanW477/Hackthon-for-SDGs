"""Trilingual brief generation (project-plan §4.4 F3, step 3.3).

One scenario test report → three audience-framed markdown briefs, each in
書面中文 (zh), English (en), and 粵語 (yue). The LLM narrates from the
structured report only — every number it can cite is in the payload; when no
LLM is reachable a deterministic template still renders the same sections so
the demo never stalls, always disclosed via ``generated_with``.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Literal

from app.ai.llm import chat_completion, message_content_text
from app.schemas.scenario import TestReport
from app.scenarios.redact import redact_text

logger = logging.getLogger(__name__)

Language = Literal["zh", "en", "yue"]
LANGUAGES: tuple[Language, ...] = ("zh", "en", "yue")

AUDIENCES: dict[str, dict[str, Any]] = {
    "cad_technical": {
        "title_en": "CAD Technical Summary",
        "title_zh": "民航處技術摘要",
        "title_yue": "民航處技術摘要",
        "register_en": "formal technical register for Civil Aviation Department reviewers",
        "sections": [
            "Scenario overview",
            "Execution metrics",
            "Checklist verification results",
            "Observed violations and clause references",
            "Recommendations",
        ],
    },
    "legco_policy": {
        "title_en": "LegCo Policy Brief",
        "title_zh": "立法會政策簡報",
        "title_yue": "立法會政策簡報",
        "register_en": "plain but formal policy register for Legislative Council members",
        "sections": [
            "Overview",
            "Safety performance",
            "Incident and system response",
            "Policy relevance (low-altitude economy, SDG 9/11)",
            "Next steps",
        ],
    },
    "community": {
        "title_en": "Community Notice",
        "title_zh": "社區通告",
        "title_yue": "社區通告",
        "register_en": "warm, reassuring plain language for district residents",
        "sections": [
            "What happened",
            "Was anyone at risk",
            "How the system responded",
            "What happens next",
        ],
    },
}

_LANGUAGE_DIRECTIVES = {
    "zh": "Write in formal written Chinese (Traditional characters, Hong Kong usage).",
    "en": "Write in clear professional English.",
    "yue": (
        "Write in Cantonese (粵語) as spoken in Hong Kong, using natural "
        "Cantonese particles and vocabulary (嘅、咗、喺、唔、啲…), not "
        "Mandarin grammar — it must read like something a 街坊 would say."
    ),
}


def _report_payload(report: TestReport) -> str:
    """Compact, redacted JSON the LLM may cite from — its only source of facts."""
    payload = {
        "scenario_id": report.scenario_id,
        "description": report.description,
        "area": report.scenario.area,
        "time_window": report.scenario.time_window,
        "weather": report.scenario.weather,
        "traffic_density": report.scenario.traffic_density,
        "aircraft_count": report.summary.aircraft_count,
        "duration_s": report.summary.duration_s,
        "injected_events": [e.model_dump() for e in report.scenario.injected_events],
        "summary": report.summary.model_dump(),
        "checks": [c.model_dump() for c in report.checks],
        "violations": [v.model_dump() for v in report.violations],
        "key_timeline_events": [
            e.model_dump()
            for e in report.timeline
            if e.kind in ("fault_detected", "fault_recovered", "violation", "advisory")
        ][:15],
        "citations": [c.model_dump(exclude_none=True) for c in report.citations],
        "notes": report.notes,
    }
    return redact_text(json.dumps(payload, ensure_ascii=False, indent=1))


def _brief_prompt(audience: str, language: Language, report: TestReport) -> list[dict[str, Any]]:
    tpl = AUDIENCES[audience]
    sections = "\n".join(f"  ## {s}" for s in tpl["sections"])
    system = (
        "You are the brief writer of UTM Copilot (低空通), Hong Kong's drone "
        "traffic-management test harness. Draft a markdown brief from the "
        "structured test report below.\n\n"
        "Hard rules (anti-hallucination discipline):\n"
        "1. Every number, track id, clause reference and event MUST come from "
        "the report JSON — never invent figures.\n"
        "2. Regulation references keep their clause identifiers (e.g. AC-014).\n"
        "3. Output markdown only, starting with a single # title.\n\n"
        f"Audience: {tpl['title_en']} — {tpl['register_en']}.\n"
        f"{_LANGUAGE_DIRECTIVES[language]}\n\n"
        f"Use exactly this section skeleton (translate headings to the target "
        f"language, keep the order):\n# {tpl['title_en']}\n{sections}"
    )
    user = f"Test report JSON:\n{_report_payload(report)}"
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


# ---------------------------------------------------------------------------
# Deterministic fallback briefs — same sections, numbers straight from report.
# ---------------------------------------------------------------------------


def _fmt_checks(report: TestReport, lang: Language) -> list[str]:
    label = {"pass": {"zh": "通過", "en": "PASS", "yue": "通過"},
             "fail": {"zh": "未通過", "en": "FAIL", "yue": "未通過"},
             "pending": {"zh": "待覆核", "en": "PENDING", "yue": "待覆核"}}
    return [f"- [{label[c.status][lang]}] {c.check}" for c in report.checks]


def _fallback_brief(audience: str, language: Language, report: TestReport) -> str:
    s = report.summary
    tpl = AUDIENCES[audience]
    zh = language in ("zh", "yue")
    pct = f"{s.pass_rate * 100:.0f}%"

    if zh:
        title = tpl["title_zh"]
        intro = (
            f"場景 {report.scenario_id}：{report.description or '（無描述）'}。"
            f"{s.aircraft_count} 架無人機於{report.scenario.area}一帶運作，"
            f"天氣 {report.scenario.weather}，模擬時長 {s.duration_s} 秒。"
        )
        metrics = (
            f"檢查 {s.total_checks} 項：通過 {s.passed}、未通過 {s.failed}、"
            f"待覆核 {s.pending}（通過率 {pct}）；觀察到 {s.violations_count} 宗違規、"
            f"{s.advisories_count} 次避讓提示。"
        )
        violation_head = "違規明細"
        no_violation = "是次演練無觀察到違規情況。"
    else:
        title = tpl["title_en"]
        intro = (
            f"Scenario {report.scenario_id}: {report.description or '(no description)'}. "
            f"{s.aircraft_count} aircraft over {report.scenario.area}, weather "
            f"{report.scenario.weather}, simulated for {s.duration_s} s."
        )
        metrics = (
            f"{s.total_checks} checks: {s.passed} passed, {s.failed} failed, "
            f"{s.pending} pending (pass rate {pct}); {s.violations_count} observed "
            f"violation(s), {s.advisories_count} avoidance advisory(ies)."
        )
        violation_head = "Violation detail"
        no_violation = "No violations were observed during this run."

    lines = [f"# {title}", "", intro, "", metrics, ""]
    if zh:
        lines.append("## 檢查結果" if audience == "cad_technical" else "## 系統表現")
    else:
        lines.append("## Checklist results" if audience == "cad_technical" else "## System performance")
    lines += _fmt_checks(report, language)
    lines += ["", f"## {violation_head}"]
    if report.violations:
        for v in report.violations:
            lines.append(
                f"- t={v.at_second:.0f}s {v.track_id or ''}: {v.message} ({v.regulation_ref})"
            )
    else:
        lines.append(no_violation)
    if language == "yue":
        # The fallback renders written Chinese; mark it honestly rather than
        # pretending Mandarin grammar is Cantonese.
        lines += ["", "（註：離線範本暫以書面中文呈現，連線後可生成地道粵語版。）"]
    lines += ["", "---", "UTM Copilot 低空通 · offline template brief"]
    return redact_text("\n".join(lines))


def generate_briefs(audience: str, report: TestReport) -> tuple[dict[str, str], str]:
    """Return ({lang: markdown}, generated_with) for one audience."""
    briefs: dict[str, str] = {}
    llm_count = 0
    for language in LANGUAGES:
        try:
            message = chat_completion(_brief_prompt(audience, language, report))
            text = message_content_text(message).strip()
            if not text:
                raise RuntimeError("empty LLM brief")
            text = re.sub(r"^```(?:markdown)?\s*|\s*```$", "", text).strip()
            briefs[language] = redact_text(text)
            llm_count += 1
        except Exception as exc:  # noqa: BLE001 — per-language fallback
            logger.warning("LLM brief failed (%s/%s): %s", audience, language, exc)
            briefs[language] = _fallback_brief(audience, language, report)
    generated_with = "llm" if llm_count == len(LANGUAGES) else "mixed" if llm_count else "fallback"
    return briefs, generated_with
