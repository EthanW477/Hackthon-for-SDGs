"""ingest_regulations.py — build the CAD regulation vector library (step 2.1).

Pipeline: pypdf text extraction -> clause-aware chunking (~500 tokens with
overlap; metadata keeps circular no., title, clause, page span) -> BAAI/bge-m3
embeddings (local, multilingual so English queries hit the Chinese circulars)
-> persistent Chroma collection at data/chroma/ (git-ignored, do not commit).

Usage (from repo root):
    python scripts/ingest_regulations.py                      # data/regulations -> data/chroma
    python scripts/ingest_regulations.py --source-dir /path/to/pdfs
    python scripts/ingest_regulations.py --keep-existing      # upsert without reset

PDFs come from scripts/download_data.sh (see data/SOURCES.md); the project
store also keeps verified copies under internal/datasets/regulations/.
Re-running is reproducible: the collection is reset and rebuilt from scratch
unless --keep-existing is given.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.rag.chunker import DEFAULT_MAX_TOKENS, DEFAULT_OVERLAP_TOKENS, chunk_pdf
from app.rag.store import DEFAULT_COLLECTION, DEFAULT_MODEL, RegulationStore


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--source-dir", type=Path, default=REPO_ROOT / "data" / "regulations",
                   help="directory of CAD regulation PDFs (default: data/regulations)")
    p.add_argument("--chroma-dir", type=Path, default=None,
                   help="Chroma persist dir (default: data/chroma or $RAG_CHROMA_DIR)")
    p.add_argument("--model", default=DEFAULT_MODEL, help="embedding model (default: BAAI/bge-m3)")
    p.add_argument("--collection", default=DEFAULT_COLLECTION)
    p.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    p.add_argument("--overlap-tokens", type=int, default=DEFAULT_OVERLAP_TOKENS)
    p.add_argument("--batch-size", type=int, default=32)
    p.add_argument("--keep-existing", action="store_true",
                   help="upsert into the existing collection instead of rebuilding it")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    pdfs = sorted(args.source_dir.glob("*.pdf"))
    if not pdfs:
        raise SystemExit(
            f"no PDFs in {args.source_dir} — run `bash scripts/download_data.sh` first"
        )

    print(f"Loading tokenizer for {args.model} …")
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(args.model)

    def count_tokens(text: str) -> int:
        return len(tokenizer.encode(text, add_special_tokens=False))

    print(f"Chunking {len(pdfs)} PDFs from {args.source_dir} …")
    chunks = []
    for pdf in pdfs:
        doc_chunks = chunk_pdf(
            pdf,
            max_tokens=args.max_tokens,
            overlap_tokens=args.overlap_tokens,
            token_counter=count_tokens,
        )
        if not doc_chunks:
            print(f"  ! {pdf.name}: no text extracted — skipped")
            continue
        first = doc_chunks[0]
        print(f"  {first.doc_id:12s} {len(doc_chunks):3d} chunks  {first.doc_title}")
        chunks.extend(doc_chunks)
    if not chunks:
        raise SystemExit("no chunks produced — check the source PDFs")

    print(f"Embedding {len(chunks)} chunks with {args.model} (CPU) …")
    store = RegulationStore(
        args.chroma_dir, model_name=args.model, collection_name=args.collection
    )
    started = time.time()

    def progress(done: int, total: int) -> None:
        rate = done / max(time.time() - started, 1e-9)
        print(f"\r  {done}/{total} chunks ({rate:.1f}/s)", end="", flush=True)

    total = store.ingest(
        chunks,
        batch_size=args.batch_size,
        reset=not args.keep_existing,
        on_batch=progress,
    )
    print(f"\nDone: {total} chunks in collection {args.collection!r} at {store.persist_dir}")


if __name__ == "__main__":
    main()
