#!/usr/bin/env bash
# Deploy one service of the sandbox shop at a tagged version, and record it.
#   ./scenarios/deploy.sh payment v1.4.0
# Needs the images built first (sandbox/<service>:<tag>, see the plan's "Versioned deploys").
set -euo pipefail
service=${1:?usage: deploy.sh <service> <version>}
version=${2:?usage: deploy.sh <service> <version>}

AGENT_DIR=$(cd "$(dirname "$0")/.." && pwd)
SANDBOX_DIR=${SANDBOX_DIR:-$AGENT_DIR/../opentelemetry-demo}
# Confirm against the shop's `make start-minimal` target and keep the same files, plus versions.
SHOP_COMPOSE_FILES=${SHOP_COMPOSE_FILES:-"-f compose.yaml -f compose.minimal.yaml -f compose.versions.yaml"}

cd "$SANDBOX_DIR"
var="$(echo "$service" | tr 'a-z-' 'A-Z_')_VERSION"
touch versions.env
previous=$(grep "^${var}=" versions.env | cut -d= -f2 || true)
previous=${previous:-v1.3.0}

# 1. what's deployed
if grep -q "^${var}=" versions.env; then
  sed -i.bak "s/^${var}=.*/${var}=${version}/" versions.env && rm -f versions.env.bak
else
  echo "${var}=${version}" >> versions.env
fi

# 2. restart only that service, without rebuilding
env_files="--env-file .env"
[ -f .env.override ] && env_files="$env_files --env-file .env.override"
# shellcheck disable=SC2086
docker compose $env_files --env-file versions.env $SHOP_COMPOSE_FILES \
  up -d --no-deps --no-build "$service"

# 3. record it, with the commit titles since the previous version
sha=$(git rev-parse "${version}^{commit}")
git log --format=%s "${previous}..${version}" -- "src/${service}/" \
  | (cd "$AGENT_DIR" && uv run python scenarios/record.py deploy "$service" "$version" "$previous" "$sha")

# 4. TODO(phase 5): index the new version: uv run python -m app.indexer "$service" "$sha"
