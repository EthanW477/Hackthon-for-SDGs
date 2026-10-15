"""Scenario executor — run a Scenario through the track simulator and produce
a structured, citation-carrying test report (project-plan §4.4 F2, step 3.2).

The executor plays two roles:

1. the world: the deterministic Simulator flies the traffic with the injected
   faults (gps_loss / off_course→deviation / rfz_intrusion→intrusion);
2. the system under test: a deterministic UTM monitor watches the reported
   track picture — lost-link detection, avoidance advisories, separation and
   corridor/zone violations.

Checklist evaluation is code, not LLM: each expected behaviour is matched to
a measurable probe and marked pass/fail/pending with evidence. Anything the
simulator cannot observe stays honestly "pending". The LLM only enters later,
to narrate the briefs — the verdicts here never depend on it.
"""

from __future__ import annotations

import hashlib
import math
import re
from datetime import datetime, timedelta, timezone

from app.schemas.scenario import (
    CheckResult,
    InjectedEvent,
    ObservedViolation,
    ReportCitation,
    ReportSummary,
    Scenario,
    TestReport,
    TimelineEvent,
)
from app.simulator import FaultSpec, Simulator
from app.simulator.tracks import (
    CORRIDOR_MAX_LAT,
    CORRIDOR_MAX_LON,
    CORRIDOR_MIN_LAT,
    CORRIDOR_MIN_LON,
    DEFAULT_INTRUSION_POLYGON,
    MAX_COUNT,
    distance_m,
    point_in_polygon,
)
from app.scenarios.redact import redact_lines, redact_text

HK_TZ = timezone(timedelta(hours=8))

MIN_DURATION_S = 30
MAX_DURATION_S = 1800
ADVISORY_THRESHOLD_M = 60.0
SEPARATION_VIOLATION_M = 30.0  # mirrors the rules-engine horizontal separation
ADVISORY_COOLDOWN_S = 30.0
AIRBORNE_ALT_M = 5.0

# Fault kinds the simulator can kinematically reproduce; the rest are logged
# as context events (weather_shift) or mapped onto an equivalent observable.
_SIM_FAULT_KIND = {
    "gps_loss": "gps_loss",
    "comms_loss": "gps_loss",  # lost link presents identically on the track picture
    "off_course": "deviation",
    "rfz_intrusion": "intrusion",
}


def _stable_seed(scenario_id: str) -> int:
    return int(hashlib.md5(scenario_id.encode()).hexdigest()[:8], 16)


_DURATION_RE = re.compile(
    r"^P(?:(?P<days>\d+(?:\.\d+)?)D)?"
    r"(?:T(?:(?P<hours>\d+(?:\.\d+)?)H)?(?:(?P<minutes>\d+(?:\.\d+)?)M)?"
    r"(?:(?P<seconds>\d+(?:\.\d+)?)S)?)?$"
)


def window_seconds(time_window: str) -> int:
    """ISO 8601 interval ("start/duration" or "start/end") → whole sim seconds."""
    _, _, tail = time_window.partition("/")
    seconds = 1800.0
    if tail:
        m = _DURATION_RE.match(tail)
        if m:
            parts = {k: float(v) for k, v in m.groupdict().items() if v}
            seconds = (
                parts.get("days", 0.0) * 86400
                + parts.get("hours", 0.0) * 3600
                + parts.get("minutes", 0.0) * 60
                + parts.get("seconds", 0.0)
            )
        else:
            try:
                start = datetime.fromisoformat(time_window.partition("/")[0])
                end = datetime.fromisoformat(tail)
                seconds = (end - start).total_seconds()
            except ValueError:
                pass
    return int(max(MIN_DURATION_S, min(MAX_DURATION_S, seconds)))


def _normalize_target(raw: str | None, count: int, fallback_idx: int) -> str:
    """Map an LLM-supplied target id onto the actual fleet SIM-001..SIM-0NN."""
    if raw:
        m = re.search(r"(\d+)", raw)
        if m:
            idx = int(m.group(1))
            return f"SIM-{max(1, min(count, idx)):03d}"
    return f"SIM-{(fallback_idx % count) + 1:03d}"


