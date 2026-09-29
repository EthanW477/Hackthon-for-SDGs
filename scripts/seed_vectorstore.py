"""seed_vectorstore.py — load the CAD regulation PDFs into the vector store.

Phase 2 (step 2.1) implementation target:
  1. Read the 20 PDFs from data/regulations/ (AC-001~017 + 3 UCA docs).
  2. Split clause-by-clause; every chunk's metadata must carry its clause
     number (e.g. "AC-014 para. 3.2") so answers can cite it — this is one of
     the three anti-hallucination engineering rules (project-plan §7.0).
  3. Embed with the local open-source bge-m3 model and store in Chroma.

TODO(phase-2): implement the pipeline above, then wire app/rag/retrieve.py
to the populated store.
"""


def main() -> None:
    raise SystemExit(
        "TODO: vector store seeding not implemented yet — "
        "see the docstring and data/SOURCES.md"
    )


if __name__ == "__main__":
    main()
