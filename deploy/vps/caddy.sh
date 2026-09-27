#!/usr/bin/env bash
# One-time: add the API's site to the VPS's shared Caddy (voice-runtime's, which owns 80/443).
#   ./deploy/vps/caddy.sh
# Backs the Caddyfile up, appends one site block (appending keeps the bind-mounted file's inode),
# validates, and reloads Caddy without a restart; restores the backup if validation fails.
set -euo pipefail
HOST=${VPS_HOST:-root@155.138.161.5}
DOMAIN=${VPS_DOMAIN:-support-triage-agent.duckdns.org}

ssh "$HOST" DOMAIN="$DOMAIN" bash -s <<'REMOTE'
set -euo pipefail
FILE=/opt/dhwani/deploy/Caddyfile
CADDY=voice-runtime-caddy-1
if grep -q "^$DOMAIN " "$FILE"; then echo "$DOMAIN is already in $FILE"; exit 0; fi
backup="$FILE.bak-support-triage-$(date +%Y%m%d%H%M%S)"
cp -p "$FILE" "$backup"
cat >> "$FILE" <<SITE

$DOMAIN {
	# Server-sent events: pass every chunk through at once, and don't compress them.
	reverse_proxy support-triage-api:8000 {
		flush_interval -1
	}

	header {
		Strict-Transport-Security "max-age=31536000; includeSubDomains"
		X-Content-Type-Options "nosniff"
		Referrer-Policy "strict-origin-when-cross-origin"
		-Server
	}
}
SITE
if ! docker exec "$CADDY" caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile; then
  cat "$backup" > "$FILE"
  echo "invalid Caddyfile; restored $backup" >&2
  exit 1
fi
docker exec "$CADDY" caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile
echo "added $DOMAIN (backup: $backup)"
REMOTE
