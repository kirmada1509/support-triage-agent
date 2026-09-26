# AGENTS.md

Context and rules for coding agents working in this repo. Read it before changing anything, and
keep it true (see "Keeping this file current" at the end).

Last updated: Sep 26, 2026, end of phase 0 (sandbox) plus its test suites.

## What this is

An AI first pass for B2B support tickets (built for a Zuddl demo). A ticket arrives through a
Pylon-style signed webhook, is enriched and categorized (Jev), and takes one of three lanes: a
cited Layer 1 answer, request triage, or a Layer 2 investigation where a data analyst
(HolmesGPT) and a read-only codebase analyst (mini-swe-agent) work in parallel against a real
microservice shop. Real bugs go to the owning team as Linear issues (Layer 3). A person approves
anything uncertain. A Next.js Triage Console shows every stage live.

| To know | Read |
| --- | --- |
| The design, and why | `planning/Agent_Architecture_And_Build_Plan.md` |
| What's built and what isn't | `planning/Build_Checklist.md` |
| The sandbox shop, its bugs and scenarios | `sandbox/README.md` |
| How to run things | `README.md` |

## Ground rules

1. **Work in the repo root** (`/Users/krishna/dev/support-triage-agent`), not in a git worktree
   under `.claude/worktrees/`. Paths break there: `SANDBOX_DIR` defaults to
   `../opentelemetry-demo` relative to the repo, and `make db` from a worktree starts a second
   Postgres that fights for port 5433.
2. **Start from the checklist.** Find the phase and item in `planning/Build_Checklist.md`, then the
   matching section of the plan. Build what the plan says, or change the plan first and say why.
3. **Test first** for anything with a spec code can check (see "Testing"). Model behaviour is
   judged by evals, not unit tests. A bug found later gets a failing test before its fix.
4. **One list of service names:** `config/ownership.yaml`. Jev's `service` choices, the
   enrichment's `likely_services`, and the sandbox's versioned services all use its keys.
5. **Read-only everywhere the agents touch the shop:** the data analyst's SQL runs as `agent_ro`,
   the codebase analyst gets read-only worktrees and no network. Never widen these to make
   something work.
6. **The answers stay here.** `sandbox/patches/` and `sandbox/README.md` say which commits are the
   planted bugs. The codebase analyst must only ever read the fork, never this repo, and nothing
   that names a bug may be copied into the fork.
7. **Secrets** live in `.env.agent` (git-ignored). Never commit keys; `agent_ro_password` is a
   sandbox-only password for a read-only role on demo data and is fine in the repo.
