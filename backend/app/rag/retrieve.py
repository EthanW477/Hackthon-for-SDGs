"""Regulation retrieval — the citation source for LLM answers (step 2.1).

`query(text, k)` returns top-k regulation chunks, each carrying a complete
citation: circular number (AC-014…), title, clause/section label, page span,
and the verbatim excerpt. This is what the chat layer must quote when it
cites a rule (dev-readme §7: citations must carry clause numbers).
"""

from __future__ import annotations

from functools import lru_cache

from app.rag.store import RegulationStore, RegulationStoreNotReady

__all__ = ["RegulationStoreNotReady", "query", "retrieve", "get_store"]


@lru_cache(maxsize=1)
def get_store() -> RegulationStore:
    """Process-wide store; the embedding model loads on first query."""
    return RegulationStore()


def query(text: str, k: int = 5, *, store: RegulationStore | None = None) -> list[dict]:
    """Top-k regulation excerpts for a natural-language question.

    Each hit: {regulation_id, title, section, page_start, page_end, excerpt,
    score}. Raises RegulationStoreNotReady when the library is not ingested.
    """
    return (store or get_store()).query(text, k)


def retrieve(topic: str, k: int = 5) -> list[dict]:
    """Backward-compatible Phase-0 signature; delegates to query(). Returns
    [] instead of raising when the store is not seeded yet."""
    try:
        return query(topic, k)
    except RegulationStoreNotReady:
        return []
