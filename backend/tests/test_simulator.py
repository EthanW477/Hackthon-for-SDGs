"""Simulator v1 tests — corridor containment, route lifecycle, fault hooks,
and the 1 Hz SSE frame source (project-plan §4.3 / step 1.4)."""

import asyncio

import pytest

from app.simulator import FaultSpec, Simulator, parse_fault_specs, stream_tracks
from app.simulator.tracks import (
    CORRIDOR_MAX_LAT,
    CORRIDOR_MAX_LON,
    CORRIDOR_MIN_LAT,
    CORRIDOR_MIN_LON,
    DEFAULT_INTRUSION_POLYGON,
    SIM_DT_S,
    distance_m,
    point_in_polygon,
)


def test_tracks_stay_inside_corridor_nominal():
    sim = Simulator(count=10, seed=42)
    for _ in range(300):
        sim.step()
        for t in sim.snapshot():
            assert CORRIDOR_MIN_LON <= t.lon <= CORRIDOR_MAX_LON, t
            assert CORRIDOR_MIN_LAT <= t.lat <= CORRIDOR_MAX_LAT, t
            # 300 ft AC-014 ceiling ≈ 91 m; nominal traffic must stay under it
            assert 0.0 <= t.altitude_m <= 91.0, t


def test_aircraft_complete_routes_and_respawn():
    sim = Simulator(count=3, seed=7)
    phases_seen = {ac.track_id: set() for ac in sim.aircraft}
    for _ in range(1000):
        sim.step()
        for ac in sim.aircraft:
            phases_seen[ac.track_id].add(ac.phase)
    for track_id, phases in phases_seen.items():
        assert {"on_ground", "takeoff", "cruise", "landing"} <= phases, track_id
    # Traffic never runs dry: the world still yields a full snapshot.
    assert len(sim.snapshot()) == 3


def test_gps_loss_freezes_then_jumps():
    fault = FaultSpec(kind="gps_loss", track_id="SIM-001", start_s=30.0, duration_s=10.0)
    sim = Simulator(count=2, seed=3, faults=[fault])
    fixes = {}
    for t in range(45):
        sim.step()
        snap = {tr.track_id: tr for tr in sim.snapshot()}
        if t == 29:  # last fix before the fault window
            fixes["before"] = (snap["SIM-001"].lon, snap["SIM-001"].lat)
        elif t == 34:  # mid-fault
            fixes["during"] = (snap["SIM-001"].lon, snap["SIM-001"].lat, snap["SIM-001"].status)
        elif t == 41:  # after recovery
            fixes["after"] = (snap["SIM-001"].lon, snap["SIM-001"].lat, snap["SIM-001"].status)
    assert fixes["during"][:2] == fixes["before"], "reported position must freeze"
    assert fixes["during"][2] == "gps_loss"
    assert fixes["after"][:2] != fixes["before"], "recovery must jump to the true position"
    assert fixes["after"][2] != "gps_loss"
    # The unaffected neighbour keeps moving normally throughout.
    assert snap["SIM-002"].status in {"nominal", "takeoff", "cruise", "landing", "on_ground"}


def test_deviation_drifts_off_route():
    fault = FaultSpec(kind="deviation", track_id="SIM-001", start_s=60.0, duration_s=30.0)
    dev = Simulator(count=1, seed=11, faults=[fault])
    ref = Simulator(count=1, seed=11)
    separation_m = 0.0
    status_mid_fault = None
    for t in range(120):
        dev.step()
        ref.step()
        if t == 85:  # 25 s into the fault
            a, b = dev.snapshot()[0], ref.snapshot()[0]
            separation_m = distance_m((a.lon, a.lat), (b.lon, b.lat))
            status_mid_fault = a.status
    assert status_mid_fault == "deviation"
    assert separation_m > 50.0, f"expected visible drift, got {separation_m:.1f} m"


def test_intrusion_enters_polygon():
    fault = FaultSpec(kind="intrusion", track_id="SIM-001", start_s=40.0, duration_s=260.0)
    sim = Simulator(count=1, seed=5, faults=[fault])
    entered = False
    statuses = set()
    for _ in range(300):
        sim.step()
        ac = sim.aircraft[0]
        statuses.add(sim.snapshot()[0].status)
        if point_in_polygon(ac.lon, ac.lat, DEFAULT_INTRUSION_POLYGON):
            entered = True
    assert entered, "intrusion fault must steer the aircraft into the polygon"
    assert "intrusion" in statuses


def test_stream_yields_1hz_frames_with_timestamps():
    class _FastForwardSim(Simulator):
        def step_wallclock(self):  # decouple the test from wall time
            self.step(SIM_DT_S)

    async def collect():
        frames = []
        gen = stream_tracks(interval_s=0, simulator=_FastForwardSim(count=5, seed=7))
        async for frame in gen:
            frames.append(frame)
            if len(frames) >= 3:
                break
        return frames

    frames = asyncio.run(collect())
    assert [len(f) for f in frames] == [5, 5, 5]
    assert all(t.ts is not None for frame in frames for t in frame)
    # SIM-001 has no takeoff dwell, so it is already climbing: sim time
    # advances one second per frame.
    assert frames[0][0].altitude_m < frames[-1][0].altitude_m


def test_parse_fault_specs():
    specs = parse_fault_specs(
        "gps_loss:SIM-002@30+15"
        "|off_course:SIM-004@60+20"
        "|intrusion:SIM-005@10+5:114.198,22.397;114.204,22.403;114.198,22.403"
    )
    assert [s.kind for s in specs] == ["gps_loss", "deviation", "intrusion"]
    assert specs[0].track_id == "SIM-002"
    assert specs[0].start_s == 30.0
    assert specs[0].end_s == 45.0
    assert specs[2].polygon == ((114.198, 22.397), (114.204, 22.403), (114.198, 22.403))
    with pytest.raises(ValueError):
        parse_fault_specs("bogus:SIM-001@1+1")
    with pytest.raises(ValueError):
        parse_fault_specs("gps_loss:SIM-001")


def test_count_clamped_to_ten():
    assert len(Simulator(count=50).aircraft) == 10
    assert len(Simulator(count=0).aircraft) == 1
