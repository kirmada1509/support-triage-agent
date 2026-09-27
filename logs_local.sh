#!/usr/bin/env bash
# Follow the API, worker, and web logs in one labeled terminal view.
#   ./logs_local.sh
set -euo pipefail

if [ "$#" -ne 0 ]; then
  echo "usage: ./logs_local.sh" >&2
  exit 2
fi

ROOT=$(cd "$(dirname "$0")" && pwd)
LOGS="$ROOT/.local/logs"
for name in api worker web; do
  [ -f "$LOGS/$name.log" ] || {
    echo "missing $LOGS/$name.log; run ./start_local.sh first" >&2
    exit 1
  }
done

color=0
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then color=1; fi

tail -n 20 -F "$LOGS/api.log" "$LOGS/worker.log" "$LOGS/web.log" | awk -v color="$color" '
  /^==> .*\/api\.log <==$/ { name="api"; shade="\033[34m"; next }
  /^==> .*\/worker\.log <==$/ { name="worker"; shade="\033[33m"; next }
  /^==> .*\/web\.log <==$/ { name="web"; shade="\033[32m"; next }
  {
    if (name == "") next
    if (color) printf "%s[%s]\033[0m %s\n", shade, name, $0
    else printf "[%s] %s\n", name, $0
    fflush()
  }
'
