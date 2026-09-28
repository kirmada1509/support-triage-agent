#!/usr/bin/env bash
# Replace the VPS database with a copy of the local one (tickets, events, investigations, the
# retrieval and code indexes, deploy and flag history), then re-run migrations for its roles.
#   ./deploy/vps/copy-db.sh           (refuses if the VPS already has tickets)
#   ./deploy/vps/copy-db.sh --force   (replaces them)
# Needs the local agent Postgres (make db) and a deployed VPS. Stops the API and worker while
# it restores.
set -euo pipefail
HOST=${VPS_HOST:-root@108.61.252.195}
DIR=${VPS_DIR:-/opt/support-triage-agent}
LOCAL_DB=${LOCAL_DB_CONTAINER:-support-triage-agent-db-1}
FORCE=${1:-}
[ -z "$FORCE" ] || [ "$FORCE" = --force ] || { echo "usage: copy-db.sh [--force]" >&2; exit 1; }

remote_psql() { ssh "$HOST" "docker exec -i support-triage-agent-db-1 psql -U triage -d triage -v ON_ERROR_STOP=1 $*"; }
count=$(remote_psql "-Atc 'select count(*) from tickets'" 2>/dev/null || echo 0)
if [ "$count" != 0 ] && [ "$FORCE" != --force ]; then
  echo "the VPS database has $count tickets; pass --force to replace them" >&2
  exit 1
fi
pending=$(docker exec "$LOCAL_DB" psql -U triage -d triage -Atc \
  "select count(*) from procrastinate_jobs where status in ('todo', 'doing')")
[ "$pending" = 0 ] || { echo "local queue has $pending unfinished jobs; let them finish first" >&2; exit 1; }

echo "== stop api and worker"
ssh "$HOST" "systemctl stop triage-worker; docker compose -f $DIR/deploy/vps/compose.yaml stop triage-api"
echo "== copy"
docker exec "$LOCAL_DB" pg_dump -U triage -d triage -Fc --no-owner --no-privileges \
  | ssh "$HOST" "docker exec -i support-triage-agent-db-1 pg_restore -U triage -d triage \
      --clean --if-exists --no-owner --no-privileges --single-transaction"
echo "== migrate and start"
ssh "$HOST" "cd $DIR && .venv/bin/python -m app.migrate \
  && docker compose -f deploy/vps/compose.yaml start triage-api && systemctl start triage-worker"
remote_psql "-Atc 'select count(*) || \$\$ tickets\$\$ from tickets'"
