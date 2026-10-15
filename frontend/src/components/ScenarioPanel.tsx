"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import Markdown from "@/components/Markdown";
import {
  createBrief,
  createScenario,
  reportExportUrl,
  runScenario,
  type BriefAudience,
  type BriefLang,
  type BriefResponse,
  type ScenarioCreateResponse,
  type ScenarioRunResponse,
  type TimelineEvent,
} from "@/lib/api";

/**
 * Phase-3 scenario lab: one plain-language sentence → scenario JSON +
 * checklist → one-click simulator run → structured test report → trilingual
 * briefs (CAD technical / LegCo policy / community notice).
 */

const EXAMPLES = [
  {
    label: "台风 + GPS 丢失",
    text: "台风逼近，沙田 10 架无人机同时作业，第 5 分钟一架丢 GPS",
  },
  {
    label: "RFZ 闯入 Intrusion",
    text: "Evening rush: 6 drones over Sha Tin, one intrudes into the racecourse restricted zone at minute 2",
  },
  {
    label: "偏航 Off-course",
    text: "大風警告：4 架無人機作業，第 1 分鐘一架偏離航線",
  },
];

const AUDIENCES: { id: BriefAudience; label: string; hint: string }[] = [
  { id: "cad_technical", label: "CAD 技术摘要", hint: "technical" },
  { id: "legco_policy", label: "LegCo 政策简报", hint: "policy" },
  { id: "community", label: "社区通告", hint: "plain" },
];

const LANG_TABS: { id: BriefLang; label: string }[] = [
  { id: "zh", label: "中文" },
  { id: "en", label: "English" },
  { id: "yue", label: "粵語" },
];

const KIND_LABEL: Record<string, string> = {
  gps_loss: "GPS 丢失",
  rfz_intrusion: "RFZ 闯入",
  off_course: "偏航",
  weather_shift: "天气突变",
  comms_loss: "通信中断",
};

const EVENT_COLOR: Record<TimelineEvent["kind"], string> = {
  scenario_start: "text-muted-foreground",
  fault_injected: "text-amber-600 dark:text-amber-400",
  fault_detected: "text-red-600 dark:text-red-400",
  fault_recovered: "text-emerald-600 dark:text-emerald-400",
  advisory: "text-sky-600 dark:text-sky-400",
  violation: "text-red-700 dark:text-red-400",
  weather: "text-violet-600 dark:text-violet-400",
  note: "text-muted-foreground",
};

