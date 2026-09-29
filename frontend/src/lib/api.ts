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

export interface FlightPlanCheckResponse {
  verdict: "approved" | "rejected";
  violations: { rule_id: string; regulation_ref: string; message: string }[];
  suggestions: { kind: string; description: string }[];
}

export interface AirspaceResponse {
  area: string;
  active_restrictions: string[];
  rfz_count: number;
  active_tracks: Track[];
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

export async function sendChat(message: string): Promise<ChatResponse> {
  const res = await fetch(`${API_BASE}/api/v1/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });
  if (!res.ok) throw new Error(`chat failed: ${res.status}`);
  return res.json();
}

export async function checkFlightPlan(
  routeGeoJson: Record<string, unknown>,
): Promise<FlightPlanCheckResponse> {
  const res = await fetch(`${API_BASE}/api/v1/flight-plans/check`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ route_geojson: routeGeoJson, params: {} }),
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
