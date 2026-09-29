"""Track simulator stub — Phase-0 mock traffic over Sha Tin / Science Park.

Phase 1 (step 1.4) replaces the circular toy motion with a real multi-track
time-series generator (speed/altitude/heading per aircraft) plus fault
injection (off-course, GPS loss, RFZ intrusion) driven by scenario JSON.
"""

import asyncio
import math
from collections.abc import AsyncGenerator

from app.schemas.airspace import Track

# Demo box: Sha Tin town centre -> Hong Kong Science Park.
CENTER_LON = 114.200
CENTER_LAT = 22.390


def generate_tracks(count: int = 5, tick: int = 0) -> list[Track]:
    """Deterministic circular tracks so SSE output is reproducible in tests."""
    tracks: list[Track] = []
    for i in range(count):
        angle = (tick * 0.05) + (i * 2 * math.pi / count)
        tracks.append(
            Track(
                track_id=f"SIM-{i + 1:03d}",
                lon=CENTER_LON + 0.02 * math.cos(angle),
                lat=CENTER_LAT + 0.015 * math.sin(angle),
                altitude_m=60.0 + 5.0 * i,
                heading_deg=(math.degrees(angle) + 90.0) % 360.0,
                speed_mps=12.0,
            )
        )
    return tracks


async def stream_tracks(count: int = 5, interval_s: float = 1.0) -> AsyncGenerator[list[Track], None]:
    """Yield a snapshot of simulated tracks every `interval_s` seconds (SSE source)."""
    tick = 0
    while True:
        yield generate_tracks(count=count, tick=tick)
        tick += 1
        await asyncio.sleep(interval_s)
