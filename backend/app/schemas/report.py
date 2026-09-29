"""Report / brief models — see API contract: POST /api/v1/reports."""

from typing import Literal

from pydantic import BaseModel, Field


class ReportRequest(BaseModel):
    audience: Literal["cad_technical", "legco_policy", "community"] = Field(
        ...,
        description="cad_technical: CAD technical summary; legco_policy: policy brief; "
        "community: trilingual plain-language note.",
    )
    range: str = Field(..., examples=["2026-W42"], description="ISO week or date range.")


class ReportResponse(BaseModel):
    audience: str
    range: str
    markdown: str