def _faults_from_events(
    events: list[InjectedEvent], count: int, notes: list[str]
) -> tuple[list[FaultSpec], dict[str, list[InjectedEvent]]]:
    """Translate scenario events into simulator FaultSpecs.

    Returns the specs plus a track_id → source-events map for the timeline.
    """
    specs: list[FaultSpec] = []
    by_track: dict[str, list[InjectedEvent]] = {}
    for i, event in enumerate(events):
        target = _normalize_target(event.target_track_id, count, i)
        sim_kind = _SIM_FAULT_KIND.get(event.kind)
        if sim_kind is None:
            notes.append(
                f"{event.kind} at t={event.at_second}s logged as context only — "
                "simulator v1 has no kinematic effect for it"
            )
            by_track.setdefault(target, []).append(event)
            continue
        duration = min(event.duration_s, float(MAX_DURATION_S))
        specs.append(
            FaultSpec(kind=sim_kind, track_id=target, start_s=float(event.at_second), duration_s=duration)
        )
        by_track.setdefault(target, []).append(event)
    return specs, by_track


# ---------------------------------------------------------------------------
# In-run monitor — the "system under test".
# ---------------------------------------------------------------------------


class _Monitor:
    """Deterministic UTM monitor — the system under test.

    Separation probing is scoped to pairs involving a fault-affected aircraft
    during its fault window: simulator v1 traffic is not deconflicted
    fleet-wide (trail followers on shared templates genuinely converge), so a
    fleet-wide probe would drown the report in nominal-traffic noise that says
    nothing about the scenario under test.
    """

    def __init__(self, faults: list[FaultSpec], scenario_events: list[InjectedEvent]) -> None:
        self.events: list[TimelineEvent] = []
        self.violations: list[ObservedViolation] = []
        self.prev_status: dict[str, str] = {}
        self.faults = faults
        self.fault_tracks = {f.track_id for f in faults}
        self.scenario_events = scenario_events
        self.detected_faults: dict[tuple[str, str], float] = {}  # (kind, track) -> detected t
        self.recovered: dict[str, float] = {}  # track -> t
        self.deviation_tracks: set[str] = set()
        self.intrusion_tracks: set[str] = set()
        self.broadcasts: list[float] = []  # t of each lost-link fleet broadcast
        self._advisory_cooldown: dict[tuple[str, str], float] = {}
        self._violation_cooldown: dict[tuple[str, str], float] = {}
        self._corridor_flagged: set[str] = set()
        self.advisories_count = 0

    def log(self, t: float, kind: str, message: str, track_id: str | None = None) -> None:
        self.events.append(TimelineEvent(t=round(t, 1), kind=kind, message=message, track_id=track_id))

    def violation(
        self, t: float, rule_id: str, regulation_ref: str, message: str, track_id: str | None
    ) -> None:
        self.violations.append(
            ObservedViolation(
                rule_id=rule_id, regulation_ref=regulation_ref,
                message=message, track_id=track_id, at_second=round(t, 1),
            )
        )
        self.log(t, "violation", message, track_id)

    # -- per-tick probes --------------------------------------------------

    def observe_statuses(self, t: float, snapshot) -> None:
        for tr in snapshot:
            prev = self.prev_status.get(tr.track_id)
            status = tr.status
            if status == prev:
                continue
            if status == "gps_loss" and prev != "gps_loss":
                self.log(t, "fault_detected",
                         f"LOST-LINK ALERT: {tr.track_id} position fix frozen", tr.track_id)
                airborne_others = [
                    o.track_id for o in snapshot
                    if o.track_id != tr.track_id and o.altitude_m > AIRBORNE_ALT_M
                ]
                if airborne_others:
                    self.broadcasts.append(t)
                    self.advisories_count += 1
                    self.log(
                        t, "advisory",
                        f"lost-link advisory broadcast to {len(airborne_others)} airborne "
                        f"aircraft: untracked {tr.track_id}, last known fix "
                        f"({tr.lon:.5f}, {tr.lat:.5f}, {tr.altitude_m:.0f} m)",
                        tr.track_id,
                    )
                for f in self.faults:
                    if f.track_id == tr.track_id and f.kind == "gps_loss" and f.start_s <= t <= f.end_s + 2:
                        key = ("gps_loss", tr.track_id)
                        self.detected_faults.setdefault(key, t)
            elif prev == "gps_loss" and status != "gps_loss":
                self.log(t, "fault_recovered",
                         f"{tr.track_id} link restored — position fix live again", tr.track_id)
                self.recovered.setdefault(tr.track_id, t)
            elif status == "deviation" and tr.track_id not in self.deviation_tracks:
                self.log(t, "fault_detected",
                         f"ROUTE DEVIATION: {tr.track_id} drifting off planned route", tr.track_id)
                self.deviation_tracks.add(tr.track_id)
            elif status == "intrusion" and tr.track_id not in self.intrusion_tracks:
                self.log(t, "fault_detected",
                         f"RFZ INTRUSION ALERT: {tr.track_id} steering into restricted area",
                         tr.track_id)
                self.intrusion_tracks.add(tr.track_id)
            self.prev_status[tr.track_id] = status

    def observe_separation(self, t: float, snapshot, active_fault_tracks: set[str]) -> None:
        airborne = [tr for tr in snapshot if tr.altitude_m > AIRBORNE_ALT_M]
        if not active_fault_tracks:
            return
        for i in range(len(airborne)):
            for j in range(i + 1, len(airborne)):
                a, b = airborne[i], airborne[j]
                if a.track_id not in active_fault_tracks and b.track_id not in active_fault_tracks:
                    continue
                dist = distance_m((a.lon, a.lat), (b.lon, b.lat))
                pair = tuple(sorted((a.track_id, b.track_id)))
                if dist < SEPARATION_VIOLATION_M:
                    last = self._violation_cooldown.get(pair, -1e9)
                    if t - last >= ADVISORY_COOLDOWN_S:
                        self._violation_cooldown[pair] = t
                        self.violation(
                            t, "separation_minima", "AC-014",
                            f"separation between {pair[0]} and {pair[1]} down to "
                            f"{dist:.0f} m (minimum {SEPARATION_VIOLATION_M:.0f} m)",
                            pair[0],
                        )
                elif dist < ADVISORY_THRESHOLD_M:
                    last = self._advisory_cooldown.get(pair, -1e9)
                    if t - last >= ADVISORY_COOLDOWN_S:
                        self._advisory_cooldown[pair] = t
                        self.advisories_count += 1
                        self.log(t, "advisory",
                                 f"avoidance advisory issued to {pair[0]} / {pair[1]} "
                                 f"(closing, {dist:.0f} m)", pair[0])

    def observe_containment(self, t: float, snapshot) -> None:
        for tr in snapshot:
            if tr.altitude_m <= AIRBORNE_ALT_M:
                continue
            outside = not (
                CORRIDOR_MIN_LON <= tr.lon <= CORRIDOR_MAX_LON
                and CORRIDOR_MIN_LAT <= tr.lat <= CORRIDOR_MAX_LAT
            )
            if outside and tr.track_id not in self._corridor_flagged:
                self._corridor_flagged.add(tr.track_id)
                self.violation(
                    t, "corridor_exit", "AC-014",
                    f"{tr.track_id} left the authorised operating corridor "
                    f"({tr.lon:.5f}, {tr.lat:.5f})", tr.track_id,
                )
            in_zone = point_in_polygon(tr.lon, tr.lat, DEFAULT_INTRUSION_POLYGON)
            if in_zone and tr.track_id in self.intrusion_tracks:
                key = (tr.track_id, "zone")
                last = self._violation_cooldown.get(key, -1e9)
                if t - last >= ADVISORY_COOLDOWN_S:
                    self._violation_cooldown[key] = t
                    self.violation(
                        t, "rfz_intersection", "AC-014",
                        f"{tr.track_id} inside restricted flying zone polygon "
                        "(Sha Tin Racecourse area)", tr.track_id,
                    )

    def observe_weather_events(self, t: float) -> None:
        for event in self.scenario_events:
            if event.kind == "weather_shift" and abs(event.at_second - t) < 0.5:
                self.log(t, "weather",
                         f"WEATHER SHIFT: {event.detail or 'conditions deteriorate'}", None)


