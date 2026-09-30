"""Trajectory simulator v1 — multi-aircraft 1 Hz traffic, Sha Tin ↔ Science Park.

Implements project-plan §4.3 (航迹模拟器) / step 1.4: simple kinematics per
aircraft (takeoff → cruise legs → landing → turnaround → respawn, so demo
traffic never runs dry) plus per-track fault-injection hooks (gps_loss /
deviation / intrusion) that phase-3 scenario scripting drives via FaultSpec.

Geo math is a plain equirectangular projection centred on the corridor —
accurate to well under 0.1% at this scale (< 5 km), so no third-party geo
dependency is needed.
"""

import asyncio
import math
import random
import time
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field, replace

from app.schemas.airspace import Track

# Corridor bounding box (project-plan §4.3 demo area).
CORRIDOR_MIN_LAT = 22.380
CORRIDOR_MAX_LAT = 22.430
CORRIDOR_MIN_LON = 114.190
CORRIDOR_MAX_LON = 114.210

# Waypoints trace the Shing Mun River → Tolo Harbour shoreline, the plausible
# low-altitude route between Sha Tin town centre and HK Science Park.
SHA_TIN = (114.1915, 22.3830)
RIVER_MID = (114.1975, 22.3920)
MA_LIU_SHUI = (114.2030, 22.4090)
SCIENCE_PARK = (114.2090, 22.4255)

ROUTE_TEMPLATES = [
    [SHA_TIN, RIVER_MID, MA_LIU_SHUI, SCIENCE_PARK],  # outbound
    [SCIENCE_PARK, MA_LIU_SHUI, RIVER_MID, SHA_TIN],  # return
    [MA_LIU_SHUI, RIVER_MID, SHA_TIN, RIVER_MID, MA_LIU_SHUI],  # shuttle
]

# Demo RFZ-style polygon astride the river leg (Sha Tin Racecourse area),
# used when an intrusion fault does not supply its own polygon.
DEFAULT_INTRUSION_POLYGON = (
    (114.1980, 22.3970),
    (114.2040, 22.3970),
    (114.2040, 22.4030),
    (114.1980, 22.4030),
)

SIM_DT_S = 1.0
DEFAULT_COUNT = 8
MAX_COUNT = 10
DEFAULT_SEED = 20261024

CLIMB_RATE_MPS = 2.5
DESCENT_RATE_MPS = 2.0
ACCEL_MPS2 = 3.0
TURN_RATE_DEG_S = 25.0
ARRIVAL_RADIUS_M = 25.0
# Cruise altitudes stay under the 300 ft (≈91 m) AC-014/AC-015 ceiling the
# rule engine enforces, so nominal traffic is compliant by construction.
CRUISE_ALT_RANGE_M = (50.0, 85.0)
CRUISE_SPEED_RANGE_MPS = (10.0, 16.0)
DEVIATION_HEADING_BIAS_DEG = 28.0

_LAT0_RAD = math.radians(22.40)
_M_PER_DEG_LAT = 111_320.0
_M_PER_DEG_LON = 111_320.0 * math.cos(_LAT0_RAD)

# Scenario-schema (app/schemas/scenario.py InjectedEvent.kind) aliases, so
# phase-3 scenario JSON can drive these hooks without a translation layer.
FAULT_KIND_ALIASES = {
    "gps_loss": "gps_loss",
    "deviation": "deviation",
    "off_course": "deviation",
    "intrusion": "intrusion",
    "rfz_intrusion": "intrusion",
}


def _to_xy(lonlat: tuple[float, float]) -> tuple[float, float]:
    return lonlat[0] * _M_PER_DEG_LON, lonlat[1] * _M_PER_DEG_LAT


def distance_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    ax, ay = _to_xy(a)
    bx, by = _to_xy(b)
    return math.hypot(bx - ax, by - ay)


def bearing_deg(a: tuple[float, float], b: tuple[float, float]) -> float:
    ax, ay = _to_xy(a)
    bx, by = _to_xy(b)
    return math.degrees(math.atan2(bx - ax, by - ay)) % 360.0


def _advance(lon: float, lat: float, heading_deg: float, dist_m: float) -> tuple[float, float]:
    dx = dist_m * math.sin(math.radians(heading_deg))
    dy = dist_m * math.cos(math.radians(heading_deg))
    return lon + dx / _M_PER_DEG_LON, lat + dy / _M_PER_DEG_LAT


