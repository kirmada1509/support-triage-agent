#!/usr/bin/env bash
# One-time (or after changing sandbox/): build the sandbox fork, its images and the analysts'
# images on the VPS, and start the shop with the VPS layer (no public ports, no load generator).
#   ./deploy/vps/setup-shop.sh
# Run deploy.sh first (it syncs the code and installs uv). Takes a while on 2 vCPUs.
set -euo pipefail
HOST=${VPS_HOST:-root@108.61.252.195}
DIR=${VPS_DIR:-/opt/support-triage-agent}

ssh "$HOST" DIR="$DIR" bash -s <<'REMOTE'
set -euo pipefail
cd "$DIR"
export SANDBOX_DIR=/opt/opentelemetry-demo
free_gb=$(df --output=avail -BG / | tail -1 | tr -dc 0-9)
[ "$free_gb" -ge 10 ] || { echo "only ${free_gb}G free on /; the shop needs about 10G" >&2; exit 1; }
cp deploy/vps/compose.shop.yaml sandbox/compose.host.yaml
make sandbox
make sandbox-images
make analyst-images
make shop-up
./sandbox/compose.sh ps --format '{{.Name}} {{.Status}}'
REMOTE
