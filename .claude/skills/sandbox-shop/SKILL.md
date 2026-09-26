---
name: sandbox-shop
description: Start, reset, inspect or debug the sandbox shop (the OpenTelemetry Astronomy Shop fork), deploy a version, change a flag, or reproduce a demo ticket's scenario. Use for anything that needs the shop running, Jaeger, Prometheus, OpenSearch or the shop's Postgres.
---

# Run and debug the sandbox shop

Everything runs from the repo root. The fork is `../opentelemetry-demo` (or `SANDBOX_DIR`).
Details: `sandbox/README.md`.

## Bring it up

```bash
make db migrate          # our Postgres records deploys and flag changes
make sandbox             # only if ../opentelemetry-demo is missing or sandbox/ changed
make sandbox-images      # skips images already built from the current tags
make shop-up             # 25 containers, about 2.5 GB; UI on http://localhost:8080
make test-sandbox        # the fork and images are what the kit says
```

Wait until `./sandbox/compose.sh ps` shows the services healthy (frontend takes about a minute).

## Reproduce a ticket

`make scenario-N` (1..7, `cart`, `catalog`); `--no-send` prints the ticket instead of sending
it (`uv run python scenarios/scenario.py 4 --no-send`), and sending needs `make api`. A scenario
that didn't reproduce exits 1 and sends nothing; its PASS/FAIL lines and trace links say why.
Scenario 6 leaves `paymentFailure` at 25%: turn it off after with `make flag f=paymentFailure v=off`.

## Look at the data

- Jaeger: http://localhost:8080/jaeger/ui, API `.../jaeger/ui/api/traces/<id>`
- Prometheus: http://localhost:9090, e.g.
  `sum by (service_version, status_code) (increase(traces_span_metrics_calls_total{service_name="payment"}[15m]))`
- OpenSearch: `docker exec opensearch curl -s 'localhost:9200/otel-logs-*/_search?q=...'`
- Shop Postgres as the agent: `docker exec astronomy-db psql postgresql://agent_ro:agent_ro_password@localhost/astronomy_db`
- What's deployed: `cat ../opentelemetry-demo/versions.env`; history:
  `docker compose exec db psql -U triage -c 'select * from deploys'`

## Reset and troubleshoot

- A service on the wrong version: `DEPLOY_RECORD=0 ./scenarios/deploy.sh <service> v1.3.0`
  (switches without recording). Scenarios do this themselves.
- `no image sandbox/<service>:<tag>` or a stale-image test failure: `make sandbox-images`.
- `make sandbox` refuses because the fork is dirty: usually the flag file;
  `git -C ../opentelemetry-demo checkout -- src/flagd`.
- Port 5433 taken: another compose project's Postgres is running (often one started from a
  worktree); `docker ps` and stop that one.
- Traces missing their first half: Jaeger dropped them (memory cap) or restarted; check
  `docker stats jaeger` and rerun the scenario.
- `make shop-down` stops the shop and deletes its volumes: ask the user first.
