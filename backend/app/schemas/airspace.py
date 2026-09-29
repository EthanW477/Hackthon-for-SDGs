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


class AirspaceResponse(BaseModel):
    area: str = "Hong Kong"
    active_restrictions: list[str] = Field(
        default_factory=list,
        description="Regulation / notice identifiers currently shaping the airspace.",
    )
    rfz_count: int = 286
    active_tracks: list[Track] = []
