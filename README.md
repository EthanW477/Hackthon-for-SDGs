# 低空通 · UTM Copilot

**The natural-language interaction layer for drone traffic management (UTM) — Hong Kong low-altitude economy.**

Built for **Hack4SDG 2026, Track 1: Green Transport & Smart Mobility**. Anyone can talk to a UTM system in plain language: ask why a flight plan was rejected (with regulation citations and fix suggestions), generate test scenarios from a sentence, and auto-produce reports and plain-language briefs. The LLM is the dispatcher; the rules engine and data do the real work.

The app: a 3D map of Hong Kong on the left, a chat panel on the right, a report panel below.

## Architecture

```
┌─────────────────────────────────────────────┐
│ frontend/  Next.js + TypeScript + Cesium     │
│ (3D map / chat panel / report panel)         │
├─────────────────────────────────────────────┤
│ backend/   FastAPI — AI layer: LLM tool      │
│ calling + RAG regulation library             │
├─────────────────────────────────────────────┤
│ backend/   rules engine (CAD rules as code)  │
│ + track simulator (simulated UTM base)       │
├─────────────────────────────────────────────┤
│ data/      HK open geo data + CAD regulation │
│ library (not in git — scripts/download_data) │
└─────────────────────────────────────────────┘
```

Anti-hallucination engineering discipline (from the project plan):
1. Rules engine first, AI second — every AI explanation must rest on a real check.
2. The LLM may only speak from tool-returned data; regulation citations must carry clause numbers.
3. LLM structured output must pass schema validation, with automatic retry.

## Quickstart

### Docker (everything at once)

```bash
docker compose up --build
# frontend → http://localhost:43123
# backend  → http://localhost:43124/docs
```

### Dev mode

```bash
# terminal 1 — backend (Python 3.11+)
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 43124

# terminal 2 — frontend (Node.js 20+)
cd frontend
npm install
npm run dev   # http://localhost:43123
```

### Data & tests

```bash
bash scripts/download_data.sh        # fetch datasets into data/ (see data/SOURCES.md)
python scripts/seed_vectorstore.py   # load the regulation library (Phase 2)
cd backend && pytest                 # backend tests
```

Optional env vars: `NEXT_PUBLIC_CESIUM_ION_TOKEN` (Cesium ion imagery; falls back to plain OSM tiles without it), `LLM_API_KEY` (Phase-2 AI layer; Phase-0 stubs run without it).

## Repo layout

| Path | Owner role (see dev-readme) | Contents |
|---|---|---|
| `frontend/` | A — frontend | Next.js + Cesium 3D map, chat panel, report panel |
| `backend/app/rules_engine/`, `backend/app/simulator/` | B — backend/data | CAD rules as pure functions, track simulator |
| `backend/app/ai/`, `backend/app/rag/` | C — AI integration | LLM tools, prompts, regulation RAG |
| `data/` | B | Datasets (git-ignored), `SOURCES.md` provenance |
| `scripts/` | B/C | Data download + vector-store seeding |
| `docs/` | D — PM/docs | Pitch deck, interim report, demo script |

## Plan docs

The full plan docs live in the team's project store (not in this repo):

- `docs/dev-readme.md` — division of labour (roles A–D), API contract, file skeleton
- `docs/project-plan.md` — background, scope, phased implementation steps (§4.7 API contract, §4.8 skeleton)

Key dates: interim report 10/4 → pitch deck 10/18 → Final Pitch 10/24 (CityU).
