"""Store round-trip tests with a deterministic fake embedding function —
fast, no model download, exercises the real Chroma persistence + citation
metadata plumbing. Retrieval *quality* is covered by test_rag_smoke.py.
"""

import math
import re

import pytest

from app.rag.chunker import chunk_pages
from app.rag.store import RegulationStore, RegulationStoreNotReady


def fake_embed(texts: list[str]) -> list[list[float]]:
    """Bag-of-words hashing into 64 dims, L2-normalised. Lexical but
    deterministic — good enough to verify ranking wiring."""
    vectors = []
    for text in texts:
        v = [0.0] * 64
        for tok in re.findall(r"[a-z0-9]+|[一-鿿]", text.lower()):
            v[hash(tok) % 64] += 1.0
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        vectors.append([x / norm for x in v])
    return vectors


def _chunks():
    pages_a = [
        "No. AC-014\nDate: 31 July 2026\nCategory C Permission\n1. Requirements",
        "1.1 The maximum flight altitude is 300 ft above ground level.",
        "1.2 The minimum horizontal separation is 30 m.",
    ]
    pages_b = [
        "No. AC-010\nDate: 18 June 2026\nDrone Show Guidelines\n1. Background",
        "1.1 A drone show involves multiple SUA at night over Victoria Harbour.",
    ]
    return chunk_pages(pages_a, doc_id="AC-014", doc_title="Category C", source_file="a.pdf") + chunk_pages(
        pages_b, doc_id="AC-010", doc_title="Drone Show", source_file="b.pdf"
    )


@pytest.fixture()
def store(tmp_path):
    s = RegulationStore(tmp_path / "chroma", embedding_fn=fake_embed)
    assert s.ingest(_chunks()) == len(_chunks())
    return s


def test_query_returns_full_citation(store):
    hits = store.query("maximum altitude", k=2)
    assert hits and hits[0]["regulation_id"] == "AC-014"
    hit = hits[0]
    assert hit["title"] == "Category C"
    assert hit["section"].startswith("para. 1.1")
    assert hit["page_start"] >= 1 and hit["page_end"] >= hit["page_start"]
    assert "300 ft" in hit["excerpt"]
    assert 0.0 <= hit["score"] <= 1.0


def test_query_orders_by_relevance(store):
    hits = store.query("drone show night harbour", k=2)
    assert hits[0]["regulation_id"] == "AC-010"


def test_ingest_is_reproducible(tmp_path):
    s = RegulationStore(tmp_path / "chroma", embedding_fn=fake_embed)
    n1 = s.ingest(_chunks())
    n2 = s.ingest(_chunks())  # default reset -> rebuild, not duplicate
    assert n1 == n2 == s.count()


def test_keep_existing_upserts_without_duplicating(store):
    store.ingest(_chunks(), reset=False)
    assert store.count() == len(_chunks())


def test_not_ready_when_collection_missing(tmp_path):
    s = RegulationStore(tmp_path / "empty", embedding_fn=fake_embed)
    assert not s.is_ready()
    with pytest.raises(RegulationStoreNotReady, match="ingest_regulations"):
        s.query("anything")
