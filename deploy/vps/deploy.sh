#!/usr/bin/env bash
# Deploy the committed HEAD to the VPS: code, the API container and Postgres, migrations, and
# the worker service. Run from the repo root after init-env.sh (first time) and commit.
#   ./deploy/vps/deploy.sh
# Uncommitted changes are not deployed. Files the VPS owns (.env.agent, deploy/vps/.env, .venv,
# sandbox/compose.host.yaml) are left alone.
set -euo pipefail
HOST=${VPS_HOST:-root@155.138.161.5}
DIR=${VPS_DIR:-/opt/support-triage-agent}
DOMAIN=${VPS_DOMAIN:-support-triage-agent.duckdns.org}
UV_VERSION=0.12.17
AGENT_DIR=$(cd "$(dirname "$0")/../.." && pwd)
cd "$AGENT_DIR"

[ -z "$(git status --porcelain --untracked-files=no)" ] || echo "note: uncommitted changes are not deployed" >&2
ssh "$HOST" "test -f $DIR/.env.agent -a -f $DIR/deploy/vps/.env" \
  || { echo "no env on $HOST; run deploy/vps/init-env.sh first" >&2; exit 1; }

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
git archive HEAD | tar -x -C "$tmp"
echo "== sync $(git rev-parse --short HEAD) to $HOST:$DIR"
rsync -az --delete \
  --exclude /.env.agent --exclude /deploy/vps/.env --exclude /.venv --exclude /.local \
  --exclude /sandbox/compose.host.yaml --exclude __pycache__ \
  "$tmp/" "$HOST:$DIR/"

ssh "$HOST" DIR="$DIR" DOMAIN="$DOMAIN" UV_VERSION="$UV_VERSION" bash -s <<'REMOTE'
set -euo pipefail
cd "$DIR"
if ! command -v uv >/dev/null || [ "$(uv --version | cut -d' ' -f2)" != "$UV_VERSION" ]; then
  echo "== install uv $UV_VERSION"
  id=$(docker create "ghcr.io/astral-sh/uv:$UV_VERSION")
  docker cp "$id:/uv" /usr/local/bin/uv && docker rm "$id" >/dev/null
fi
cp deploy/vps/compose.shop.yaml sandbox/compose.host.yaml

echo "== worker venv"
uv sync --frozen --no-dev --quiet

echo "== postgres and api"
docker compose -f deploy/vps/compose.yaml up --detach --build --wait db
.venv/bin/python -m app.migrate
docker compose -f deploy/vps/compose.yaml up --detach --build --wait triage-api

echo "== worker"
install -m 644 deploy/vps/triage-worker.service /etc/systemd/system/triage-worker.service
systemctl daemon-reload
systemctl enable --quiet triage-worker
systemctl restart triage-worker
sleep 3
systemctl is-active triage-worker

echo "== check"
curl -fsS -o /dev/null -w "https://$DOMAIN/pipeline %{http_code}\n" "https://$DOMAIN/pipeline" \
  || echo "API not reachable at https://$DOMAIN yet (run deploy/vps/caddy.sh once)"
REMOTE
