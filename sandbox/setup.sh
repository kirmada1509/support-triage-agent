#!/usr/bin/env bash
# Build the sandbox fork: the pinned upstream commit, the sandbox overlay, then the patches.
#   ./sandbox/setup.sh        (make sandbox)
# Clones into $SANDBOX_DIR if it isn't there. Re-running rebuilds branch `sandbox` from scratch
# and moves tags v1.3.0 (good) and v1.4.0 (four planted bugs). Authors, committer and dates are
# fixed, so the tags get the same SHAs on every machine.
set -euo pipefail
KIT=$(cd "$(dirname "$0")" && pwd)
AGENT_DIR=$(dirname "$KIT")
SANDBOX_DIR=${SANDBOX_DIR:-$AGENT_DIR/../opentelemetry-demo}
# shellcheck source=upstream.env
source "$KIT/upstream.env"

if [ ! -d "$SANDBOX_DIR/.git" ]; then
  # No upstream tags: upstream has 1.3.0 and 1.4.0 (2022 releases), one typo away from ours.
  git clone --no-tags "$UPSTREAM_URL" "$SANDBOX_DIR"
fi
cd "$SANDBOX_DIR"
dirty=$(git status --porcelain --untracked-files=no)
if [ -n "$dirty" ]; then
  echo "$SANDBOX_DIR has uncommitted changes; the sandbox branch is rebuilt from scratch:" >&2
  echo "$dirty" >&2
  echo "(flag.sh edits src/flagd/demo.flagd.json: git -C $SANDBOX_DIR checkout -- src/flagd)" >&2
  exit 1
fi

git config remote.origin.tagOpt --no-tags
if ! git cat-file -e "${UPSTREAM_SHA}^{commit}" 2>/dev/null; then
  git fetch --no-tags origin "$UPSTREAM_SHA"
fi
for t in 1.3.0 1.4.0; do
  if git rev-parse -q --verify "refs/tags/$t" >/dev/null; then
    echo "warning: upstream tag $t is present next to v$t; the agent must always use the v tags" >&2
  fi
done

# versions.env is what deploy.sh says is running; it belongs to this checkout, not to the fork.
grep -qx versions.env .git/info/exclude 2>/dev/null || echo versions.env >> .git/info/exclude

git_() { git -c commit.gpgsign=false -c core.hooksPath=/dev/null "$@"; }
export GIT_COMMITTER_NAME="Sandbox Setup" GIT_COMMITTER_EMAIL="sandbox@example.com"

git_ checkout -q -B sandbox "$UPSTREAM_SHA"

# 1. The overlay: files the fork owns (compose.versions.yaml, compose.extras.yaml, .env.override).
(cd "$KIT/overlay" && find . -type f) | while read -r f; do
  mkdir -p "$(dirname "$f")" && cp "$KIT/overlay/$f" "$f" && git add "$f"
done
GIT_AUTHOR_NAME="$GIT_COMMITTER_NAME" GIT_AUTHOR_EMAIL="$GIT_COMMITTER_EMAIL" \
GIT_AUTHOR_DATE="2026-09-21T09:00:00+00:00" GIT_COMMITTER_DATE="2026-09-21T09:00:00+00:00" \
  git_ commit -q -m "sandbox: versioned service images, pinned release images, longer trace retention" \
  -m "compose.versions.yaml runs payment, quote, checkout and product-catalog from images built per tag (sandbox/<service>:<tag>), and reports the tag as service.version. .env.override pins every other service to the 3.1.0 release images. compose.extras.yaml keeps more traces in Jaeger and runs fewer load-generator users."

# 2. The good baseline, then the release with the planted bugs.
git_ am -q --committer-date-is-author-date "$KIT"/patches/v1.3.0/*.patch
git tag -f v1.3.0 >/dev/null
git_ am -q --committer-date-is-author-date "$KIT"/patches/v1.4.0/*.patch
git tag -f v1.4.0 >/dev/null

v13=$(git rev-parse --short=8 v1.3.0)
v14=$(git rev-parse --short=8 v1.4.0)
echo "sandbox ready in $SANDBOX_DIR (branch sandbox)"
echo "  upstream $UPSTREAM_REF  ${UPSTREAM_SHA:0:8}"
echo "  v1.3.0   $v13"
echo "  v1.4.0   $v14"
git log --format='             %h %s' v1.3.0..v1.4.0
if [ "$v13" != "$EXPECTED_V1_3_0" ] || [ "$v14" != "$EXPECTED_V1_4_0" ]; then
  echo "warning: expected v1.3.0=$EXPECTED_V1_3_0 v1.4.0=$EXPECTED_V1_4_0 (sandbox/upstream.env)" >&2
fi
