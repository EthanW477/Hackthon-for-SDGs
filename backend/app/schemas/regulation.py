"""Regulation search models — GET /api/v1/regulations/search."""

from pydantic import BaseModel, Field


class RegulationExcerpt(BaseModel):
    """One retrieved chunk with a complete citation (dev-readme §7 rule 2:
    every regulation citation must carry its clause number)."""

    regulation_id: str = Field(..., examples=["AC-014"])
    title: str = Field(..., examples=["丙類小型無人機操作許可及預設情境 #1"])
    section: str = Field(..., examples=["para. 7.2"], description="Clause label of the chunk start, or 'p. N' for unnumbered text")
    clauses: str = Field("", examples=["7.1,7.2"], description="All clause numbers covered by the chunk")
    page_start: int = Field(..., examples=[7])
    page_end: int = Field(..., examples=[8])
    excerpt: str = Field(..., description="Verbatim chunk text — quote this when citing")
    score: float = Field(..., ge=0.0, le=1.0, description="cosine similarity")


class RegulationSearchResponse(BaseModel):
    query: str
    k: int
    results: list[RegulationExcerpt]