function download(filename: string, content: string, type: string) {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function StatusBadge({ status }: { status: "pass" | "fail" | "pending" }) {
  const style =
    status === "pass"
      ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300"
      : status === "fail"
        ? "bg-red-100 text-red-700 dark:bg-red-950 dark:text-red-300"
        : "bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300";
  const label = status === "pass" ? "PASS" : status === "fail" ? "FAIL" : "PENDING";
  return (
    <span className={`rounded px-1.5 py-0.5 font-mono text-[10px] font-semibold ${style}`}>
      {label}
    </span>
  );
}

export default function ScenarioPanel() {
  const [description, setDescription] = useState(EXAMPLES[0].text);
  const [busy, setBusy] = useState<"generate" | "run" | "brief" | null>(null);
  const [created, setCreated] = useState<ScenarioCreateResponse | null>(null);
  const [run, setRun] = useState<ScenarioRunResponse | null>(null);
  const [showJson, setShowJson] = useState(false);
  const [showTimeline, setShowTimeline] = useState(true);
  const [audience, setAudience] = useState<BriefAudience>("community");
  const [brief, setBrief] = useState<BriefResponse | null>(null);
  const [briefLang, setBriefLang] = useState<BriefLang>("zh");
  const [error, setError] = useState<string | null>(null);

  async function onGenerate() {
    const text = description.trim();
    if (!text || busy) return;
    setBusy("generate");
    setError(null);
    setCreated(null);
    setRun(null);
    setBrief(null);
    try {
      setCreated(await createScenario(text));
    } catch {
      setError("Scenario generation failed — is the backend running on :43124?");
    } finally {
      setBusy(null);
    }
  }

  async function onRun() {
    if (!created || busy) return;
    setBusy("run");
    setError(null);
    setBrief(null);
    try {
      setRun(await runScenario(created.id));
    } catch {
      setError("Scenario run failed — check the backend logs.");
    } finally {
      setBusy(null);
    }
  }

  async function onBrief(next: BriefAudience) {
    if (!run || busy) return;
    setAudience(next);
    setBusy("brief");
    setError(null);
    try {
      setBrief(await createBrief(run.scenario_id, next));
    } catch {
      setError("Brief generation failed — check the backend logs.");
    } finally {
      setBusy(null);
    }
  }

  const report = run?.report ?? null;
  const summary = report?.summary ?? null;
  const passPct = summary ? Math.round(summary.pass_rate * 100) : 0;

  return (
    <div className="flex h-full flex-col">
      <header className="border-b px-4 py-3">
        <h1 className="text-sm font-semibold">Scenario Lab 场景实验室</h1>
        <p className="text-xs text-muted-foreground">
          One sentence → test scenario → simulator run → report + 三语简报
        </p>
      </header>

      <div className="flex-1 space-y-4 overflow-y-auto p-4">
        <section className="space-y-2">
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={3}
            placeholder="用一句大白话描述测试场景… e.g. 台风逼近，10 架无人机同时作业，第 5 分钟一架丢 GPS"
            className="w-full rounded-md border bg-background px-3 py-2 text-sm outline-none focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/40"
            disabled={busy === "generate"}
          />
          <div className="flex flex-wrap gap-1.5">
            {EXAMPLES.map((ex) => (
              <button
                key={ex.label}
                type="button"
                onClick={() => setDescription(ex.text)}
                className="rounded-full border bg-muted/50 px-2 py-0.5 text-[11px] text-muted-foreground hover:bg-muted"
              >
                {ex.label}
              </button>
            ))}
          </div>
          <Button
            onClick={onGenerate}
            disabled={busy !== null || !description.trim()}
            className="w-full"
          >
            {busy === "generate" ? "Generating… 生成中" : "Generate scenario 生成场景"}
          </Button>
        </section>

        {error && (
          <div className="rounded-md border border-red-300 bg-red-50 px-3 py-2 text-xs text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300">
            {error}
          </div>
        )}

        {created && (
          <section className="space-y-2 rounded-xl border bg-card p-3 shadow-sm">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-semibold">Scenario {created.id}</h2>
              <button
                type="button"
                onClick={() => setShowJson((v) => !v)}
                className="text-xs text-muted-foreground underline-offset-2 hover:underline"
              >
                {showJson ? "hide JSON" : "show JSON"}
              </button>
            </div>

            {created.warnings.length > 0 && (
              <div className="rounded-md border border-amber-300 bg-amber-50 px-2 py-1.5 text-[11px] text-amber-800 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-300">
                {created.warnings.map((w, i) => (
                  <p key={i}>{w}</p>
                ))}
              </div>
            )}

            <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
              <dt className="text-muted-foreground">Area</dt>
              <dd>{created.scenario_json.area}</dd>
              <dt className="text-muted-foreground">Weather</dt>
              <dd>{created.scenario_json.weather}</dd>
              <dt className="text-muted-foreground">Traffic</dt>
              <dd>
                {created.scenario_json.traffic_density} · {created.scenario_json.aircraft_count}{" "}
                aircraft
              </dd>
              <dt className="text-muted-foreground">Window</dt>
              <dd className="font-mono text-[11px]">{created.scenario_json.time_window}</dd>
            </dl>

            {created.scenario_json.injected_events.length > 0 && (
              <div className="space-y-1">
                <p className="text-xs font-medium text-muted-foreground">Injected events</p>
                {created.scenario_json.injected_events.map((e, i) => (
                  <div
                    key={i}
                    className="rounded-md bg-muted/60 px-2 py-1 text-[11px]"
                  >
                    <span className="font-medium">{KIND_LABEL[e.kind] ?? e.kind}</span>
                    {" · "}t={e.at_second}s · {e.duration_s}s
                    {e.target_track_id ? ` · ${e.target_track_id}` : ""}
                    {e.detail ? ` — ${e.detail}` : ""}
                  </div>
                ))}
              </div>
            )}

            <div className="space-y-1">
              <p className="text-xs font-medium text-muted-foreground">
                Test checklist 测试检查单
              </p>
              <ul className="space-y-1 text-xs">
                {created.checklist.map((c, i) => (
                  <li key={i} className="flex gap-1.5">
                    <span className="mt-0.5 inline-block size-2 shrink-0 rounded-full border border-primary" />
                    <span>{c}</span>
                  </li>
                ))}
              </ul>
            </div>

            {showJson && (
              <pre className="max-h-56 overflow-auto rounded-md bg-muted p-2 font-mono text-[10px] leading-relaxed">
                {JSON.stringify(created.scenario_json, null, 2)}
              </pre>
            )}

            <Button onClick={onRun} disabled={busy !== null} className="w-full">
              {busy === "run" ? "Running simulator… 运行中" : "Run scenario 运行场景 ▶"}
            </Button>
          </section>
        )}

        {report && summary && (
          <section className="space-y-3 rounded-xl border bg-card p-3 shadow-sm">
            <div className="flex items-end justify-between">
              <div>
                <h2 className="text-sm font-semibold">Test report 测试报告</h2>
                <p className="text-[11px] text-muted-foreground">
                  {summary.aircraft_count} aircraft · {summary.duration_s}s ·{" "}
                  {report.generated_at}
                </p>
              </div>
              <div
                className={`text-2xl font-bold ${
                  passPct >= 80
                    ? "text-emerald-600"
                    : passPct >= 50
                      ? "text-amber-600"
                      : "text-red-600"
                }`}
              >
                {passPct}%
              </div>
            </div>

            <div className="flex flex-wrap gap-1.5 text-[11px]">
              <span className="rounded bg-emerald-100 px-1.5 py-0.5 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300">
                {summary.passed} pass
              </span>
              <span className="rounded bg-red-100 px-1.5 py-0.5 text-red-700 dark:bg-red-950 dark:text-red-300">
                {summary.failed} fail
              </span>
              <span className="rounded bg-amber-100 px-1.5 py-0.5 text-amber-700 dark:bg-amber-950 dark:text-amber-300">
                {summary.pending} pending
              </span>
              <span className="rounded bg-muted px-1.5 py-0.5">
                {summary.violations_count} violations
              </span>
              <span className="rounded bg-muted px-1.5 py-0.5">
                {summary.advisories_count} advisories
              </span>
            </div>

            <div className="space-y-1.5">
              <p className="text-xs font-medium text-muted-foreground">Checklist results</p>
              {report.checks.map((c, i) => (
                <div key={i} className="space-y-0.5 rounded-md bg-muted/50 px-2 py-1.5">
                  <div className="flex items-start justify-between gap-2">
                    <span className="text-xs">{c.check}</span>
                    <StatusBadge status={c.status} />
                  </div>
                  {c.evidence && (
                    <p className="text-[11px] text-muted-foreground">
                      {c.evidence}
                      {c.regulation_ref ? ` (${c.regulation_ref})` : ""}
                    </p>
                  )}
                </div>
              ))}
            </div>

            {report.violations.length > 0 && (
              <div className="space-y-1">
                <p className="text-xs font-medium text-red-600">Observed violations 违规明细</p>
                {report.violations.map((v, i) => (
                  <div
                    key={i}
                    className="rounded-md border border-red-200 bg-red-50 px-2 py-1 text-[11px] dark:border-red-900 dark:bg-red-950"
                  >
                    t={v.at_second}s · {v.track_id ?? "—"} · {v.message}{" "}
                    <span className="font-mono">({v.regulation_ref})</span>
                  </div>
                ))}
              </div>
            )}

            <div className="space-y-1">
              <button
                type="button"
                onClick={() => setShowTimeline((v) => !v)}
                className="text-xs font-medium text-muted-foreground underline-offset-2 hover:underline"
              >
                {showTimeline ? "▾" : "▸"} Timeline 时间线 ({report.timeline.length} events)
              </button>
              {showTimeline && (
                <div className="max-h-44 space-y-0.5 overflow-y-auto rounded-md bg-muted/40 p-2 font-mono text-[10.5px]">
                  {report.timeline.map((e, i) => (
                    <p key={i} className={EVENT_COLOR[e.kind] ?? ""}>
                      t={e.t}s [{e.kind}] {e.message}
                    </p>
                  ))}
                </div>
              )}
            </div>

            {report.citations.length > 0 && (
              <div className="space-y-0.5 text-[11px] text-muted-foreground">
                <p className="font-medium">Citations 引用条款</p>
                {report.citations.map((c, i) => (
                  <p key={i} className="font-mono">
                    {c.regulation_id}
                    {c.section ? ` · ${c.section}` : ""}
                  </p>
                ))}
              </div>
            )}

            <div className="flex gap-2">
              <Button
                variant="outline"
                size="sm"
                className="flex-1"
                onClick={() =>
                  download(
                    `utm-report-${report.scenario_id}.json`,
                    JSON.stringify(report, null, 2),
                    "application/json",
                  )
                }
              >
                Export JSON
              </Button>
              <Button
                variant="outline"
                size="sm"
                className="flex-1"
                onClick={() =>
                  window.open(reportExportUrl(report.scenario_id, "markdown"), "_blank")
                }
              >
                Export Markdown
              </Button>
            </div>
          </section>
        )}

        {report && (
          <section className="space-y-2 rounded-xl border bg-card p-3 shadow-sm">
            <h2 className="text-sm font-semibold">Trilingual brief 三语简报</h2>
            <div className="grid grid-cols-3 gap-1.5">
              {AUDIENCES.map((a) => (
                <button
                  key={a.id}
                  type="button"
                  onClick={() => onBrief(a.id)}
                  disabled={busy !== null}
                  className={`rounded-md border px-1.5 py-1.5 text-[11px] leading-tight transition-colors ${
                    audience === a.id && brief
                      ? "border-primary bg-primary/10 font-medium"
                      : "bg-muted/40 hover:bg-muted"
                  } disabled:opacity-50`}
                >
                  {a.label}
                </button>
              ))}
            </div>

            {busy === "brief" && (
              <p className="py-4 text-center text-xs text-muted-foreground">
                Drafting briefs in 中文 / English / 粵語…
              </p>
            )}

            {brief && busy !== "brief" && (
              <>
                <div className="flex items-center justify-between">
                  <div className="flex gap-1">
                    {LANG_TABS.map((l) => (
                      <button
                        key={l.id}
                        type="button"
                        onClick={() => setBriefLang(l.id)}
                        className={`rounded-full px-2.5 py-0.5 text-[11px] ${
                          briefLang === l.id
                            ? "bg-primary text-primary-foreground"
                            : "bg-muted/60 hover:bg-muted"
                        }`}
                      >
                        {l.label}
                      </button>
                    ))}
                  </div>
                  <span className="text-[10px] text-muted-foreground">
                    {brief.generated_with === "llm"
                      ? "LLM"
                      : brief.generated_with === "mixed"
                        ? "LLM + offline"
                        : "offline template"}
                  </span>
                </div>
                <div className="max-h-72 overflow-y-auto rounded-md border bg-background p-3">
                  <Markdown source={brief.briefs[briefLang]} />
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  className="w-full"
                  onClick={() =>
                    download(
                      `utm-brief-${brief.scenario_id}-${brief.audience}-${briefLang}.md`,
                      brief.briefs[briefLang],
                      "text/markdown",
                    )
                  }
                >
                  Download {LANG_TABS.find((l) => l.id === briefLang)?.label} .md
                </Button>
              </>
            )}
          </section>
        )}
      </div>
    </div>
  );
}
