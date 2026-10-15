"""seed_vectorstore.py — kept for muscle memory; delegates to the real
ingest pipeline in scripts/ingest_regulations.py (phase-2, step 2.1)."""

from pathlib import Path
import runpy
import sys

if __name__ == "__main__":
    script = Path(__file__).with_name("ingest_regulations.py")
    sys.argv = [str(script), *sys.argv[1:]]
    runpy.run_path(str(script), run_name="__main__")