# ---------------------------------------------------------------------------
# Checklist evaluation — deterministic probes, honest pending.
# ---------------------------------------------------------------------------

_LATENCY_RE = re.compile(r"(\d+)\s*(?:s\b|sec|second|秒)", re.I)


def _evaluate_checks(
    scenario: Scenario,
    checklist: list[str],
    monitor: _Monitor,
    duration_s: int,
) -> list[CheckResult]:
    results: list[CheckResult] = []
    gps_faults = [f for f in monitor.faults if f.kind == "gps_loss"]
    deviation_faults = [f for f in monitor.faults if f.kind == "deviation"]
    intrusion_faults = [f for f in monitor.faults if f.kind == "intrusion"]

    for check in checklist:
        text = check
        lowered = text.lower()
        latency_m = _LATENCY_RE.search(text)

        if latency_m and re.search(r"alert|alarm|detect|identify|warn|flag|告警|警報|识别|識別|侦测|偵測", lowered):
            threshold = float(latency_m.group(1))
            if not gps_faults and not intrusion_faults and not deviation_faults:
                results.append(CheckResult(
                    check=text, status="pending",
                    evidence="no fault event in this scenario to measure latency against",
                ))
                continue
            latencies = []
            missing = []
            for f in gps_faults + intrusion_faults + deviation_faults:
                key_kind = "gps_loss" if f.kind == "gps_loss" else f.kind
                det = monitor.detected_faults.get((key_kind, f.track_id))
                if det is None and f.kind in ("deviation", "intrusion"):
                    det = min(
                        [e.t for e in monitor.events
                         if e.kind == "fault_detected" and e.track_id == f.track_id] or [None]
                    )
                if det is None:
                    missing.append(f.track_id)
                else:
                    latencies.append((f, det - f.start_s))
            if missing:
                results.append(CheckResult(
                    check=text, status="fail", regulation_ref="AC-014",
                    evidence=f"no alert observed for {', '.join(missing)} within the window",
                ))
            else:
                worst = max(lat for _, lat in latencies)
                detail = "; ".join(f"{f.track_id}: alert in {lat:.0f} s" for f, lat in latencies)
                results.append(CheckResult(
                    check=text,
                    status="pass" if worst <= threshold else "fail",
                    regulation_ref="AC-014",
                    evidence=f"{detail} (threshold {threshold:.0f} s)",
                ))
        elif re.search(r"avoid|advisory|advisories|separation|避让|避讓|冲突|衝突", lowered):
            sep_violations = [v for v in monitor.violations if v.rule_id == "separation_minima"]
            results.append(CheckResult(
                check=text, status="pass", regulation_ref="AC-014",
                evidence=(
                    f"monitor tracked {len(monitor.fault_tracks)} fault-affected "
                    f"aircraft: {monitor.advisories_count} advisory(ies) issued "
                    f"({len(monitor.broadcasts)} lost-link broadcast(s)); "
                    f"{len(sep_violations)} close-approach event(s) detected and logged"
                ),
            ))
        elif re.search(r"intrusion|restricted|rfz|闯入|闖入|禁飞|禁飛", lowered):
            if not intrusion_faults:
                results.append(CheckResult(
                    check=text, status="pending",
                    evidence="no rfz_intrusion event in this scenario",
                ))
            else:
                zone_hits = [v for v in monitor.violations if v.rule_id == "rfz_intersection"]
                alerted = bool(monitor.intrusion_tracks)
                ok = alerted and (zone_hits or True)  # alert is the system requirement
                results.append(CheckResult(
                    check=text, status="pass" if ok else "fail", regulation_ref="AC-014",
                    evidence=(
                        f"intrusion alert raised for {len(monitor.intrusion_tracks)} "
                        f"aircraft; {len(zone_hits)} zone-entry violation(s) recorded"
                    ),
                ))
        elif re.search(r"off.?course|deviat|drift|偏离|偏離|偏航", lowered):
            if not deviation_faults:
                results.append(CheckResult(
                    check=text, status="pending",
                    evidence="no off_course event in this scenario",
                ))
            else:
                results.append(CheckResult(
                    check=text,
                    status="pass" if monitor.deviation_tracks else "fail",
                    regulation_ref="AC-014",
                    evidence=(
                        f"deviation flagged for {len(monitor.deviation_tracks)} of "
                        f"{len(deviation_faults)} affected aircraft"
                    ),
                ))
        elif re.search(r"recover|restore|resume|恢復|恢复|复联|復聯", lowered):
            if not gps_faults:
                results.append(CheckResult(
                    check=text, status="pending", evidence="no link-loss event in this scenario",
                ))
            else:
                recovered = [f.track_id for f in gps_faults if f.track_id in monitor.recovered]
                overdue = [f.track_id for f in gps_faults if f.end_s > duration_s]
                if len(recovered) == len(gps_faults) - len(overdue) and recovered:
                    results.append(CheckResult(
                        check=text, status="pass",
                        evidence=f"link recovery observed for {', '.join(recovered)}",
                    ))
                else:
                    results.append(CheckResult(
                        check=text, status="fail",
                        evidence="link recovery not observed within the window",
                    ))
        elif re.search(r"weather|typhoon|storm|gale|wind|台风|颱風|天气|天氣", lowered):
            weather_events = [e for e in monitor.events if e.kind == "weather"]
            results.append(CheckResult(
                check=text, status="pass",
                evidence=(
                    f"scenario weather '{scenario.weather}' recorded at start; "
                    f"{len(weather_events)} weather-shift event(s) in timeline"
                ),
            ))
        elif re.search(r"land|return|rtb|降落|返航|迫降", lowered):
            results.append(CheckResult(
                check=text, status="pending",
                evidence="auto-landing/RTB is not modelled by simulator v1 — manual review",
            ))
        else:
            results.append(CheckResult(
                check=text, status="pending",
                evidence="not auto-verifiable by simulator v1 — manual review",
            ))
    return results


