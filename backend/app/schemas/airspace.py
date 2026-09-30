"""Airspace status models — see API contract: GET /api/v1/airspace, GET /api/v1/tracks/stream."""

from pydantic import BaseModel, Field


class Track(BaseModel):
    track_id: str
    lon: float
    lat: float
    altitude_m: float
    heading_deg: float = 0.0
    speed_mps: float = 0.0
    status: str = Field(default="nominal", examples=["nominal"])
    ts: float | None = Field(
        default=None,
        description="Unix epoch seconds (UTC) of this position fix; set by the simulator.",
    )


class AirspaceResponse(BaseModel):
    area: str = "Hong Kong"
    active_restrictions: list[str] = Field(
        default_factory=list,
        description="Regulation / notice identifiers currently shaping the airspace.",
    )
    # TODO(phase-1/2): stub — real count once the RFZ GeoJSON layer is wired in.
    rfz_count: int = 286
    # TODO(phase-3): stub — real value once the HKO open-data weather feed lands.
    weather: str = Field(default="fine", examples=["fine", "typhoon_approaching"])
    active_tracks: list[Track] = []
