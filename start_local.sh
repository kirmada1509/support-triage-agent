#!/usr/bin/env bash
# Start the local Postgres, API, worker, and Next.js console. Run from any directory.
#   ./start_local.sh [--follow] [--observability]
set -Eeuo pipefail

follow=0
observability=0
for option in "$@"; do
  case "$option" in
    --follow) [ "$follow" -eq 0 ] || { echo "duplicate --follow" >&2; exit 2; }; follow=1 ;;
    --observability) [ "$observability" -eq 0 ] || { echo "duplicate --observability" >&2; exit 2; }; observability=1 ;;
    *) echo "usage: ./start_local.sh [--follow] [--observability]" >&2; exit 2 ;;
  esac
done

ROOT=$(cd "$(dirname "$0")" && pwd)
STATE="$ROOT/.local"
cd "$ROOT"

for command in docker uv pnpm python3 curl; do
  command -v "$command" >/dev/null 2>&1 || { echo "missing $command" >&2; exit 1; }
done
[ -f .env.agent ] || { echo "missing .env.agent; copy .env.agent.example and configure it" >&2; exit 1; }
docker compose version >/dev/null
if [ "$observability" -eq 1 ]; then
  if [ "$(docker inspect -f '{{.State.Running}}' otel-collector 2>/dev/null)" != true ] \
    || [ "$(docker inspect -f '{{.State.Running}}' grafana 2>/dev/null)" != true ]; then
    echo "--observability needs the sandbox observability stack; run make shop-up first" >&2
    exit 1
  fi
  if [ -z "${OTEL_EXPORTER_OTLP_ENDPOINT:-}" ] \
    && ! grep -Eq '^[[:space:]]*OTEL_EXPORTER_OTLP_ENDPOINT=' .env.agent; then
    export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:8080/otlp-http
  fi
fi

managed() {
  local file="$STATE/$1.pid" pid started
  [ -f "$file" ] || return 1
  pid=$(sed -n '1p' "$file")
  started=$(sed -n '2p' "$file")
  [[ "$pid" =~ ^[0-9]+$ ]] && [ -n "$started" ] && kill -0 "$pid" 2>/dev/null \
    && [ "$(ps -p "$pid" -o lstart= 2>/dev/null)" = "$started" ]
}

port_busy() {
  python3 - "$1" <<'PY'
import socket
import sys

with socket.socket() as connection:
    connection.settimeout(0.5)
    sys.exit(connection.connect_ex(("127.0.0.1", int(sys.argv[1]))) != 0)
PY
}

if ! managed api && port_busy 8000; then
  echo "port 8000 is in use by an API not started by this script" >&2
  exit 1
fi
if ! managed web && port_busy 3000; then
  echo "port 3000 is in use by a web server not started by this script" >&2
  exit 1
fi

mkdir -p "$STATE/logs"
started_services=()
started_db=0
started_collector=0
finished=0
cleanup() {
  if [ "$finished" -eq 1 ]; then return; fi
  for name in "${started_services[@]}"; do
    pid=$(sed -n '1p' "$STATE/$name.pid")
    kill -TERM -- "-$pid" 2>/dev/null || true
    rm -f "$STATE/$name.pid"
  done
  if [ "$started_collector" -eq 1 ]; then
    docker compose --profile observability stop local-log-collector >/dev/null 2>&1 || true
    rm -f "$STATE/local-log-collector.id"
  fi
  if [ "$started_db" -eq 1 ]; then
    docker compose stop db >/dev/null 2>&1 || true
    rm -f "$STATE/db.id"
  fi
}
trap cleanup EXIT

if [ -z "$(docker compose ps --status running -q db)" ]; then
  docker compose up -d db
  db_id=$(docker compose ps -q db)
  printf '%s\n%s\n' "$db_id" "$(docker inspect -f '{{.State.StartedAt}}' "$db_id")" \
    > "$STATE/db.id"
  started_db=1
fi

for attempt in {1..30}; do
  if docker compose exec -T db pg_isready -U triage >/dev/null 2>&1; then break; fi
  if [ "$attempt" -eq 30 ]; then echo "Postgres did not become ready" >&2; exit 1; fi
  sleep 1
done

if [ ! -d web/node_modules ]; then
  (cd web && pnpm install --frozen-lockfile)
fi
make migrate

launch() {
  local name="$1" directory="$2"
  shift 2
  if managed "$name"; then
    echo "$name already running (PID $(sed -n '1p' "$STATE/$name.pid"))"
    return
  fi
  rm -f "$STATE/$name.pid"
  (
    cd "$directory"
    python3 -c 'import os, sys; os.setsid(); os.execvp(sys.argv[1], sys.argv[1:])' "$@" \
      > "$STATE/logs/$name.log" 2>&1 &
    pid=$!
    printf '%s\n%s\n' "$pid" "$(ps -p "$pid" -o lstart=)" > "$STATE/$name.pid"
  )
  started_services+=("$name")
  echo "started $name (PID $(sed -n '1p' "$STATE/$name.pid"))"
}

wait_for() {
  local name="$1" url="$2"
  for attempt in {1..60}; do
    if curl --silent --fail --output /dev/null "$url"; then return; fi
    if ! managed "$name"; then break; fi
    sleep 0.5
  done
  echo "$name did not become ready; see $STATE/logs/$name.log" >&2
  tail -n 20 "$STATE/logs/$name.log" >&2 || true
  return 1
}

launch api "$ROOT" uv run uvicorn app.api.main:app --reload --port 8000
wait_for api http://localhost:8000/openapi.json
launch worker "$ROOT" uv run python -m procrastinate --app=app.tasks.app worker
sleep 1
managed worker || { echo "worker exited; see $STATE/logs/worker.log" >&2; exit 1; }
launch web "$ROOT/web" pnpm dev
wait_for web http://localhost:3000/tickets

if [ "$observability" -eq 1 ]; then
  if [ -z "$(docker compose --profile observability ps --status running -q local-log-collector)" ]; then
    docker compose --profile observability up -d local-log-collector
    collector_id=$(docker compose --profile observability ps -q local-log-collector)
    printf '%s\n%s\n' "$collector_id" "$(docker inspect -f '{{.State.StartedAt}}' "$collector_id")" \
      > "$STATE/local-log-collector.id"
    started_collector=1
  fi
  sleep 2
  if [ -z "$(docker compose --profile observability ps --status running -q local-log-collector)" ]; then
    echo "local log collector exited; inspect docker compose --profile observability logs local-log-collector" >&2
    exit 1
  fi
  echo "Logs and traces: http://localhost:8080/grafana/explore"
fi

finished=1
echo "Ready: http://localhost:3000 (API http://localhost:8000)"
echo "Logs: $STATE/logs/"
echo "Stop: ./stop_local.sh"
if [ "$follow" -eq 1 ]; then
  echo "Following logs; Ctrl-C closes this view but leaves services running."
  exec "$ROOT/logs_local.sh"
fi
