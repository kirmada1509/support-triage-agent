#!/usr/bin/env bash
# docker compose for the sandbox shop: the shop's minimal mode (its `make start-minimal` files)
# plus compose.versions.yaml, with versions.env saying which tag each versioned service runs.
#   ./sandbox/compose.sh up --detach --no-build
#   ./sandbox/compose.sh ps
# A host may add its own layer as sandbox/compose.host.yaml (git-ignored; the VPS uses
# deploy/vps/compose.shop.yaml there to keep every port off the public interface).
set -euo pipefail
AGENT_DIR=$(cd "$(dirname "$0")/.." && pwd)
SANDBOX_DIR=${SANDBOX_DIR:-$AGENT_DIR/../opentelemetry-demo}

cd "$SANDBOX_DIR"
touch versions.env
env_files=(--env-file .env)
[ -f .env.override ] && env_files+=(--env-file .env.override)
env_files+=(--env-file versions.env)

files=(-f compose.yaml -f compose.observability.yaml -f compose.extras.yaml -f compose.versions.yaml)
[ -f "$AGENT_DIR/sandbox/compose.host.yaml" ] && files+=(-f "$AGENT_DIR/sandbox/compose.host.yaml")

exec docker compose "${env_files[@]}" "${files[@]}" "$@"
