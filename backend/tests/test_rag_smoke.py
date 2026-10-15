"""Retrieval-quality smoke tests against the real ingested library.

These need the bge-m3 model and the populated Chroma store at data/chroma/
(built by scripts/ingest_regulations.py — git-ignored, not available in CI).
They auto-skip when the store is absent; run the ingest script, then
`pytest tests/test_rag_smoke.py`, to exercise them locally.
"""

import re

import pytest

from app.rag.store import DEFAULT_PERSIST_DIR, RegulationStore

pytestmark = pytest.mark.skipif(
    not (DEFAULT_PERSIST_DIR / "chroma.sqlite3").exists(),
    reason="regulation store not ingested — run scripts/ingest_regulations.py",
)


@pytest.fixture(scope="module")
def store() -> RegulationStore:
    return RegulationStore()


def test_store_is_populated(store):
    assert store.count() > 0


def test_restricted_flying_zone_hits_rfz_clauses(store):
    hits = store.query("restricted flying zone", k=5)
    assert hits, "no hits at all"
    rfz_hits = [
        h for h in hits if re.search(r"限制飛行區|restricted flying zone", h["excerpt"], re.I)
    ]
    assert rfz_hits, f"no RFZ clause in top-5: {[h['regulation_id'] for h in hits]}"
    for h in rfz_hits:
        assert h["section"] and h["page_start"] >= 1


def test_altitude_query_hits_ac014_300ft_limit(store):
    """'altitude' must surface AC-014's 300 ft ceiling — the clause the rules
    engine enforces (rules_engine altitude_limit cites AC-014)."""
    hits = store.query("maximum flight altitude", k=10)
    ac014 = [h for h in hits if h["regulation_id"] == "AC-014" and "300 呎" in h["excerpt"]]
    assert ac014, f"AC-014 300-ft clause not in top-10: {[h['regulation_id'] for h in hits]}"


def test_cross_lingual_english_query_hits_chinese_circular(store):
    """Most circulars are Chinese-only; bge-m3 must retrieve them from an
    English query — otherwise the library is half-blind to English users."""
    hits = store.query("night operation permission", k=10)
    assert any(h["regulation_id"] == "AC-003" for h in hits), (
        f"AC-003 (night operations, zh) not in top-10: {[h['regulation_id'] for h in hits]}"
    )


def test_citations_are_complete(store):
    for h in store.query("insurance", k=3):
        assert h["regulation_id"]
        assert h["title"]
        assert h["section"]
        assert h["page_start"] >= 1 and h["page_end"] >= h["page_start"]
        assert h["excerpt"].strip()
