#!/usr/bin/env bash
# start-demo.sh — idempotent demo starter/self-healer for this VM.
#
# Manages three tmux sessions:
#   utm-backend    FastAPI via uvicorn on :43124
#   utm-frontend   Next.js dev server on :43123
#   utm-tunnel-fe  cloudflared quick tunnel -> http://localhost:43123
#
# Safe to re-run any time: sessions that are alive AND healthy are skipped;
# dead or missing ones are (re)started. Contains no secrets — LLM keys live
# in backend/.env (git-ignored) and the ephemeral tunnel URL is only ever
# read from the cloudflared log at runtime.
#
# Boot persistence: install the cron @reboot line documented in the README
# ("Demo VM self-healing" section).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$REPO_ROOT/backend"
FRONTEND_DIR="$REPO_ROOT/frontend"
BACKEND_PORT=43124
FRONTEND_PORT=43123
CLOUDFLARED="${CLOUDFLARED_BIN:-$HOME/bin/cloudflared}"
TMUX_BIN="${TMUX_BIN:-tmux}"
BACKEND_LOG=/tmp/utm-backend.log
FRONTEND_LOG=/tmp/utm-frontend.log
TUNNEL_LOG=/tmp/tunnel-fe.log

# cron @reboot hands us a minimal PATH — make sure node/npm (nvm) are reachable.
if ! command -v npm >/dev/null 2>&1; then
  for d in "$HOME/.nvm/versions/node/current/bin" "$HOME"/.nvm/versions/node/*/bin; do
    if [ -x "$d/npm" ]; then PATH="$d:$PATH"; fi
  done
  export PATH
fi

log() { printf '[start-demo] %s\n' "$*"; }
die() { log "ERROR: $*"; exit 1; }

session_exists() { "$TMUX_BIN" has-session -t "=$1" 2>/dev/null; }
kill_session() { "$TMUX_BIN" kill-session -t "$1" 2>/dev/null || true; }

backend_healthy() { curl -fsS --max-time 3 "http://127.0.0.1:$BACKEND_PORT/api/v1/health" >/dev/null 2>&1; }
frontend_healthy() { curl -fsS -o /dev/null --max-time 5 "http://127.0.0.1:$FRONTEND_PORT/" 2>/dev/null; }
tunnel_running() { pgrep -f "cloudflared tunnel --url" >/dev/null 2>&1; }
# Latest URL in the log wins — earlier entries may belong to a dead registration.
tunnel_url() { grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$TUNNEL_LOG" 2>/dev/null | tail -1; }

# A quick tunnel can go zombie: the cloudflared process stays alive but the
# server-side registration is gone ("Unauthorized: Tunnel not found" in an
# endless retry loop) and the public URL is dead. Only a restart (new URL)
# recovers from that, so treat a recent error tail with no successful
# registration as unhealthy.
tunnel_healthy() {
  session_exists utm-tunnel-fe || return 1
  tunnel_running || return 1
  [ -s "$TUNNEL_LOG" ] || return 1
  local recent
  recent="$(tail -n 20 "$TUNNEL_LOG" 2>/dev/null)"
  if grep -q "Register tunnel error" <<<"$recent" && ! grep -q "Registered tunnel connection" <<<"$recent"; then
    return 1
  fi
  return 0
}

# wait_for <seconds> <description> <check-command...>
wait_for() {
  local secs="$1" desc="$2"
  shift 2
  for _ in $(seq "$secs"); do
    if "$@" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  log "WARNING: $desc did not come up within ${secs}s"
  return 1
}

ensure_backend() {
  if session_exists utm-backend && backend_healthy; then
    log "utm-backend: already running and healthy — skipping"
    return 0
  fi
  if session_exists utm-backend; then
    log "utm-backend: session exists but :$BACKEND_PORT is not answering — restarting"
    kill_session utm-backend
  else
    log "utm-backend: starting (uvicorn :$BACKEND_PORT)"
  fi
  "$TMUX_BIN" new-session -d -s utm-backend -c "$BACKEND_DIR" \
    "python3 -m uvicorn app.main:app --host 0.0.0.0 --port $BACKEND_PORT 2>&1 | tee $BACKEND_LOG"
  wait_for 30 "backend :$BACKEND_PORT" \
    curl -fsS --max-time 2 "http://127.0.0.1:$BACKEND_PORT/api/v1/health"
}

ensure_frontend() {
  if session_exists utm-frontend && frontend_healthy; then
    log "utm-frontend: already running and healthy — skipping"
    return 0
  fi
  if session_exists utm-frontend; then
    log "utm-frontend: session exists but :$FRONTEND_PORT is not answering — restarting"
    kill_session utm-frontend
  else
    log "utm-frontend: starting (next dev :$FRONTEND_PORT)"
  fi
  command -v npm >/dev/null 2>&1 || die "npm not found (checked nvm under \$HOME/.nvm)"
  "$TMUX_BIN" new-session -d -s utm-frontend -c "$FRONTEND_DIR" \
    "npm run dev 2>&1 | tee $FRONTEND_LOG"
  wait_for 90 "frontend :$FRONTEND_PORT" \
    curl -fsS -o /dev/null --max-time 3 "http://127.0.0.1:$FRONTEND_PORT/"
}

ensure_tunnel() {
  if tunnel_healthy; then
    log "utm-tunnel-fe: already running — skipping"
    return 0
  fi
  if session_exists utm-tunnel-fe; then
    log "utm-tunnel-fe: tunnel is dead or unregistered — restarting (URL will change)"
    kill_session utm-tunnel-fe
  else
    log "utm-tunnel-fe: starting (quick tunnel -> :$FRONTEND_PORT)"
  fi
  [ -x "$CLOUDFLARED" ] || die "cloudflared not found at $CLOUDFLARED (set CLOUDFLARED_BIN)"
  : > "$TUNNEL_LOG"
  "$TMUX_BIN" new-session -d -s utm-tunnel-fe \
    "$CLOUDFLARED tunnel --url http://localhost:$FRONTEND_PORT 2>&1 | tee $TUNNEL_LOG"
  # cloudflared keeps retrying internally; wait for the full URL line so the
  # summary below can print it.
  wait_for 30 "tunnel URL in $TUNNEL_LOG" \
    bash -c "grep -qE 'https://[a-z0-9-]+\\.trycloudflare\\.com' '$TUNNEL_LOG'"
}

main() {
  command -v "$TMUX_BIN" >/dev/null 2>&1 || die "tmux not found"
  command -v curl >/dev/null 2>&1 || die "curl not found"
  local failed=0
  ensure_backend || failed=1
  ensure_frontend || failed=1
  ensure_tunnel || failed=1

  log "------------------------------------------------------------"
  log "backend : http://localhost:$BACKEND_PORT/api/v1/health"
  log "frontend: http://localhost:$FRONTEND_PORT"
  local url
  url="$(tunnel_url || true)"
  if [ -n "$url" ]; then
    log "tunnel  : $url  (same-origin /api proxy included)"
  else
    log "tunnel  : URL not yet in $TUNNEL_LOG — check: $TMUX_BIN attach -t utm-tunnel-fe"
  fi
  if [ "$failed" -ne 0 ]; then
    log "one or more components failed health checks (logs: $BACKEND_LOG $FRONTEND_LOG $TUNNEL_LOG)"
    exit 1
  fi
  log "demo is up"
}

main "$@"
