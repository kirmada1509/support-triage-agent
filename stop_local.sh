#!/usr/bin/env bash
# Stop only the local services and Postgres container started by start_local.sh.
#   ./stop_local.sh
set -euo pipefail

if [ "$#" -ne 0 ]; then
  echo "usage: ./stop_local.sh" >&2
  exit 2
fi

ROOT=$(cd "$(dirname "$0")" && pwd)
STATE="$ROOT/.local"
cd "$ROOT"

stop_process() {
  local name="$1" file pid started
  file="$STATE/$name.pid"
  [ -f "$file" ] || { echo "$name was not started by start_local.sh"; return; }
  pid=$(sed -n '1p' "$file")
  started=$(sed -n '2p' "$file")
  if [[ ! "$pid" =~ ^[0-9]+$ ]] || [ -z "$started" ] \
    || [ "$(ps -p "$pid" -o lstart= 2>/dev/null)" != "$started" ]; then
    echo "$name is no longer running; removing stale PID file"
    rm -f "$file"
    return
  fi
  kill -TERM -- "-$pid" 2>/dev/null || true
  for attempt in {1..20}; do
    if ! kill -0 -- "-$pid" 2>/dev/null; then break; fi
    sleep 0.25
  done
  if kill -0 -- "-$pid" 2>/dev/null; then
    kill -KILL -- "-$pid" 2>/dev/null || true
  fi
  rm -f "$file"
  echo "stopped $name"
}

stop_process web
stop_process worker
stop_process api

if [ -f "$STATE/db.id" ]; then
  started_id=$(sed -n '1p' "$STATE/db.id")
  started_at=$(sed -n '2p' "$STATE/db.id")
  if command -v docker >/dev/null 2>&1 \
    && [ -n "$started_id" ] && [ -n "$started_at" ] \
    && [ "$(docker compose ps --status running -q db 2>/dev/null)" = "$started_id" ] \
    && [ "$(docker inspect -f '{{.State.StartedAt}}' "$started_id" 2>/dev/null)" = "$started_at" ]; then
    docker compose stop db
    echo "stopped Postgres"
  else
    echo "Postgres container changed; leaving it alone"
  fi
  rm -f "$STATE/db.id"
else
  echo "Postgres was already running or was not started by start_local.sh"
fi
