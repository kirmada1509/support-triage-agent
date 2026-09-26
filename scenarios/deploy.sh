#!/usr/bin/env bash
# Deploy one service of the sandbox shop at a tagged version, and record it.
#   ./scenarios/deploy.sh payment v1.4.0
# Needs the images built first (./sandbox/build-images.sh). DEPLOY_RECORD=0 switches the version
# without recording a deploy, for resetting the sandbox before a scenario.
set -euo pipefail
service=${1:?usage: deploy.sh <service> <version>}
version=${2:?usage: deploy.sh <service> <version>}

AGENT_DIR=$(cd "$(dirname "$0")/.." && pwd)
SANDBOX_DIR=${SANDBOX_DIR:-$AGENT_DIR/../opentelemetry-demo}
export SANDBOX_DIR

case "$service" in
  payment | quote | checkout | product-catalog) ;;
  *) echo "$service isn't versioned; choose payment, quote, checkout or product-catalog" >&2; exit 1 ;;
esac
sha=$(git -C "$SANDBOX_DIR" rev-parse --verify -q "${version}^{commit}") \
  || { echo "no tag $version in $SANDBOX_DIR" >&2; exit 1; }
docker image inspect "sandbox/$service:$version" >/dev/null 2>&1 \
  || { echo "no image sandbox/$service:$version; run ./sandbox/build-images.sh $service $version" >&2; exit 1; }

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

# 2. restart only that service, without rebuilding, and wait until it's healthy
"$AGENT_DIR/sandbox/compose.sh" up --detach --no-deps --no-build --wait --wait-timeout 120 "$service"

if [ "${DEPLOY_RECORD:-1}" = 0 ] || [ "$previous" = "$version" ]; then
  echo "$service is on $version (not recorded)"
  exit 0
fi

# 3. record it, with the commit titles since the previous version
git log --format=%s "${previous}..${version}" -- "src/${service}/" \
  | (cd "$AGENT_DIR" && uv run python scenarios/record.py deploy "$service" "$version" "$previous" "$sha")

# 4. TODO(phase 5): index the new version: uv run python -m app.indexer "$service" "$sha"
