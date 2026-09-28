#!/usr/bin/env bash
# One-time: write the VPS's .env.agent and deploy/vps/.env (compose's Postgres password).
#   ./deploy/vps/init-env.sh https://<console>.vercel.app
# Model keys come from the local .env.agent; the database and history passwords and the
# webhook secret are new random values. Refuses to overwrite files already on the VPS.
set -euo pipefail
CONSOLE=${1:?usage: init-env.sh <console origin, e.g. https://support-triage-agent.vercel.app>}
HOST=${VPS_HOST:-root@108.61.252.195}
DIR=${VPS_DIR:-/opt/support-triage-agent}
DOMAIN=${VPS_DOMAIN:-support-triage-agent.duckdns.org}
AGENT_DIR=$(cd "$(dirname "$0")/../.." && pwd)
[[ $CONSOLE == https://* ]] || { echo "console origin must start with https://" >&2; exit 1; }

if ssh "$HOST" "test -e $DIR/.env.agent -o -e $DIR/deploy/vps/.env"; then
  echo "$HOST already has $DIR/.env.agent or deploy/vps/.env; edit it there instead" >&2
  exit 1
fi

key() { grep -E "^$1=" "$AGENT_DIR/.env.agent" | tail -1 | cut -d= -f2- || true; }
random() { openssl rand -hex 24; }
db_password=$(random)
history_password=$(random)

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
cat > "$tmp/env.agent" <<ENV
# Written by deploy/vps/init-env.sh. The worker (host) reads it; the API container too, with
# DATABASE_URL replaced by the compose network's.
DATABASE_URL=postgresql://triage:$db_password@localhost:5433/triage
HISTORY_DB_URL=postgresql://history_ro:$history_password@localhost:5433/triage
PYLON_WEBHOOK_SECRET=$(random)
API_BASE_URL=https://$DOMAIN
CORS_ORIGINS=$CONSOLE
SANDBOX_DIR=/opt/opentelemetry-demo
DEEPSEEK_API_KEY=$(key DEEPSEEK_API_KEY)
OPENROUTER_API_KEY=$(key OPENROUTER_API_KEY)
GEMINI_API_KEY=$(key GEMINI_API_KEY)
OPENAI_API_KEY=$(key OPENAI_API_KEY)
LINEAR_API_KEY=$(key LINEAR_API_KEY)
ENV
printf 'POSTGRES_PASSWORD=%s\n' "$db_password" > "$tmp/compose.env"

ssh "$HOST" "mkdir -p $DIR/deploy/vps"
scp -q "$tmp/env.agent" "$HOST:$DIR/.env.agent"
scp -q "$tmp/compose.env" "$HOST:$DIR/deploy/vps/.env"
ssh "$HOST" "chmod 600 $DIR/.env.agent $DIR/deploy/vps/.env"
echo "wrote $HOST:$DIR/.env.agent and deploy/vps/.env"