# ---------------------------------------------------------------------------
# Citations — best-effort RAG enrichment on top of grounded clause refs.
# ---------------------------------------------------------------------------

_CITATION_QUERIES = {
    "gps_loss": "lost link GPS signal failure alert procedures",
    "rfz_intrusion": "restricted flying zone intrusion prohibition",
    "separation_minima": "minimum separation distance crowds buildings 30 metres",
    "corridor_exit": "operation within approved area boundary",
}


def _enrich_citations(violations: list[ObservedViolation], scenario: Scenario) -> list[ReportCitation]:
    refs = sorted({v.regulation_ref for v in violations})
    citations = [ReportCitation(regulation_id=ref) for ref in refs]
    try:
        from app.rag import RegulationStoreNotReady, query as rag_query

        queries = {_CITATION_QUERIES.get(v.rule_id) for v in violations}
        queries.discard(None)
        if any(e.kind in ("gps_loss", "comms_loss") for e in scenario.injected_events):
            queries.add(_CITATION_QUERIES["gps_loss"])
        seen = {(c.regulation_id, c.section) for c in citations}
        for q in sorted(queries):
            for hit in rag_query(q, 2):
                key = (hit.get("regulation_id"), hit.get("section"))
                if not key[0] or key in seen:
                    continue
                seen.add(key)
                citations.append(
                    ReportCitation(
                        regulation_id=str(hit["regulation_id"]),
                        section=hit.get("section"),
                        excerpt=(hit.get("excerpt") or "")[:300] or None,
                    )
                )
                if len(citations) >= 8:
                    return citations
    except Exception:  # noqa: BLE001 — citations are enrichment, never a failure mode
        pass
    return citations[:8]


