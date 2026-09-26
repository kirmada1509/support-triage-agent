#!/usr/bin/env bash
# Change a flagd flag's default variant in the sandbox shop, and record it.
#   ./scenarios/flag.sh paymentFailure 25%
#   ./scenarios/flag.sh paymentFailure off
# Don't use the flagd web page during the demo: its changes aren't logged.
set -euo pipefail
flag=${1:?usage: flag.sh <flag> <variant>}
variant=${2:?usage: flag.sh <flag> <variant>}

AGENT_DIR=$(cd "$(dirname "$0")/.." && pwd)
SANDBOX_DIR=${SANDBOX_DIR:-$AGENT_DIR/../opentelemetry-demo}
cd "$AGENT_DIR"
uv run python scenarios/record.py flag "$SANDBOX_DIR/src/flagd/demo.flagd.json" "$flag" "$variant"
