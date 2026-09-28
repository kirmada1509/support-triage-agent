# Deployment

The hosted demo runs in two places:

| Part | Where | Address |
| --- | --- | --- |
| Triage Console (`web/`) | Vercel, project `support-triage-agent`, built on every push to `main` | https://support-triage-agent-delta.vercel.app |
| API (FastAPI), Postgres (pgvector), Caddy | VPS `108.61.252.195`, Docker Compose (`deploy/vps/compose.yaml`) | https://support-triage-agent.duckdns.org |
| Worker (Procrastinate + LangGraph) | VPS host, systemd `triage-worker` | outbound only |
| Sandbox shop, HolmesGPT and codebox images | VPS, `/opt/opentelemetry-demo` | 127.0.0.1:8080 only |

Railway was the first choice for the API and database; its free plan refused a new project.
The analysts can't run there anyway: they start their own containers and mount the fork by host
path, so the worker, the shop and the analysts share one Docker host (2 vCPU, 15 GB, Ubuntu 26.04,
Docker from Ubuntu's packages, ufw allowing 22, 80 and 443).

## No public ports but Caddy's

Docker publishes ports past ufw, so every published port is chosen on purpose: Caddy's 80/443
(HTTPS for the API, certificates in the `caddy-data` volume); Postgres on 127.0.0.1 and the
docker0 bridge only (the worker, and HolmesGPT's history queries); the shop's frontend proxy on
127.0.0.1:8080 (`compose.shop.yaml` resets every other shop port). The load generator is off:
the scenarios place their own baseline orders, and 2 vCPUs are better spent on them.

## The console on Vercel

The project is connected to the GitHub repo: every push to `main` builds and deploys it. Its
settings: Root Directory `web`, with files outside it included (the build prerenders the diagrams
from `../planning`), and `NEXT_PUBLIC_API_URL=https://support-triage-agent.duckdns.org` for
Production and Preview. A build from the repo root fails with "No Next.js version detected".
`./deploy/vercel.sh` still deploys the local checkout (prebuilt) without pushing.

## First time

```bash
./deploy/vercel.sh                                                        # console (later: every push); note its URL
./deploy/vps/init-env.sh https://support-triage-agent-delta.vercel.app   # VPS .env.agent, passwords
./deploy/vps/deploy.sh                                                    # code, Postgres, API, Caddy, worker
./deploy/vps/copy-db.sh                                                   # optional: local runs and indexes
./deploy/vps/setup-shop.sh                                                # fork, images, shop (slow)
```

Docker on a new server: `apt-get install docker.io docker-compose-v2 docker-buildx` and
`ufw allow 80/tcp; ufw allow 443/tcp`. Point `support-triage-agent.duckdns.org` at it first, or
Caddy can't get a certificate. Another host: `VPS_HOST=root@<ip> ./deploy/vps/...`.

## Every change

Commit, then `./deploy/vps/deploy.sh` (deploys `HEAD`; uncommitted changes are not sent). The
console deploys itself when `main` is pushed. A change under `sandbox/` needs `setup-shop.sh`
again.

## Operating it

```bash
ssh root@108.61.252.195
journalctl -u triage-worker -f                                      # worker logs
cd /opt/support-triage-agent
docker compose -f deploy/vps/compose.yaml logs -f triage-api caddy  # API and proxy logs
SANDBOX_DIR=/opt/opentelemetry-demo make scenario-4                 # reproduce a demo ticket
```

Secrets live only in `/opt/support-triage-agent/.env.agent` and `deploy/vps/.env` on the VPS
(mode 600). The API has no login: anyone with the console can create tickets, which spend the
DeepSeek credit shown in its sidebar, and approve replies.
