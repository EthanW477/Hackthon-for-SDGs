# UTM Copilot — frontend

Next.js 16 + TypeScript + Tailwind + Cesium + shadcn/ui. See the repo-root
README for the full project intro and quickstart.

- `src/app/page.tsx` — main layout: 3D map left, chat panel right
- `src/components/MapView.tsx` — Cesium viewer centred on Hong Kong (22.3°N, 114.17°E); ion imagery when `NEXT_PUBLIC_CESIUM_ION_TOKEN` is set, OSM fallback otherwise
- `src/components/ChatPanel.tsx` — chat UI wired to `POST /api/v1/chat`
- `src/lib/api.ts` — backend API client (mirrors the API contract)

```bash
npm install   # also copies Cesium static assets to public/cesium (postinstall)
npm run dev   # http://localhost:43123
```

Env: see `.env.example`.
