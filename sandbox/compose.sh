#!/usr/bin/env bash
# docker compose for the sandbox shop: the shop's minimal mode (its `make start-minimal` files)
# plus compose.versions.yaml, with versions.env saying which tag each versioned service runs.
#   ./sandbox/compose.sh up --detach --no-build
#   ./sandbox/compose.sh ps
set -euo pipefail
AGENT_DIR=$(cd "$(dirname "$0")/.." && pwd)
SANDBOX_DIR=${SANDBOX_DIR:-$AGENT_DIR/../opentelemetry-demo}

cd "$SANDBOX_DIR"
touch versions.env
env_files=(--env-file .env)
[ -f .env.override ] && env_files+=(--env-file .env.override)
env_files+=(--env-file versions.env)

exec docker compose "${env_files[@]}" \
  -f compose.yaml -f compose.observability.yaml -f compose.extras.yaml -f compose.versions.yaml \
  "$@"
