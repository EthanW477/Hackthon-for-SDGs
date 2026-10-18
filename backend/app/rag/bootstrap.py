"""Self-healing regulation library: auto-ingest when the store is empty.

Two entry points share one ingest path:

- `maybe_auto_ingest()` — called from the FastAPI lifespan. When the Chroma
  collection is missing/empty and `REGULATIONS_DIR` points at a directory of
  PDFs, ingestion runs in a daemon thread so uvicorn serves immediately
  (health checks pass; regulation search keeps returning 503 until ready).
- `python -m app.rag.bootstrap` — synchronous, for optional ingestion at
  image build time (see backend/Dockerfile).

No-op unless REGULATIONS_DIR is set, so local dev, tests, and containers
without PDFs are unaffected.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path

from app.rag.store import RegulationStore

logger = logging.getLogger("utm.rag.bootstrap")


def regulations_dir() -> Path | None:
    """REGULATIONS_DIR as an existing directory, else None."""
    raw = os.environ.get("REGULATIONS_DIR", "").strip()
    if not raw:
        return None
    path = Path(raw)
    if not path.is_dir():
        logger.warning("REGULATIONS_DIR=%s is not a directory — auto-ingest disabled", raw)
        return None
    return path


def _is_ready(store: RegulationStore) -> bool:
    try:
        return store.is_ready()
    except Exception:  # corrupt dir, lock contention, … — treat as not ready
        logger.exception("regulation store readiness check failed")
        return False


def ingest_pdf_dir(pdf_dir: Path, *, store: RegulationStore | None = None) -> int:
    """Chunk and embed every PDF in `pdf_dir` into the regulation store."""
    from transformers import AutoTokenizer

    from app.rag.chunker import chunk_pdf

    store = store or RegulationStore()
    pdfs = sorted(pdf_dir.glob("*.pdf"))
    if not pdfs:
        raise RuntimeError(f"no PDFs in {pdf_dir}")

    tokenizer = AutoTokenizer.from_pretrained(store.model_name)

    def count_tokens(text: str) -> int:
        return len(tokenizer.encode(text, add_special_tokens=False))

    chunks = []
    for pdf in pdfs:
        doc_chunks = chunk_pdf(pdf, token_counter=count_tokens)
        if not doc_chunks:
            logger.warning("%s: no text extracted — skipped", pdf.name)
            continue
        chunks.extend(doc_chunks)
        logger.info("%s -> %d chunks", pdf.name, len(doc_chunks))
    if not chunks:
        raise RuntimeError(f"no chunks produced from {pdf_dir}")

    started = time.time()
    total = store.ingest(chunks)
    logger.info(
        "ingested %d chunks from %d PDFs into %s in %.1fs",
        total,
        len(pdfs),
        store.persist_dir,
        time.time() - started,
    )
    return total


def maybe_auto_ingest() -> bool:
    """Spawn a background ingest when the store is empty. Returns True if started."""
    pdf_dir = regulations_dir()
    if pdf_dir is None:
        return False
    # Share the process-wide store (app.rag.retrieve.get_store) so the ingest
    # thread and query path use one Chroma client. is_ready() forces client
    # initialisation here, before the thread starts — no lazy-init race.
    from app.rag.retrieve import get_store

    store = get_store()
    if _is_ready(store):
        logger.info(
            "regulation store already ingested (%s) — skipping auto-ingest",
            store.persist_dir,
        )
        return False

    def _run() -> None:
        try:
            ingest_pdf_dir(pdf_dir, store=store)
        except Exception:
            logger.exception("regulation auto-ingest failed — search stays 503")

    logger.info(
        "regulation store empty — auto-ingesting PDFs from %s in the background",
        pdf_dir,
    )
    threading.Thread(target=_run, name="rag-auto-ingest", daemon=True).start()
    return True


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    pdf_dir = regulations_dir()
    if pdf_dir is None:
        raise SystemExit("set REGULATIONS_DIR to a directory of regulation PDFs")
    total = ingest_pdf_dir(pdf_dir)
    print(f"done: {total} chunks")


if __name__ == "__main__":
    main()