8. **Ask before destructive steps:** `make shop-down` (deletes the shop's volumes), dropping or
   recreating the dev database (`docker compose down -v`), `git push`, or anything that rewrites
   history outside the fork's generated `sandbox` branch.
9. **Pinned versions:** add dependencies with `uv add`, pin exact versions for LangGraph, Pydantic
   AI, HolmesGPT and mini-swe-agent, and upgrade on purpose.

## Repository map

```text
app/
  api/main.py       FastAPI: POST /webhooks/pylon (HMAC), /tickets, /tickets/{id}, /pipeline,
                    /tickets/{id}/events (+ /stream SSE, ?replay=1), /tickets/{id}/approve,
                    /simulator/templates, /simulator/tickets, /evals/scorecard
  api/schemas.py    request and response models
  graph/build.py    the StateGraph: NODES, edges, RETRY policies, pipeline_shape() for the console
  graph/state.py    TicketState (each node returns only the keys it changes)
  graph/routes.py   pick_lane, is_duplicate, pick_outcome: pure functions of the state
  graph/stream.py   emit() from inside nodes, staged() wrapper, run_graph() -> event sink
  graph/layout.yaml node positions for the console's flowchart
  nodes/*.py        one async run(state) per stage; stubs say `TODO(phase N)` in their docstring
  events.py         event models (discriminated union) the console renders
  models.py         Ticket, ContextBundle, Enrichment, Retrieved, Classification, Findings, Verdict...
  models_config.py  roles.yaml -> Pydantic AI model / LiteLLM string, fallbacks, UsageLimits, cost
  tasks.py          Procrastinate: run_ticket, resume_ticket; the checkpointer's psycopg pool
  tables.py, db.py  SQLAlchemy 2.0 tables (source of the migrations) and every query
  migrate.py        make migrate: Alembic, Procrastinate schema, checkpoint tables, demo tenant
  retrieval/, indexer/   empty until phases 3 and 5
config/             models.yaml (names, prices), roles.yaml (model per role), ownership.yaml
db/migrations/      Alembic; 0001 also creates the events NOTIFY trigger by hand
holmes/             HolmesGPT toolsets (drafted, not yet run) and condense_traces.py
codebox/            the codebase analyst's container and helper commands (drafted, not yet run)
sandbox/            builds the shop fork: pin, overlay, patches, setup, images, compose wrapper
scenarios/          tickets.yaml (7 demo tickets), scenario.py, send_ticket.py, deploy.sh, flag.sh,
                    record.py (writes deploy and flag history)
tests/              pytest suites (see Testing); tests/fixtures/ holds real captured data
planning/           the plan, the build checklist, three HTML diagrams
knowledge/ seed/ evals/ web/   placeholders with a README each (phases 3, 3, 3 and 9, 8)
.claude/skills/     project skills: sandbox-shop, planted-bugs (see "Skills and plugins")
```

## How it works (as built)

- **Intake.** The webhook checks `x-pylon-signature` (HMAC-SHA256 of the raw body with
  `PYLON_WEBHOOK_SECRET`), stores the ticket and defers `run_ticket`. It must answer fast.
- **Worker.** `run_ticket` runs the graph with the ticket ID as LangGraph's `thread_id`, so every
  step is checkpointed in Postgres. `approve` calls `interrupt()`; `POST .../approve` defers
  `resume_ticket`, which resumes with `Command(resume=decision)`. Both take a lock on the ticket ID.
- **Graph.** `context -> enrich -> (retrieve || jev) -> route`, then by lane: `layer1`,
  `requests`, or `duplicates -> brief -> (data_analyst || codebase_analyst) -> round2 -> verdict
  -> layer3 | approve`; every lane ends `approve -> reply -> remember`. `findings` is the one
  state key both analysts append to.
- **Nodes.** Plain async functions. Every node is wrapped by `staged()`, which emits
  running/done/failed events; a node may return `_summary` (one line for its flowchart node).
  Inside a node, `emit(...)` sends tool calls, model output and links to the console. Nodes that
  call outside services have a `RetryPolicy` in `build.py`.
- **Events.** Each emitted event is a row in `events`; a trigger NOTIFYs, and the SSE endpoint
  LISTENs on a plain psycopg connection. Stored events replay a run with no model calls.
- **Database.** One Postgres 16 + pgvector (`make db`, localhost:5433, user/password/db
  `triage`). Our tables are SQLAlchemy models migrated by Alembic; Procrastinate and the LangGraph
  checkpointer own their tables, which Alembic ignores.
- **Models.** `config/roles.yaml` picks a model and fallback per role (profile `cheap`: DeepSeek);
  `pydantic_ai_model(role)` and `litellm_model(role)` give the two naming forms;
  `LIMITS` caps each single call (`UsageLimits`).
- **Status.** Every node except `context`, `route` and `approve` is still a stub returning fixed
  data. See the checklist for what each phase replaces.

## The sandbox shop

The OpenTelemetry Astronomy Shop, release 3.1.0, forked to `../opentelemetry-demo` (override with
`SANDBOX_DIR`) and run in minimal mode (25 containers, about 2.5 GB).

- **Built, not edited.** `make sandbox` rebuilds branch `sandbox` in the fork from
  `sandbox/upstream.env` (pin), `sandbox/overlay/` (files the fork owns) and `sandbox/patches/`,
  with fixed authors and dates, so the tags have the same SHAs on every machine
  (`v1.3.0` = `e4243199`, `v1.4.0` = `6c877703`, also in `upstream.env`). To change a planted
  commit, use the `planted-bugs` skill.
- **Versions.** `v1.3.0` is upstream plus the setup (versioned images, pinned release images,
  trace retention, the `agent_ro` role). `v1.4.0` adds 8 commits: 4 planted bugs among 4 harmless.
- **The bugs** (lines at `v1.4.0`):

  | Bug | Where | Demo ticket |
  | --- | --- | --- |
  | Cards rejected in their expiry month (`>` became `>=`) | `src/payment/charge.js:88` | 4 |
  | Shipping doubled above 10 items (batches added to a total never reset) | `src/quote/app/routes.php:34-39` | 5 |
  | Non-USD carts not emptied (early return) | `src/checkout/main.go:544-554` | spare `cart` |
  | The Comet Book ($0.99) missing from the listing (`price_units > 0`) | `src/product-catalog/main.go:235` | spare `catalog` |

  Ticket 3 (Amex) is upstream's intended card-type rule, `charge.js:82-84`; ticket 6 is the
  `paymentFailure` flag at 25%. The plan's search bug was dropped: nothing calls `SearchProducts`.
- **Running it.** `make sandbox-images` builds `sandbox/<service>:<tag>` for payment, quote,
  checkout and product-catalog from worktrees `../shop@v1.3.0` and `../shop@v1.4.0`.
  `make shop-up` starts it; `versions.env` in the fork says which tag each versioned service
  runs. `make deploy s=payment v=v1.4.0` switches one and records the deploy (with commit titles)
  in our Postgres; `make flag f=paymentFailure v=25%` does the same for flags.
- **Scenarios.** `make scenario-N` (N = 1..7, `cart`, `catalog`) resets the service to `v1.3.0`
  without recording, places baseline orders, deploys `v1.4.0`, places the same orders again,
  checks in Jaeger that the bug reproduced, and only then sends the ticket with real times.
  Each scenario has its own shoppers (`figma-shopper-NN`, the `figma-merch` tenant) and each order
  its own trace ID.

**Facts about the shop, confirmed against 3.1.0** (the agents' tools depend on them):

- Host ports: the frontend proxy on 8080 (`/jaeger/ui`, `/grafana`, `/feature`, `/loadgen`) and
  Prometheus on 9090. Everything else is by name on the `opentelemetry-demo` Docker network:
  `jaeger:16686` (API under `/jaeger/ui/api`), `prometheus:9090`, `opensearch:9200`,
  `astronomy-db:5432` database `astronomy_db`.
- `agent_ro` / `agent_ro_password`: SELECT on schema `catalog` only, read-only transactions, 5 s
  statement timeout. Minimal mode has no order rows in Postgres; orders live in traces and logs.
- Traces: checkout's `PlaceOrder` span carries `user.id`; payment's `charge` span carries the
  decline message; `calculate-quote` carries `demo.shipping.quote.cost.total` and
  `demo.shipping.quote.items_count`; `ListProducts` carries `demo.product.count`. Card numbers are
  masked to the last four digits by the Collector.
- Metrics: `traces_span_metrics_calls_total` has `service_name`, `service_version`, `status_code`.
- Logs: one OpenSearch index a day, `otel-logs-yyyy-MM-dd`; records carry `resource.service.version`
  and `attributes.exception.message`.
- Checkout API: `POST /api/cart` `{item: {productId, quantity}, userId}`, then
  `POST /api/checkout?currencyCode=USD` with `{userId, userCurrency, email, address, creditCard}`
  (dashed card numbers, as in `src/load-generator/people.json`). A declined charge returns a
  generic 422; the reason is only in traces and logs.

## Commands

```bash
make install db migrate            # deps, agent Postgres (5433), migrations + demo tenant
make api / make worker             # FastAPI on :8000 / Procrastinate worker (separate terminals)
make send t=4                      # send demo ticket 4 as-is
make sandbox sandbox-images shop-up  # build the fork, its images, start the shop
make scenario-4                    # reproduce ticket 4 and send it (needs make api)
make deploy s=quote v=v1.4.0       # switch a versioned service, recorded
make flag f=paymentFailure v=off   # change a flag, recorded (FLAG_RECORD=0 to skip recording)
make migration m="..." ; make migrate ; make check-migrations
make lint fmt                      # ruff, line length 100
```

## Testing

| Suite | Command | Needs | What it covers |
| --- | --- | --- | --- |
| default | `make test` | nothing | units, the whole graph in memory, scenario logic against a simulated shop, the sandbox kit's files |
| `db` | `make test-db` | `make db` | migrations up/down, queries, NOTIFY, the worker pausing and resuming |
| `sandbox` | `make test-sandbox` | `make sandbox` | the fork's tags, each planted diff, `git blame` to the planted commits, images |
| `shop` | `make test-shop` | `make shop-up` | every scenario live (~3 min), recorded deploys, metrics, logs, `agent_ro` |

- Markers are excluded by default (`pyproject.toml` addopts). `db` and `shop` refuse to run unless
  `DATABASE_URL` names a database ending in `_test`; the make targets set it.
- **Replacing a stub node:** write its test first against `TicketState` (the state it receives,
  the keys it returns), with the model or tool faked, then implement; `tests/test_graph.py`
  keeps the lanes working end to end. Put each outside call (model, Jev, HolmesGPT, Postgres,
  HTTP) behind one small function a test can replace, send progress with `emit(...)`, and give a
  node that calls out a `RetryPolicy` in `app/graph/build.py`.
- **Scenario logic** is tested against `FakeShop` in `tests/test_scenarios.py`: every scenario
  must pass with its bug and fail without it. Keep that pair when adding a scenario.
- **Characterization data** (real responses) goes in `tests/fixtures/`, trimmed and free of
  personal data.
- Before committing, run `make lint test`, plus `test-db` if you touched the database,
  `test-sandbox` if you touched `sandbox/`, and `test-shop` if you touched scenarios or the shop.

## Conventions

- Python 3.12, `uv`, ruff (line length 100). Async throughout the app; SQLAlchemy 2.0 async with
  psycopg 3.
- Match the surrounding code: short module docstrings that say what the file is for, comments
  only where the reason isn't obvious, plain words. No `# fmt: skip` to dodge the line limit.
- Node functions are `async def run(state: TicketState) -> dict`. Keep side effects (DB, network)
  behind small functions that tests can replace.
- Pydantic models for everything passed between steps; never free text between nodes.
- Every ID a model returns (help section, ticket, deploy, trace, file) is checked in code against
  what it was given or fetched in that run.
- Database changes: edit `app/tables.py`, `make migration m="..."`, read the generated file and
  hand-write what autogenerate misses (triggers, functions, data) plus a working `downgrade()`,
  then `make migrate check-migrations test-db`. Never edit an applied migration; add one.
- Shell scripts: `set -euo pipefail`, a usage comment at the top, validate arguments before
  changing anything.
- Commits: one branch per phase (`phase-N-name`), a short imperative subject, a bullet body of
  what changed and why, and the trailer the harness asks for. Never commit `.env.agent`.

## Gotchas we've hit

- The shop's `.env` resolves `OTEL_RESOURCE_ATTRIBUTES` from its own `IMAGE_VERSION` before
  `.env.override` is read; the overlay restates it. `DEMO_VERSION=latest` has moved past 3.1.0,
  so the overlay pins it.
- Jaeger keeps traces in memory at about 50 KB each; 25000 traces fit its 1200M limit. Raise the
  cap and the memory together, or Jaeger restarts and every trace is gone.
- `flag.sh` edits `src/flagd/demo.flagd.json` in the fork, which leaves the fork dirty, and
  `make sandbox` then refuses to run: `git -C ../opentelemetry-demo checkout -- src/flagd`.
- A trace arrives in pieces (each service exports in batches): wait for the span you need
  (`Shop.spans(until=...)`) rather than the first response.
- The shop's clock is UTC; ticket times are the customer's local time.
- `condense_traces.py` still looks for `app.user.id` and `app.payment.card_type`; the shop sends
  `user.id` and `demo.payment.card_type` (fix in phase 5).
- The frontend has no search box and nothing calls `SearchProducts`; don't build on search.

## Skills and plugins

Project skills in `.claude/skills/`, for work only this repo has:

| Skill | Use it when |
| --- | --- |
| `sandbox-shop` | starting, resetting, or debugging the shop, or reproducing a scenario |
| `planted-bugs` | changing, adding or removing a commit in the fork, or the overlay |

Recommended plugins from the Claude plugin directory (install them from there; they aren't in
the repo). Where one disagrees with this file, this file wins.

| Plugin | Use it for |
| --- | --- |
| Superpowers | `test-driven-development`, `systematic-debugging`, `verification-before-completion`, `writing-plans` / `executing-plans`, code review. Don't use its `using-git-worktrees` skill here (ground rule 1). |
| claude-md-management | auditing and updating AGENTS.md at the end of a session |
| py-pit | FastAPI, Pydantic, SQLAlchemy, Alembic, pytest and uv practices |

## Finishing a task

1. Run the suites that cover the change (see Testing) and read the results. Say which ones you
   skipped and why; never report a suite as passing without running it.
2. `planning/Build_Checklist.md`: tick what now works and is tested, add what you found under the
   phase that will fix it, update the test counts and "Last updated".
3. This file and the READMEs: fix whatever the change made wrong (next section).
4. Commit on the phase branch with the docs in the same commit. Never commit `.env.agent`, and
   leave the fork (`../opentelemetry-demo`) clean.

## Keeping this file current

This file describes how the repo **is**, not how it will be. Update it in the same commit as the
change that makes it wrong, as step 3 of "Finishing a task".

- **What goes where.** Status (built or not) goes in `planning/Build_Checklist.md`. Design and
  rationale go in the plan. How to operate the sandbox goes in `sandbox/README.md`. This file
  holds the map, how things work as built, rules, conventions, commands and gotchas. Link rather
  than repeat.
- **Update it when:** a directory, module, command, make target, test suite, port, credential
  name, or convention changes; a stub node becomes real (update "How it works"); a phase finishes
  (update "Last updated"); you hit a gotcha that cost more than a few minutes (add it, with the fix).
- **Remove what's no longer true** in the same change. Stale guidance is worse than none.
- Keep it under about 300 lines; if a section grows past a screen, move the detail to the right
  README and leave a link.
- Change a ground rule only when the user asks.
