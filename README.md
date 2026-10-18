# 低空通 · UTM Copilot

**The natural-language interaction layer for drone traffic management (UTM) — Hong Kong low-altitude economy.**

Built for **Hack4SDG 2026, Track 1: Green Transport & Smart Mobility**. Anyone can talk to a UTM system in plain language: ask why a flight plan was rejected (with regulation citations and fix suggestions), generate test scenarios from a sentence, and auto-produce reports and plain-language briefs. The LLM is the dispatcher; the rules engine and data do the real work.

The app: a 3D map of Hong Kong on the left; the right panel has two tabs — the chat assistant and the Scenario Lab (Phase 3): one plain-language sentence → test-scenario JSON + checklist → one-click simulator run → structured test report → trilingual (中/EN/粵語) briefs for CAD, LegCo, and community audiences.

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
bash scripts/download_data.sh          # fetch datasets into data/ (see data/SOURCES.md)
python scripts/ingest_regulations.py   # build the regulation vector library into data/chroma/
cd backend && pytest                   # backend tests
```

The regulation library (20 CAD circulars, clause-level chunks, BAAI/bge-m3
embeddings + Chroma) powers `GET /api/v1/regulations/search?q=...&k=5` and
the chat layer's citations. First run downloads the ~2 GB embedding model;
the store itself is git-ignored and rebuilt by the ingest script.

### Phase 3 API (scenarios · reports · briefs)

| Endpoint | Purpose |
|---|---|
| `POST /api/v1/scenarios` | NL description → scenario JSON + checklist (LLM → schema validation → auto-retry; disclosed heuristic fallback) |
| `GET /api/v1/scenarios/{id}` | Fetch a generated scenario |
| `POST /api/v1/scenarios/{id}/run` | Execute through the simulator → structured report (pass rate, violations with clause refs, timeline) |
| `GET /api/v1/scenarios/{id}/report?format=json\|markdown` | Export the latest report |
| `POST /api/v1/scenarios/{id}/brief` | Trilingual (zh/en/yue) brief per audience: `cad_technical` / `legco_policy` / `community` |

Checklist verdicts are computed by deterministic code probes against the
simulated track picture — never by the LLM. Anything the simulator cannot
observe is honestly marked `pending`. API keys are scrubbed from every
response (`app/scenarios/redact.py`).

Optional env vars: `NEXT_PUBLIC_CESIUM_ION_TOKEN` (Cesium ion imagery; falls back to plain OSM tiles without it), `LLM_API_KEY` (Phase-2 AI layer; Phase-0 stubs run without it).

## Production deployment (Vercel + Railway)

Frontend on Vercel, backend on Railway (Docker). The regulation vector
library is **not** committed — the container self-heals it on first boot
(see below).

### Backend → Railway

1. New Railway service from this repo; set **Root Directory** to `backend/`.
   `backend/railway.toml` selects the Dockerfile build, healthchecks
   `/api/v1/health`, and restarts on failure. Railway injects `PORT`; the
   image default (43124) keeps docker-compose working.
2. Environment variables: `LLM_PROVIDER` plus the matching key
   (`KIMI_API_KEY` / `DEEPSEEK_API_KEY`, … — see `backend/.env.example`).
   Without them the Phase-0 stubs still run.
3. Memory: the BAAI/bge-m3 embedding model needs **~2 GB RAM** (pre-downloaded
   into the image at build time via `HF_HOME=/opt/hf`) — pick an instance
   with headroom (≥ 4 GB recommended; first-boot ingestion is the peak).
4. Regulation library — three options:
   - **Auto-ingest (default):** set `REGULATIONS_DIR` to a directory of the
     CAD PDFs (e.g. a Railway volume mounted at `/app/data` with PDFs in
     `/app/data/regulations`). When `data/chroma` is empty, startup ingests
     in a background thread; `/api/v1/regulations/search` returns 503 until
     done, everything else works immediately.
   - **Bake PDFs into the image:** copy the PDFs into
     `backend/data/regulations/` and uncomment the marked lines in
     `backend/Dockerfile` (optionally ingesting at build time instead).
   - **Pre-built store:** mount a volume at `/app/data` containing a
     `chroma/` collection built by `scripts/ingest_regulations.py`.

### Frontend → Vercel

1. Import the repo in Vercel; set **Root Directory** to `frontend/` (Next.js
   auto-detected; `postinstall` copies the Cesium static assets into
   `public/cesium`).
2. Set `NEXT_PUBLIC_API_URL` to the Railway backend URL
   (`https://<service>.up.railway.app`). Optional:
   `NEXT_PUBLIC_CESIUM_ION_TOKEN` (OSM fallback without it).
3. No localhost is hardcoded: browser calls go to `NEXT_PUBLIC_API_URL`, and
   the same-origin `/api/*` rewrite in `next.config.ts` is only emitted in
   development.

## Demo VM self-healing

`scripts/start-demo.sh` idempotently (re)starts the demo on this VM in tmux
— backend (`uvicorn :43124`), frontend (`next dev :43123`), and a
cloudflared quick tunnel (session `utm-tunnel-fe`). Healthy sessions are
skipped; dead or missing ones are restarted. Re-run it any time:

```bash
bash scripts/start-demo.sh
```

To survive VM reboots, add a cron `@reboot` entry (`crontab -e`):

```cron
@reboot sleep 30 && /workspace/scripts/start-demo.sh >> /tmp/start-demo-cron.log 2>&1
```

(Adjust the repo path if the checkout moves. The script carries no keys or
tunnel domains — the ephemeral URL is read from `/tmp/tunnel-fe.log`.)

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