def _turn_toward(current: float, target: float, max_delta: float) -> float:
    delta = (target - current + 180.0) % 360.0 - 180.0
    if abs(delta) <= max_delta:
        return target % 360.0
    return (current + math.copysign(max_delta, delta)) % 360.0


def point_in_polygon(lon: float, lat: float, polygon: tuple[tuple[float, float], ...]) -> bool:
    inside = False
    j = len(polygon) - 1
    for i in range(len(polygon)):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


@dataclass(frozen=True)
class FaultSpec:
    """One per-track fault-injection event; times are sim seconds.

    kind: gps_loss (reported position freezes, then jumps on recovery),
    deviation (heading bias drifts the aircraft off its route), intrusion
    (steers into `polygon`, or DEFAULT_INTRUSION_POLYGON when omitted).
    """

    kind: str
    track_id: str
    start_s: float
    duration_s: float
    polygon: tuple[tuple[float, float], ...] | None = None

    @property
    def end_s(self) -> float:
        return self.start_s + self.duration_s


def parse_fault_specs(raw: str) -> list[FaultSpec]:
    """Parse the compact query-string fault format used by the SSE endpoint.

    "gps_loss:SIM-002@30+15|intrusion:SIM-004@60+20:lon,lat;lon,lat;..."
    — kind:TRACK@start_s+duration_s, specs joined by "|", intrusion may
    append ":lon,lat;lon,lat;..." as its polygon.
    """
    specs: list[FaultSpec] = []
    for chunk in raw.split("|"):
        chunk = chunk.strip()
        if not chunk:
            continue
        parts = chunk.split(":")
        if len(parts) < 2:
            raise ValueError(f"malformed fault spec {chunk!r}; expected kind:TRACK@start+duration")
        kind = FAULT_KIND_ALIASES.get(parts[0].strip())
        if kind is None:
            raise ValueError(
                f"unknown fault kind {parts[0]!r}; expected one of {sorted(FAULT_KIND_ALIASES)}"
            )
        track_id, _, window = parts[1].partition("@")
        start_s, _, duration_s = window.partition("+")
        try:
            polygon = None
            if len(parts) > 2:
                polygon = tuple(
                    (float(pair[0]), float(pair[1]))
                    for pair in (p.split(",") for p in parts[2].split(";"))
                )
            specs.append(
                FaultSpec(
                    kind=kind,
                    track_id=track_id.strip(),
                    start_s=float(start_s),
                    duration_s=float(duration_s),
                    polygon=polygon,
                )
            )
        except (ValueError, IndexError) as exc:
            raise ValueError(f"malformed fault spec {chunk!r}: {exc}") from exc
    return specs


@dataclass
class _Aircraft:
    track_id: str
    route: list[tuple[float, float]]
    cruise_alt_m: float
    cruise_speed_mps: float
    lon: float
    lat: float
    alt_m: float = 0.0
    heading_deg: float = 0.0
    speed_mps: float = 0.0
    phase: str = "on_ground"  # on_ground → takeoff → cruise → landing → on_ground
    waypoint_idx: int = 1
    dwell_s: float = 0.0
    active_kinds: set[str] = field(default_factory=set)
    # Last reported fix latched at gps_loss onset; cleared on recovery so the
    # next snapshot jumps to the true position.
    frozen_fix: tuple[float, float, float, float, float] | None = None