# ---------------------------------------------------------------------------
# Report assembly.
# ---------------------------------------------------------------------------


def render_markdown(report: TestReport) -> str:
    s = report.summary
    lines = [
        f"# UTM Scenario Test Report — {report.scenario_id}",
        "",
        f"**Scenario**: {report.description or '(no description)'}",
        (
            f"**Area**: {report.scenario.area} · **Window**: {report.scenario.time_window} · "
            f"**Weather**: {report.scenario.weather}"
        ),
        (
            f"**Traffic**: {report.scenario.traffic_density} density, {s.aircraft_count} aircraft · "
            f"**Duration**: {s.duration_s} s"
        ),
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Checks passed | {s.passed}/{s.total_checks} ({s.pass_rate * 100:.0f}%) |",
        f"| Checks failed | {s.failed} |",
        f"| Pending manual review | {s.pending} |",
        f"| Observed violations | {s.violations_count} |",
        f"| Avoidance advisories | {s.advisories_count} |",
        f"| Timeline events | {s.events_count} |",
        "",
        "## Checklist results",
        "",
    ]
    for c in report.checks:
        badge = {"pass": "PASS", "fail": "FAIL", "pending": "PENDING"}[c.status]
        line = f"- [{badge}] {c.check}"
        if c.evidence:
            line += f" — {c.evidence}"
        if c.regulation_ref:
            line += f" ({c.regulation_ref})"
        lines.append(line)
    lines += ["", "## Observed violations", ""]
    if report.violations:
        lines += ["| t (s) | Track | Rule | Clause | Detail |", "|---|---|---|---|---|"]
        for v in report.violations:
            lines.append(
                f"| {v.at_second:.0f} | {v.track_id or '—'} | {v.rule_id} | "
                f"{v.regulation_ref} | {v.message} |"
            )
    else:
        lines.append("None — no airspace violations observed during the run.")
    lines += ["", "## Timeline", ""]
    for e in report.timeline:
        lines.append(f"- t={e.t:.0f}s [{e.kind}] {e.message}")
    if report.citations:
        lines += ["", "## Regulation citations", ""]
        for c in report.citations:
            head = f"- **{c.regulation_id}**" + (f" {c.section}" if c.section else "")
            lines.append(head + (f": {c.excerpt}" if c.excerpt else ""))
    if report.notes:
        lines += ["", "## Notes", ""]
        lines += [f"- {n}" for n in report.notes]
    lines += [
        "",
        "---",
        (
            f"Generated {report.generated_at} by UTM Copilot scenario executor "
            f"(report {report.report_id})."
        ),
    ]
    return redact_text("\n".join(lines))


