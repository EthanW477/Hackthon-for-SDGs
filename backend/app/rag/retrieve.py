"""Regulation knowledge base — Phase-0 placeholder.

Phase 2 (step 2.1): ingest the 20 CAD regulation PDFs (AC-001~017 + 3 UCA
documents, see data/regulations/) clause-by-clause into a local Chroma store;
retrieval metadata must carry clause numbers so answers can cite them.
"""


def retrieve(topic: str, k: int = 5) -> list[dict]:
    """Return the top-k regulation excerpts for a topic. Stub: empty list."""
    return []