class Simulator:
    """Multi-aircraft corridor traffic world.

    Deterministic for a given seed and step sequence; wall-clock pacing lives
    in step_wallclock() so tests can drive step() directly.
    """

    def __init__(
        self,
        count: int = DEFAULT_COUNT,
        seed: int = DEFAULT_SEED,
        faults: list[FaultSpec] | None = None,
    ) -> None:
        self.sim_time_s = 0.0
        self._rng = random.Random(seed)
        self._faults = [self._normalize(f) for f in (faults or [])]
        self._fault_keys = {self._key(f) for f in self._faults}
        n = max(1, min(MAX_COUNT, count))
        self.aircraft = [self._spawn(i) for i in range(n)]
        self._last_wall = time.monotonic()

    def _spawn(self, i: int) -> _Aircraft:
        template = ROUTE_TEMPLATES[i % len(ROUTE_TEMPLATES)]
        route = [
            (lon + self._rng.uniform(-0.0004, 0.0004), lat + self._rng.uniform(-0.0004, 0.0004))
            for lon, lat in template
        ]
        return _Aircraft(
            track_id=f"SIM-{i + 1:03d}",
            route=route,
            cruise_alt_m=self._rng.uniform(*CRUISE_ALT_RANGE_M),
            cruise_speed_mps=self._rng.uniform(*CRUISE_SPEED_RANGE_MPS),
            lon=route[0][0],
            lat=route[0][1],
            heading_deg=bearing_deg(route[0], route[1]),
            dwell_s=i * 4.0,  # stagger takeoffs
        )

    # -- faults ----------------------------------------------------------

    @staticmethod
    def _normalize(f: FaultSpec) -> FaultSpec:
        kind = FAULT_KIND_ALIASES.get(f.kind)
        if kind is None:
            raise ValueError(
                f"unknown fault kind {f.kind!r}; expected one of {sorted(FAULT_KIND_ALIASES)}"
            )
        return f if kind == f.kind else replace(f, kind=kind)

    @staticmethod
    def _key(f: FaultSpec) -> tuple[str, str, float, float]:
        return f.kind, f.track_id, round(f.start_s, 3), round(f.duration_s, 3)

    def register_faults(self, faults: list[FaultSpec], relative: bool = False) -> None:
        """Add fault events; `relative` rebases start_s onto the current sim time."""
        for f in faults:
            spec = self._normalize(f)
            if relative:
                spec = replace(spec, start_s=spec.start_s + self.sim_time_s)
            key = self._key(spec)
            if key in self._fault_keys:
                continue
            self._fault_keys.add(key)
            self._faults.append(spec)

    def _active_faults(self, track_id: str) -> list[FaultSpec]:
        return [
            f
            for f in self._faults
            if f.track_id == track_id and f.start_s <= self.sim_time_s < f.end_s
        ]

    # -- stepping --------------------------------------------------------

    def step(self, dt: float = SIM_DT_S) -> None:
        for ac in self.aircraft:
            active = self._active_faults(ac.track_id)
            # Latch the pre-move fix: a GPS loss freezes the *last reported*
            # position while the true position keeps evolving.
            self._update_gps_latch(ac, active)
            self._step_aircraft(ac, dt, active)
            ac.active_kinds = {f.kind for f in active}
        self.sim_time_s += dt

    def step_wallclock(self) -> None:
        """Catch the sim up to wall time in 1 s steps (idempotent per second)."""
        now = time.monotonic()
        steps = int((now - self._last_wall) / SIM_DT_S)
        if steps <= 0:
            return
        for _ in range(min(steps, 300)):
            self.step(SIM_DT_S)
        self._last_wall += steps * SIM_DT_S

    @staticmethod
    def _update_gps_latch(ac: _Aircraft, active: list[FaultSpec]) -> None:
        lost = any(f.kind == "gps_loss" for f in active)
        if lost and ac.frozen_fix is None:
            ac.frozen_fix = (ac.lon, ac.lat, ac.alt_m, ac.heading_deg, ac.speed_mps)
        elif not lost:
            ac.frozen_fix = None

    def _step_aircraft(self, ac: _Aircraft, dt: float, active: list[FaultSpec]) -> None:
        if ac.phase == "on_ground":
            ac.dwell_s -= dt
            if ac.dwell_s <= 0.0:
                ac.phase = "takeoff"
            return

        intrusion = next((f for f in active if f.kind == "intrusion"), None)
        deviation = next((f for f in active if f.kind == "deviation"), None)

        target = ac.route[ac.waypoint_idx]
        if intrusion is not None and ac.phase == "cruise":
            polygon = intrusion.polygon or DEFAULT_INTRUSION_POLYGON
            target = (
                sum(p[0] for p in polygon) / len(polygon),
                sum(p[1] for p in polygon) / len(polygon),
            )
        desired = bearing_deg((ac.lon, ac.lat), target)
        if deviation is not None and ac.phase == "cruise":
            desired = (desired + DEVIATION_HEADING_BIAS_DEG) % 360.0
        ac.heading_deg = _turn_toward(ac.heading_deg, desired, TURN_RATE_DEG_S * dt)

        if ac.phase == "takeoff":
            ac.alt_m += CLIMB_RATE_MPS * dt
            if ac.alt_m >= ac.cruise_alt_m:
                ac.alt_m = ac.cruise_alt_m
                ac.phase = "cruise"
        elif ac.phase == "cruise":
            ac.speed_mps = min(ac.cruise_speed_mps, ac.speed_mps + ACCEL_MPS2 * dt)
            ac.lon, ac.lat = _advance(ac.lon, ac.lat, ac.heading_deg, ac.speed_mps * dt)
            if intrusion is None and self._reached(ac, ac.route[ac.waypoint_idx]):
                if ac.waypoint_idx < len(ac.route) - 1:
                    ac.waypoint_idx += 1
                else:
                    ac.phase = "landing"
        elif ac.phase == "landing":
            ac.speed_mps = max(0.0, ac.speed_mps - ACCEL_MPS2 * dt)
            ac.alt_m -= DESCENT_RATE_MPS * dt
            if ac.alt_m <= 0.0:
                ac.alt_m = 0.0
                ac.speed_mps = 0.0
                ac.phase = "on_ground"
                ac.dwell_s = self._rng.uniform(8.0, 20.0)
                ac.route.reverse()  # shuttle back and forth forever
                ac.waypoint_idx = 1

    @staticmethod
    def _reached(ac: _Aircraft, waypoint: tuple[float, float]) -> bool:
        dist = distance_m((ac.lon, ac.lat), waypoint)
        if dist < ARRIVAL_RADIUS_M:
            return True
        # Closest-approach fallback: near the waypoint and already moving away
        # from it (a tight arrival radius could otherwise be orbited forever).
        bearing = bearing_deg((ac.lon, ac.lat), waypoint)
        return dist < 150.0 and math.cos(math.radians(bearing - ac.heading_deg)) < 0.0

    # -- output ----------------------------------------------------------

    def snapshot(self) -> list[Track]:
        ts = time.time()
        tracks: list[Track] = []
        for ac in self.aircraft:
            if ac.frozen_fix is not None:
                lon, lat, alt, hdg, spd = ac.frozen_fix
                status = "gps_loss"
            else:
                lon, lat, alt, hdg, spd = ac.lon, ac.lat, ac.alt_m, ac.heading_deg, ac.speed_mps
                if "intrusion" in ac.active_kinds:
                    status = "intrusion"
                elif "deviation" in ac.active_kinds:
                    status = "deviation"
                elif ac.phase == "cruise":
                    status = "nominal"
                else:
                    status = ac.phase
            tracks.append(
                Track(
                    track_id=ac.track_id,
                    lon=round(lon, 6),
                    lat=round(lat, 6),
                    altitude_m=round(alt, 1),
                    heading_deg=round(hdg % 360.0, 1),
                    speed_mps=round(spd, 1),
                    status=status,
                    ts=ts,
                )
            )
        return tracks


