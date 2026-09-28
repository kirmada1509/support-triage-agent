# Support Triage Agent

An AI first pass for B2B support tickets. A ticket arrives through a Pylon-style signed webhook,
gets enriched and categorized by a structured LLM call, and takes one of three lanes: a cited Layer 1 answer, request
triage, or, for tech issues, a Layer 2 investigation where a data analyst (HolmesGPT) and a
read-only codebase analyst (mini-swe-agent) work in parallel against a real microservice shop.
False positives are answered directly; real bugs are routed to the owning engineering team
(Layer 3). A person approves anything uncertain. The API streams every stage into a live Triage Console.

The full design is in `planning/Agent_Architecture_And_Build_Plan.md`. Coding agents: start with
[AGENTS.md](AGENTS.md) (context, rules, and the playbooks in `.claude/skills/`).

## Status

Phases 1–2 provide intake, a checkpointed graph, live events and approval. Phase 3 adds a local
hybrid retrieval index: 31 help articles, 200 labelled synthetic past tickets and a fixed
20-ticket hit-rate set. Phase 4 adds real enrichment, retrieval, LLM categorization, cited Layer 1
answers and request triage. Jev is unavailable; the `jev` stage name remains for existing events.
Layer 2 and Phase 7 are implemented. Linear and Pylon delivery are optional for the demo:
without credentials, the ticket's finding and reply are recorded locally. Every completed
ticket has a final outcome in its detail endpoint and event stream. The Next.js Triage Console
shows the queue, live and replayed investigations, approvals, simulator, and scorecard.
[planning/Build_Checklist.md](planning/Build_Checklist.md) tracks each phase.

## Run it

