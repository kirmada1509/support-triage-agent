# Support Triage Agent

An AI first pass for B2B support tickets. A ticket arrives through a Pylon-style signed webhook,
gets enriched and categorized (Jev), and takes one of three lanes: a cited Layer 1 answer, request
triage, or, for tech issues, a Layer 2 investigation where a data analyst (HolmesGPT) and a
read-only codebase analyst (mini-swe-agent) work in parallel against a real microservice shop.
False positives are answered directly; real bugs go to the owning engineering team (Layer 3).
A person approves anything uncertain. The Triage Console shows every stage live.

The full design is in `planning/Agent_Architecture_And_Build_Plan.md`. Coding agents: start with
[AGENTS.md](AGENTS.md) (context, rules, and the playbooks in `.claude/skills/`).

## Status

Phases 1–2 scaffold: the whole LangGraph pipeline runs end to end with stub nodes, checkpointed
in Postgres, streaming every event to the console API, pausing for approval and resuming.
Each stub node says in its docstring what replaces it and in which phase (`TODO(phase N)`).
Phase 0 (the sandbox) is done. [planning/Build_Checklist.md](planning/Build_Checklist.md) tracks what's
built and what isn't, phase by phase.

## Run it

Needs Docker, Python 3.12 and [uv](https://docs.astral.sh/uv/).

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
curl -N localhost:8000/tickets/<id>/events/stream         # live events (SSE)
curl -N "localhost:8000/tickets/<id>/events/stream?replay=1"   # replay a stored run
curl -X POST localhost:8000/tickets/<id>/approve \
  -H 'content-type: application/json' -d '{"approved": true}'  # resume a paused run
```

API docs at http://localhost:8000/docs. `make test` runs the graph end to end in memory and the
scenario logic against a simulated shop; `make test-db` runs the database tests on a throwaway
`triage_test` database. `make test-sandbox` and `make test-shop` check the shop fork and the
running shop (see [sandbox/README.md](sandbox/README.md)).

## Layout

```text
app/
  api/            FastAPI: webhook (HMAC), queue, ticket, /pipeline, events + SSE, approve,
                  simulator, scorecard
  graph/          LangGraph: state, build (nodes, edges, retries), routes, stream, layout.yaml
  nodes/          one async function per stage (stubs until phases 4–7)
  events.py       event models for the console (discriminated unions)
  models.py       Enrichment, Retrieved, Classification, Findings, Verdict, ...
  models_config.py  roles.yaml -> Pydantic AI model / LiteLLM string, fallbacks, limits
  tasks.py        Procrastinate: run_ticket, resume_ticket (+ the checkpointer's psycopg pool)
  tables.py       SQLAlchemy 2.0 models for our tables (the source of the migrations)
  db.py           async engine, sessions and every query the app runs
  retrieval/      phase 3        indexer/   phase 5
config/           models.yaml, roles.yaml, ownership.yaml (the one list of service names)
db/migrations/    Alembic: env.py and versions/ (0001 also creates the NOTIFY trigger)
holmes/           HolmesGPT's image and toolsets (jaeger, history, logs) + their helper scripts
codebox/          the codebase analyst's read-only container + helper commands
sandbox/          the shop fork's kit: pin, overlay, patches, setup, image builds, compose
scenarios/        tickets.yaml (7 demo tickets), scenario.py, send_ticket.py, deploy.sh, flag.sh
knowledge/ seed/ evals/ web/   phase 3, 3, 3 (dataset) and 9 (runs), 8 (see each README)
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