_default_simulator: Simulator | None = None


def get_default_simulator(count: int = DEFAULT_COUNT) -> Simulator:
    """Shared demo world behind the module-level API. `count` only applies at
    creation — the first caller wins, later callers get the existing world."""
    global _default_simulator
    if _default_simulator is None:
        _default_simulator = Simulator(count=count)
    return _default_simulator


def generate_tracks(count: int = DEFAULT_COUNT, faults: list[FaultSpec] | None = None) -> list[Track]:
    """Live snapshot of the shared demo world (used by GET /api/v1/airspace)."""
    sim = get_default_simulator(count)
    if faults:
        sim.register_faults(faults, relative=True)
    sim.step_wallclock()
    return sim.snapshot()


async def stream_tracks(
    count: int = DEFAULT_COUNT,
    interval_s: float = 1.0,
    faults: list[FaultSpec] | None = None,
    faults_relative: bool = True,
    simulator: Simulator | None = None,
) -> AsyncGenerator[list[Track], None]:
    """Yield a snapshot of all tracks every `interval_s` seconds (SSE source).

    Without an injected `simulator`, frames come from the shared demo world,
    so concurrent stream clients and /api/v1/airspace all see the same sky.
    Fault starts are relative to registration time unless faults_relative is
    False (absolute sim seconds, as scenario scripting will use).
    """
    sim = simulator or get_default_simulator(count)
    if faults:
        sim.register_faults(faults, relative=faults_relative)
    while True:
        sim.step_wallclock()
        yield sim.snapshot()
        await asyncio.sleep(interval_s)