Needs Docker, Python 3.12, [uv](https://docs.astral.sh/uv/) and Node.js for the console.

For an already configured checkout (`.env.agent` present), start the local Postgres, API, worker,
and console together with `./start_local.sh`. Open http://localhost:3000. Run
`./stop_local.sh` to stop only services the script started; it leaves an existing Postgres
container and the separate sandbox shop alone. Use `./start_local.sh --follow` to start the
services and watch one labeled API/worker/web log stream, or `./logs_local.sh` to attach later.
Ctrl-C closes the log view without stopping services. Logs are in ignored `.local/logs/`.

For a browser view of local logs and traces, first start the sandbox shop (`make shop-up`),
then run `./start_local.sh --observability`. The optional local collector reads the API,
worker, and web log files and sends them to the shop's existing OpenSearch through OpenTelemetry.
Open [Grafana Explore](http://localhost:8080/grafana/explore), choose **OpenSearch** for logs,
and filter `resource.service.name` to `support-triage-api`, `support-triage-worker`, or
`support-triage-web`. Choose **Jaeger** in Explore for traces, or use the
[Jaeger UI](http://localhost:8080/jaeger/ui/). The start script enables the worker's OTLP trace
export unless `OTEL_EXPORTER_OTLP_ENDPOINT` is already configured. `./stop_local.sh` stops only
its local log collector; it leaves the shop's Grafana, Jaeger, and OpenSearch running. The
terminal log viewer remains available with `--follow` or `./logs_local.sh`.

For first-time setup or separate terminals, use the commands below:

```bash
cp .env.agent.example .env.agent   # set HISTORY_DB_URL's random password; add API keys later
make install                       # uv sync
make db                            # Postgres 16 + pgvector on localhost:5433
make migrate                       # Alembic migrations, queue and checkpoint tables, demo tenant
make api                           # FastAPI on :8000 (another terminal)
make worker                        # runs the graph for each queued ticket (another terminal)
make send t=4                      # send demo ticket 4 from scenarios/tickets.yaml
```

Then watch it:

```bash
curl -s localhost:8000/tickets | jq                       # the queue
curl -s localhost:8000/tickets/<id> | jq '.outcome'        # final result after completion
curl -N localhost:8000/tickets/<id>/events/stream         # live events (SSE)
curl -N "localhost:8000/tickets/<id>/events/stream?replay=1"   # replay a stored run
curl -X POST localhost:8000/tickets/<id>/approve \
  -H 'content-type: application/json' -d '{"approved": true}'  # resume a paused run
```

Run `cd web && pnpm install && pnpm dev` in another terminal for the console at
http://localhost:3000. See [web/README.md](web/README.md) for type generation and checks.
To develop the investigation UI without the API, database, worker, shop, or LLM credentials,
run only `cd web && pnpm dev` and open http://localhost:3000/ticket/demo. Its recorded payment
run supports local playback and simulated approval; it does not send backend requests.

The hosted demo: console at https://support-triage-agent-delta.vercel.app, API at
https://support-triage-agent.duckdns.org (a VPS that also runs the worker and the shop). See
[deploy/README.md](deploy/README.md).

API docs at http://localhost:8000/docs. `make test` runs the graph end to end in memory and the
scenario logic against a simulated shop; `make test-db` runs the database tests on a throwaway
`triage_test` database. `make test-sandbox` and `make test-shop` check the shop fork and the
running shop (see [sandbox/README.md](sandbox/README.md)).

## Linear and Pylon delivery

Set `LINEAR_API_KEY` in `.env.agent` to create engineering issues. The service's `linear_team`
in `config/ownership.yaml` must match a team key in that Linear workspace. Set
`ROADMAP_LINEAR_TEAM` to route feature requests to a separate team. An engineering issue includes
the checked root cause, evidence references, reported symptom, file and commit, and a measured
lower bound on affected tickets. `GITHUB_REPO_URL` and `GRAFANA_PANEL_URL` add optional evidence
links; `JAEGER_BASE_URL` controls trace links. Without a Linear key, the finding stays local and
appears in the final outcome. Approval still follows severity, revenue impact and confidence.

For customer delivery, set `PYLON_API_TOKEN` and, for an EU workspace,
`PYLON_API_BASE_URL=https://api.eu.usepylon.com`. A live intake payload must include
`pylon_issue_id` in addition to the local `id`; it may include `pylon_message_id` (the top-level
ID of a customer-visible Pylon message). The reply adapter otherwise finds the latest
customer-authored visible message on the issue. For email it supplies the contact's email as a
recipient. Engineering issues and billing/account requests also produce an internal account
manager note. Demo tickets have no Pylon issue ID and their replies are logged. The intake
signature is this demo's HMAC header; Pylon's configurable webhook body and headers have not
been validated against it, so a real inbound Pylon webhook still needs an auth/payload adapter.
See the [Linear GraphQL guide](https://linear.app/developers/graphql) and
[Pylon message API](https://docs.usepylon.com/pylon-docs/developer/api/api-reference/messages).

## Retrieval

Run `make index-help index-tickets` after `make migrate` to fill the local database. The default
embedding model is [BAAI/bge-small-en-v1.5](https://huggingface.co/BAAI/bge-small-en-v1.5),
at revision `5c38ec7c`, downloaded on the first index run. Repeating either index command only
embeds changed text.
`make retrieval-hits` builds a separate throwaway `triage_retrieval_test` database and saves the
20-ticket score to [evals/retrieval_baseline.json](evals/retrieval_baseline.json). Current results:
help sections 7/7 in the top five; ticket memory 13/18 exact IDs in the top three (17/18 for an
equivalent synthetic issue family). Ticket 1's accepted-cards section ranks first. The benchmark
uses subject and body without an oracle service filter. The graph query also includes the
enrichment symptom and filters ticket memory by likely service.

`make front-eval` runs the real Phase 4 nodes on the 20 fixed tickets against the indexed local
database and writes [evals/phase4_baseline.json](evals/phase4_baseline.json). It needs the active
profile's model key. The score includes the actual route after confidence gating.

## Layout

```text
app/
  api/            FastAPI: webhook (HMAC), queue, ticket, /pipeline, events + SSE, approve,
                  simulator, scorecard
  graph/          LangGraph: state, build (nodes, edges, retries), routes, stream, layout.yaml
  nodes/          one async function per pipeline stage
  events.py       event models for the console (discriminated unions)
  models.py       Enrichment, Retrieved, Classification, Findings, Verdict, ...
  models_config.py  roles.yaml -> Pydantic AI model / LiteLLM string, fallbacks, limits
  tasks.py        Procrastinate: run_ticket, resume_ticket (+ the checkpointer's psycopg pool)
  tables.py       SQLAlchemy 2.0 models for our tables (the source of the migrations)
  db.py           async engine, sessions and every query the app runs
  retrieval/      phase 3 indexing, embedding, hybrid search and hit rates
  indexer/        phase 5 code index (ast-grep), service cards, export for the codebox
  integrations/   Linear GraphQL, Pylon HTTP and DeepSeek balance adapters
config/           models.yaml, roles.yaml, ownership.yaml (the one list of service names)
db/migrations/    Alembic: env.py and versions/ (0001 also creates the NOTIFY trigger)
holmes/           HolmesGPT's image and toolsets (jaeger, history, logs) + their helper scripts
codebox/          the codebase analyst's read-only container + helper commands
sandbox/          the shop fork's kit: pin, overlay, patches, setup, image builds, compose
scenarios/        tickets.yaml (9 demo tickets), scenario.py, send_ticket.py, deploy.sh, flag.sh
knowledge/ seed/ evals/   help, synthetic memory, fixed labels and the Phase 4 model baseline
web/                Next.js Triage Console (see its README)
deploy/             hosted demo: Vercel console, VPS API/Postgres/worker/shop (see its README)
```

## Database

One Postgres 16 with pgvector holds everything, but only our tables go through the ORM:

- **Our tables** (tickets, events, deploys, retrieval docs, code index, ...) are SQLAlchemy 2.0
  models in `app/tables.py`, queried in `app/db.py` with async sessions on the psycopg 3 driver,
  and migrated with Alembic. The API builds its responses straight from the rows
  (`from_attributes`).
- **Procrastinate** (the job queue) and **LangGraph's checkpointer** create and manage their own
  tables. Alembic ignores them.
- **The live stream** LISTENs on a plain psycopg connection, because the ORM has no LISTEN.
- **Analyst history access** uses `history_ro`, provisioned by `make migrate` from the password
  in `HISTORY_DB_URL`. It can select only `deploys` and `flag_changes`; Holmes runs the history
  queries with separately quoted values in `holmes/history_*.sql`.

Changing a table:

```bash
# edit app/tables.py, then
make migration m="add priority to tickets"   # autogenerates db/migrations/versions/<rev>_....py
# read the generated file, then
make migrate
make check-migrations                         # fails if a model change has no migration
```

Autogenerate doesn't see triggers, functions or data changes; write those by hand in the
migration, as `0001_initial_schema.py` does for the NOTIFY trigger.

## Sandbox

The shop is a fork of the OpenTelemetry Astronomy Shop pinned to release 3.1.0, cloned next to
this repo (`../opentelemetry-demo`, or set `SANDBOX_DIR`), with four planted bugs tagged `v1.4.0`
on top of a good `v1.3.0`. `sandbox/` builds it; see [sandbox/README.md](sandbox/README.md).

```bash
make sandbox          # clone, pin, apply the planted bugs, tag v1.3.0 and v1.4.0
make sandbox-images   # sandbox/<service>:<tag> for payment, quote, checkout, product-catalog
make shop-up          # the shop in minimal mode on http://localhost:8080
make scenario-4       # reproduce ticket 4 in the shop, check it in Jaeger, send the ticket
```

`make deploy s=payment v=v1.4.0` switches a service's version and records the deploy;
`make flag f=paymentFailure v=25%` changes a flag and records it. Both write to this repo's
Postgres, which is where the agent reads deploy and flag history.
