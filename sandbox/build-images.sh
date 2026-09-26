#!/usr/bin/env bash
# Build sandbox/<service>:<tag> for the versioned services at each sandbox tag.
#   ./sandbox/build-images.sh                   all four services at v1.3.0 and v1.4.0
#   ./sandbox/build-images.sh payment v1.4.0    one service at one tag
# Each tag builds from its own git worktree (shop@<tag> next to the sandbox), so an image holds
# exactly the tagged code whatever the sandbox has checked out. The codebase analyst reads the
# same worktrees later. An image already built from the tag's commit is skipped; FORCE=1 rebuilds.
set -euo pipefail
AGENT_DIR=$(cd "$(dirname "$0")/.." && pwd)
SANDBOX_DIR=${SANDBOX_DIR:-$AGENT_DIR/../opentelemetry-demo}
SANDBOX_DIR=$(cd "$SANDBOX_DIR" && pwd)
WORKTREES=${SHOP_WORKTREES:-$(dirname "$SANDBOX_DIR")}

# Keep in step with sandbox/overlay/compose.versions.yaml.
ALL_SERVICES=(payment quote checkout product-catalog)
ALL_TAGS=(v1.3.0 v1.4.0)
services=("${ALL_SERVICES[@]}")
tags=("${ALL_TAGS[@]}")
[ $# -ge 1 ] && services=("$1")
[ $# -ge 2 ] && tags=("$2")

for s in "${services[@]}"; do
  [[ " ${ALL_SERVICES[*]} " == *" $s "* ]] || { echo "$s isn't versioned; choose from: ${ALL_SERVICES[*]}" >&2; exit 1; }
done

for tag in "${tags[@]}"; do
  sha=$(git -C "$SANDBOX_DIR" rev-parse --verify -q "${tag}^{commit}") \
    || { echo "no tag $tag in $SANDBOX_DIR; run ./sandbox/setup.sh" >&2; exit 1; }
  wt="$WORKTREES/shop@$tag"
  if [ -d "$wt" ]; then
    git -C "$wt" checkout -q --detach "$sha"
  else
    git -C "$SANDBOX_DIR" worktree add -q --detach "$wt" "$sha"
  fi

  for s in "${services[@]}"; do
    image="sandbox/$s:$tag"
    built=$(docker image inspect -f '{{ index .Config.Labels "org.opencontainers.image.revision" }}' "$image" 2>/dev/null || true)
    if [ "$built" = "$sha" ] && [ -z "${FORCE:-}" ]; then
      echo "$image is up to date (${sha:0:8})"
      continue
    fi
    # The shop's .env names each service's Dockerfile, e.g. CART_DOCKERFILE=./src/cart/src/Dockerfile
    var="$(echo "$s" | tr 'a-z-' 'A-Z_')_DOCKERFILE"
    dockerfile=$(grep "^${var}=" "$wt/.env" | cut -d= -f2 | sed 's/[[:space:]]*#.*//')
    [ -n "$dockerfile" ] || { echo "no $var in $wt/.env" >&2; exit 1; }
    echo "building $image from $tag (${sha:0:8}) with $dockerfile"
    docker build -t "$image" -f "$wt/$dockerfile" \
      --label "org.opencontainers.image.revision=$sha" \
      --label "org.opencontainers.image.version=$tag" \
      "$wt"
  done
done

docker images --filter 'reference=sandbox/*' --format '{{.Repository}}:{{.Tag}}  {{.Size}}  {{.CreatedSince}}' | sort
