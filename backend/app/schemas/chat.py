"""Chat endpoint models — see API contract: POST /api/v1/chat."""

from typing import Any, Literal

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., examples=["Why was my route from Sha Tin to Science Park rejected?"])
    route: dict[str, Any] | None = Field(
        default=None,
        description="Optional GeoJSON LineString of the route being discussed.",
    )


class MapAnnotation(BaseModel):
    kind: Literal["rejected_route", "suggested_route", "rfz_highlight", "track_marker"]
    geojson: dict[str, Any]
    label: str | None = None
    color: str | None = Field(default=None, examples=["#ef4444"])


class Citation(BaseModel):
    regulation_id: str = Field(..., examples=["AC-014"])
    section: str | None = Field(default=None, examples=["para. 3.2"])
    excerpt: str | None = None


class ChatResponse(BaseModel):
    reply: str
    map_annotations: list[MapAnnotation] = []
    citations: list[Citation] = []
