"""Contract tests for GET /api/v1/regulations/search.

The RAG layer is monkeypatched — these tests pin the HTTP contract (shape,
validation, 503-before-ingest) without needing the vector store or model.
Retrieval quality lives in test_rag_smoke.py.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.rag.store import RegulationStoreNotReady

client = TestClient(app)

SAMPLE_HIT = {
    "regulation_id": "AC-014",
    "title": "丙類小型無人機操作許可及預設情境 #1",
    "section": "para. 7.2",
    "clauses": "7.2",
    "page_start": 7,
    "page_end": 8,
    "excerpt": "最高飛行高度 地面以上 300 呎",
    "score": 0.81,
}


def test_search_returns_citations(monkeypatch):
    monkeypatch.setattr("app.main.rag_query", lambda q, k: [SAMPLE_HIT] * min(k, 2))
    r = client.get("/api/v1/regulations/search", params={"q": "altitude limit", "k": 2})
    assert r.status_code == 200
    body = r.json()
    assert body["query"] == "altitude limit" and body["k"] == 2
    assert len(body["results"]) == 2
    hit = body["results"][0]
    assert hit["regulation_id"] == "AC-014"
    assert hit["section"] == "para. 7.2"
    assert hit["page_start"] == 7 and hit["page_end"] == 8
    assert "300 呎" in hit["excerpt"]


def test_search_503_before_ingest(monkeypatch):
    def raise_not_ready(q, k):
        raise RegulationStoreNotReady("collection 'cad_regulations' not found")

    monkeypatch.setattr("app.main.rag_query", raise_not_ready)
    r = client.get("/api/v1/regulations/search", params={"q": "altitude"})
    assert r.status_code == 503
    assert "not found" in r.json()["detail"]


@pytest.mark.parametrize("params", [{}, {"q": ""}, {"q": "x", "k": 0}, {"q": "x", "k": 21}])
def test_search_validation(params):
    r = client.get("/api/v1/regulations/search", params=params)
    assert r.status_code == 422
