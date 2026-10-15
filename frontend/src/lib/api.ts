/**
 * Backend API client — mirrors the API contract (dev-readme §5 / plan §4.7).
 * Base URL: NEXT_PUBLIC_API_URL, defaulting to the local backend port.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:43124";

// ---------- types (mirror backend/app/schemas) ----------

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

export interface MapAnnotation {
  kind: "rejected_route" | "suggested_route" | "rfz_highlight" | "track_marker";
  geojson: Record<string, unknown>;
  label?: string | null;
  color?: string | null;
}

export interface Citation {
  regulation_id: string;
  section?: string | null;
  excerpt?: string | null;
}

export interface ChatResponse {
  reply: string;
  map_annotations: MapAnnotation[];
  citations: Citation[];
}

export interface FlightPlanParams {
  aircraft_category?: "cat_a" | "cat_b";
  max_altitude_ft?: number;
  within_visual_line_of_sight?: boolean;
  operator?: string | null;
}

export interface RuleViolation {
  rule_id: string;
  regulation_ref: string;
  message: string;
  /** Index of the offending route segment (0-based), when applicable. */
  segment_index?: number | null;
}

export interface Suggestion {
  kind: "reroute" | "lower_altitude" | "reschedule" | "change_aircraft" | (string & {});
  description: string;
  /** Patched route (GeoJSON LineString) to render in green, when provided. */
  patched_route_geojson?: Record<string, unknown> | null;
}

export interface FlightPlanCheckResponse {
  verdict: "approved" | "rejected";
  violations: RuleViolation[];
  suggestions: Suggestion[];
}

export interface AirspaceResponse {
  area: string;
  active_restrictions: string[];
  rfz_count: number;
  active_tracks: Track[];
}

// ---------- Phase 3: scenarios, test reports, trilingual briefs ----------

export interface InjectedEvent {
  kind: "gps_loss" | "rfz_intrusion" | "off_course" | "weather_shift" | "comms_loss";
  at_second: number;
  duration_s: number;
  target_track_id?: string | null;
  detail?: string | null;
}

export interface ExpectedBehavior {
  check: string;
  pass_criteria?: string | null;
}

export interface Scenario {
  area: string;
  time_window: string;
  weather: string;
  traffic_density: "low" | "medium" | "high";
  aircraft_count: number;
  injected_events: InjectedEvent[];
  expected_system_behavior: ExpectedBehavior[];
}

export interface ScenarioCreateResponse {
  id: string;
  scenario_json: Scenario;
  checklist: string[];
  warnings: string[];
}

export interface CheckResult {
  check: string;
  status: "pass" | "fail" | "pending";
  evidence?: string | null;
  regulation_ref?: string | null;
}

export interface TimelineEvent {
  t: number;
  kind:
    | "scenario_start"
    | "fault_injected"
    | "fault_detected"
    | "fault_recovered"
    | "advisory"
    | "violation"
    | "weather"
    | "note";
  message: string;
  track_id?: string | null;
}

export interface ObservedViolation {
  rule_id: string;
  regulation_ref: string;
  message: string;
  track_id?: string | null;
  at_second?: number | null;
}

export interface ReportCitation {
  regulation_id: string;
  section?: string | null;
  excerpt?: string | null;
}

export interface ReportSummary {
  total_checks: number;
  passed: number;
  failed: number;
  pending: number;
  pass_rate: number;
  violations_count: number;
  advisories_count: number;
  events_count: number;
  duration_s: number;
  aircraft_count: number;
}

export interface TestReport {
  report_id: string;
  scenario_id: string;
  generated_at: string;
  description: string;
  scenario: Scenario;
  summary: ReportSummary;
  checks: CheckResult[];
  violations: ObservedViolation[];
  timeline: TimelineEvent[];
  citations: ReportCitation[];
  log_excerpt: string[];
  notes: string[];
}

export interface ScenarioRunResponse {
  scenario_id: string;
  status: "completed" | "failed";
  report_url: string;
  log_excerpt: string[];
  report: TestReport | null;
  markdown: string | null;
}

export type BriefAudience = "cad_technical" | "legco_policy" | "community";
export type BriefLang = "zh" | "en" | "yue";

export interface BriefResponse {
  scenario_id: string;
  audience: string;
  briefs: Record<BriefLang, string>;
  generated_with: "llm" | "mixed" | "fallback";
}

export interface Track {
  track_id: string;
  lon: number;
  lat: number;
  altitude_m: number;
  heading_deg: number;
  speed_mps: number;
  status: string;
}

// ---------- endpoints ----------

export async function sendChat(
  message: string,
  route?: Record<string, unknown> | null,
): Promise<ChatResponse> {
  const res = await fetch(`${API_BASE}/api/v1/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, route: route ?? undefined }),
  });
  if (!res.ok) throw new Error(`chat failed: ${res.status}`);
  return res.json();
}

export async function checkFlightPlan(
  routeGeoJson: Record<string, unknown>,
  params: FlightPlanParams = {},
): Promise<FlightPlanCheckResponse> {
  const res = await fetch(`${API_BASE}/api/v1/flight-plans/check`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ route_geojson: routeGeoJson, params }),
  });
  if (!res.ok) throw new Error(`flight plan check failed: ${res.status}`);
  return res.json();
}

export async function getAirspace(): Promise<AirspaceResponse> {
  const res = await fetch(`${API_BASE}/api/v1/airspace`);
  if (!res.ok) throw new Error(`airspace failed: ${res.status}`);
  return res.json();
}

/** SSE endpoint URL — consume with `new EventSource(tracksStreamUrl())`. */
export function tracksStreamUrl(): string {
  return `${API_BASE}/api/v1/tracks/stream`;
}

// ---------- Phase 3 endpoints ----------

export async function createScenario(description: string): Promise<ScenarioCreateResponse> {
  const res = await fetch(`${API_BASE}/api/v1/scenarios`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ description }),
  });
  if (!res.ok) throw new Error(`scenario generation failed: ${res.status}`);
  return res.json();
}

export async function runScenario(scenarioId: string): Promise<ScenarioRunResponse> {
  const res = await fetch(`${API_BASE}/api/v1/scenarios/${scenarioId}/run`, {
    method: "POST",
  });
  if (!res.ok) throw new Error(`scenario run failed: ${res.status}`);
  return res.json();
}

/** Direct export URL (browser download) for the latest report. */
export function reportExportUrl(scenarioId: string, format: "json" | "markdown"): string {
  return `${API_BASE}/api/v1/scenarios/${scenarioId}/report?format=${format}`;
}

export async function createBrief(
  scenarioId: string,
  audience: BriefAudience,
): Promise<BriefResponse> {
  const res = await fetch(`${API_BASE}/api/v1/scenarios/${scenarioId}/brief`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ audience }),
  });
  if (!res.ok) throw new Error(`brief generation failed: ${res.status}`);
  return res.json();
}
