#!/usr/bin/env bash
# Build the console locally and deploy the output to Vercel production, without pushing. (Every
# push to main deploys it too, through the project's Git connection.) Prebuilt, because the build
# prerenders the How it works diagrams from ../planning, which an upload of web/ lacks.
#   ./deploy/vercel.sh                            (API at https://support-triage-agent.duckdns.org)
#   API_URL=https://api.example.com ./deploy/vercel.sh
set -euo pipefail
API_URL=${API_URL:-https://support-triage-agent.duckdns.org}
PROJECT=${VERCEL_PROJECT:-support-triage-agent}
[[ $API_URL == https://* ]] || { echo "API_URL must start with https://" >&2; exit 1; }
cd "$(dirname "$0")/../web"

[ -f .vercel/project.json ] || vercel link --yes --project "$PROJECT"
vercel pull --yes --environment=production >/dev/null
NEXT_PUBLIC_API_URL=$API_URL vercel build --prod
vercel deploy --prebuilt --prod
