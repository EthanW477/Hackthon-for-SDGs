"""Chroma-backed vector store for the CAD regulation library.

BAAI/bge-m3 embeddings (multilingual, so English queries hit the Chinese
circulars) stored in a persistent Chroma collection under data/chroma/
(git-ignored — rebuild with scripts/ingest_regulations.py).

The embedding model loads lazily on first use so importing app.main stays
fast; tests inject a lightweight `embedding_fn` instead of the 2 GB model.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Protocol

from app.rag.chunker import Chunk

DEFAULT_MODEL = "BAAI/bge-m3"
DEFAULT_COLLECTION = "cad_regulations"
DEFAULT_PERSIST_DIR = Path(__file__).resolve().parents[3] / "data" / "chroma"


class EmbeddingFn(Protocol):
    def __call__(self, texts: list[str]) -> list[list[float]]: ...


class RegulationStoreNotReady(RuntimeError):
    """Raised when the Chroma collection is missing or empty — the API turns
    this into a 503 telling the operator to run the ingest script."""


def _persist_dir(persist_dir: str | Path | None = None) -> Path:
    if persist_dir is not None:
        return Path(persist_dir)
    return Path(os.environ.get("RAG_CHROMA_DIR", DEFAULT_PERSIST_DIR))


def _default_embedding_fn(model_name: str) -> EmbeddingFn:
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(model_name, device="cpu")

    def encode(texts: list[str]) -> list[list[float]]:
        return model.encode(texts, normalize_embeddings=True).tolist()

    return encode


class RegulationStore:
    """Ingest and query the regulation chunk collection."""

    def __init__(
        self,
        persist_dir: str | Path | None = None,
        *,
        model_name: str | None = None,
        collection_name: str | None = None,
        embedding_fn: EmbeddingFn | None = None,
    ) -> None:
        self.persist_dir = _persist_dir(persist_dir)
        self.model_name = model_name or os.environ.get("RAG_MODEL_NAME", DEFAULT_MODEL)
        self.collection_name = collection_name or os.environ.get(
            "RAG_COLLECTION", DEFAULT_COLLECTION
        )
        self._embedding_fn = embedding_fn
        self._client = None

    # -- internals -----------------------------------------------------------

    @property
    def client(self):
        if self._client is None:
            import chromadb

            self.persist_dir.mkdir(parents=True, exist_ok=True)
            self._client = chromadb.PersistentClient(path=str(self.persist_dir))
        return self._client

    @property
    def embedding_fn(self) -> EmbeddingFn:
        if self._embedding_fn is None:
            self._embedding_fn = _default_embedding_fn(self.model_name)
        return self._embedding_fn

    def _collection(self, *, create: bool = False):
        # Cosine space + normalised embeddings => dot-product ranking.
        if create:
            return self.client.get_or_create_collection(
                name=self.collection_name, metadata={"hnsw:space": "cosine"}
            )
        try:
            return self.client.get_collection(name=self.collection_name)
        except Exception as exc:  # chromadb raises InvalidCollection/NotFound
            raise RegulationStoreNotReady(
                f"regulation collection {self.collection_name!r} not found in "
                f"{self.persist_dir} — run `python scripts/ingest_regulations.py`"
            ) from exc

    # -- ingest ---------------------------------------------------------------

    def reset(self) -> None:
        try:
            self.client.delete_collection(self.collection_name)
        except Exception:
            pass

    def ingest(
        self,
        chunks: list[Chunk],
        *,
        batch_size: int = 32,
        reset: bool = True,
        on_batch: Callable[[int, int], None] | None = None,
    ) -> int:
        """Embed chunks and upsert them. Reproducible: resets by default so a
        re-run yields exactly the same collection contents."""
        if reset:
            self.reset()
        collection = self._collection(create=True)
        ids, docs, metas = zip(*(c.record() for c in chunks)) if chunks else ((), (), ())
        total = len(ids)
        for start in range(0, total, batch_size):
            end = min(start + batch_size, total)
            embeddings = self.embedding_fn(list(docs[start:end]))
            collection.upsert(
                ids=list(ids[start:end]),
                documents=list(docs[start:end]),
                metadatas=[dict(m) for m in metas[start:end]],
                embeddings=embeddings,
            )
            if on_batch:
                on_batch(end, total)
        return total

    # -- query -----------------------------------------------------------------

    def count(self) -> int:
        return self._collection().count()

    def is_ready(self) -> bool:
        try:
            return self.count() > 0
        except RegulationStoreNotReady:
            return False

    def query(self, text: str, k: int = 5) -> list[dict]:
        """Top-k chunks with full citation metadata, best first."""
        collection = self._collection()
        if collection.count() == 0:
            raise RegulationStoreNotReady(
                f"regulation collection {self.collection_name!r} is empty — "
                "run `python scripts/ingest_regulations.py`"
            )
        [query_embedding] = self.embedding_fn([text])
        result = collection.query(
            query_embeddings=[query_embedding],
            n_results=k,
            include=["documents", "metadatas", "distances"],
        )
        hits: list[dict] = []
        for doc, meta, distance in zip(
            result["documents"][0], result["metadatas"][0], result["distances"][0]
        ):
            hits.append(
                {
                    "regulation_id": meta["doc_id"],
                    "title": meta["doc_title"],
                    "section": meta["section"],
                    "clauses": meta.get("clauses", ""),
                    "page_start": meta["page_start"],
                    "page_end": meta["page_end"],
                    "excerpt": doc,
                    # cosine distance -> similarity in [0, 1]
                    "score": round(1.0 - float(distance), 4),
                }
            )
        return hits