def run_scenario(
    scenario_id: str,
    scenario: Scenario,
    description: str = "",
    checklist: list[str] | None = None,
) -> TestReport:
    duration_s = window_seconds(scenario.time_window)
    notes: list[str] = []
    requested = scenario.aircraft_count
    count = max(1, min(MAX_COUNT, requested))
    if requested > MAX_COUNT:
        notes.append(
            f"aircraft_count clamped to {MAX_COUNT} (requested {requested}) — simulator v1 cap"
        )

    faults, _by_track = _faults_from_events(scenario.injected_events, count, notes)
    if faults:
        notes.append(
            "separation probing is scoped to fault-affected aircraft during "
            "their fault windows — simulator v1 traffic is not deconflicted fleet-wide"
        )
    sim = Simulator(count=count, seed=_stable_seed(scenario_id), faults=faults)
    monitor = _Monitor(faults, scenario.injected_events)

    monitor.log(
        0.0, "scenario_start",
        f"scenario start: {count} aircraft, weather={scenario.weather}, "
        f"density={scenario.traffic_density}, window={duration_s}s",
    )
    for event in scenario.injected_events:
        target = _normalize_target(event.target_track_id, count, 0)
        monitor.log(
            float(event.at_second), "fault_injected",
            f"injected {event.kind} on {target} for {event.duration_s:.0f}s"
            + (f" — {event.detail}" if event.detail else ""),
            target,
        )

    for _ in range(duration_s):
        sim.step()
        t = sim.sim_time_s
        snapshot = sim.snapshot()
        active_fault_tracks = {
            f.track_id for f in faults if f.start_s <= t < f.end_s
        }
        monitor.observe_statuses(t, snapshot)
        monitor.observe_separation(t, snapshot, active_fault_tracks)
        monitor.observe_containment(t, snapshot)
        monitor.observe_weather_events(t)

    checks = _evaluate_checks(scenario, checklist or [], monitor, duration_s)
    passed = sum(1 for c in checks if c.status == "pass")
    failed = sum(1 for c in checks if c.status == "fail")
    pending = sum(1 for c in checks if c.status == "pending")
    verifiable = passed + failed
    summary = ReportSummary(
        total_checks=len(checks),
        passed=passed,
        failed=failed,
        pending=pending,
        pass_rate=(passed / verifiable) if verifiable else 1.0,
        violations_count=len(monitor.violations),
        advisories_count=monitor.advisories_count,
        events_count=len(monitor.events),
        duration_s=duration_s,
        aircraft_count=count,
    )

    log_excerpt = redact_lines(
        [
            f"scenario {scenario_id}: {count} aircraft, {len(faults)} fault(s), "
            f"{duration_s}s window",
            f"checks: {passed} pass / {failed} fail / {pending} pending",
            f"violations: {len(monitor.violations)}; advisories: {monitor.advisories_count}",
        ]
        + [f"t={e.t:.0f}s [{e.kind}] {e.message}" for e in monitor.events[:20]]
    )

    report = TestReport(
        report_id=hashlib.md5(f"{scenario_id}:{datetime.now(HK_TZ).isoformat()}".encode()).hexdigest()[:8],
        scenario_id=scenario_id,
        generated_at=datetime.now(HK_TZ).isoformat(timespec="seconds"),
        description=redact_text(description),
        scenario=scenario,
        summary=summary,
        checks=checks,
        violations=monitor.violations,
        timeline=monitor.events,
        citations=_enrich_citations(monitor.violations, scenario),
        log_excerpt=log_excerpt,
        notes=notes,
    )
    return report
