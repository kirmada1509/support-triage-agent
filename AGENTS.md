# AGENTS.md

Context and rules for coding agents working in this repo. Read it before changing anything, and
keep it true (see "Keeping this file current" at the end).

Last updated: Sep 26, 2026, during phase 5 (code index and codebox helpers).

## What this is

An AI first pass for B2B support tickets (built for a Zuddl demo). A ticket arrives through a
Pylon-style signed webhook, is enriched and categorized by a structured LLM call, and takes one
of three lanes: a cited Layer 1 answer, request triage, or a Layer 2 investigation where a data
analyst (HolmesGPT) and a read-only codebase analyst (mini-swe-agent) work in parallel against a real
microservice shop. Real bugs go to the owning team as Linear issues (Layer 3). A person approves
anything uncertain. A Next.js Triage Console shows every stage live.

| To know | Read |
| --- | --- |
| What is implemented now | `CODEBASE_SUMMARY.md` |
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
4. **One list of service names:** `config/ownership.yaml`. Classification's `service` choice, the
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
   AI and mini-swe-agent (`pyproject.toml`) and HolmesGPT (`holmes/Dockerfile`), and upgrade on
   purpose, rerunning `make test-spike`.

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
  nodes/*.py        one async run(state) per stage; later stubs say `TODO(phase N)`
  events.py         event models (discriminated union) the console renders
  models.py         Ticket, ContextBundle, Enrichment, Retrieved, Classification, Findings, Verdict...
  models_config.py  roles.yaml -> Pydantic AI model / LiteLLM string, fallbacks, UsageLimits, cost
  tasks.py          Procrastinate: run_ticket, resume_ticket; the checkpointer's psycopg pool
  tables.py, db.py  SQLAlchemy 2.0 tables (source of the migrations) and every query
  migrate.py        make migrate: Alembic, history_ro, Procrastinate schema, checkpoint tables,
                    demo tenant
  history_access.py provisions the history_ro login for the analyst's deploy/flag queries
  tracing.py        the agent's own OpenTelemetry export (off unless OTEL_EXPORTER_OTLP_ENDPOINT)
  retrieval/        phase 3: Markdown chunking, local embeddings, incremental indexing,
                    hybrid search and hit-rate CLI
  indexer/          phase 5 code index: extract.py (ast-grep), build.py (from git), card.py
                    (service cards), export.py (TSV for the codebox), __main__.py (CLI)
config/             models.yaml (names, prices), roles.yaml (model per role), ownership.yaml
db/migrations/      Alembic; 0001 also creates the events NOTIFY trigger by hand
holmes/             HolmesGPT's image (Dockerfile), config.yaml, toolsets.yaml, condense_traces.py,
                    search_logs.py (the `logs` toolset's OpenSearch search), history_*.sql
codebox/            the codebase analyst's read-only container; bin/ has the helper commands
                    (read the exported index at /index, else ctags and rg) and a git wrapper
sandbox/            builds the shop fork: pin, overlay, patches, setup, images, compose wrapper
scenarios/          tickets.yaml (7 demo tickets), scenario.py, send_ticket.py, deploy.sh, flag.sh,
                    record.py (writes deploy and flag history)
tests/              pytest suites (see Testing); tests/fixtures/ holds real captured data
planning/           the plan, the build checklist, the phase 2 spike results, three HTML diagrams
knowledge/          31 help articles / 62 sections with source map
seed/               200 labelled synthetic tickets and generator
evals/              20 fixed ticket labels, retrieval and Phase 4 model baselines
web/                phase 8 placeholder
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
  checkpointer own their tables, which Alembic ignores. `make migrate` also provisions
  `history_ro` from `HISTORY_DB_URL`, with SELECT on `deploys` and `flag_changes` only. HolmesGPT's
  history tool passes model values to `psql` variables in `holmes/history_*.sql`.
- **Retrieval.** `make index-help index-tickets` embeds 62 help sections and 200 synthetic ticket
  memories into `retrieval_docs` with local `BAAI/bge-small-en-v1.5` pinned at `5c38ec7c`.
  Unchanged text is not re-embedded. Search filters the vector and full-text candidates, then
  fuses their ranks. The graph's retrieve node now uses the index. `make retrieval-hits` uses a
  separate throwaway database and records the 20-ticket result in `evals/retrieval_baseline.json`
  (help 7/7 top 5, ticket memory 13/18 exact IDs top 3, 17/18 same synthetic issue family).
  Ticket 1's section is first.
- **Models: provider-agnostic.** No code names a provider. `config/roles.yaml` has one profile
  per provider (`deepseek`, the default; `gemini`; `openai`; `openrouter`), each role with a
  model and a fallback on the same provider, so a profile needs one key. `ROLE_PROFILE` switches
  every role; `ROLE_MODELS="role=model,..."` moves single roles to any model in
  `config/models.yaml` (no fallback). A model's provider is the prefix of its `pydantic_ai` name
  and decides its key (`PROVIDER_KEYS`). `pydantic_ai_model(role)` builds it with its own
  `settings` (a `max_tokens` cap, thinking off for direct DeepSeek); the analysts get
  `litellm_model(role)`, `litellm_kwargs(role)` (the same settings for LiteLLM) and
  `key_envs(role)` (the keys to pass into a container). `make models` prints what each role gets
  and which keys are missing. `LIMITS` caps each single call. To add a model: an entry in
  `models.yaml`, then use its key; a new provider also needs `PROVIDER_KEYS` and `build_model`.
- **Tracing.** The worker calls `setup_tracing()` on its first run; with
  `OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:8080/otlp-http` each ticket run is one trace in the
  shop's Jaeger (service `support-triage-agent`): a `ticket <id>` span, a `node <name>` span per
  node, and Pydantic AI's spans per model call.
- **Code index.** `deploy.sh` step 4 runs `python -m app.indexer index <service> <tag>`: ast-grep
  extracts symbols, error messages, flag reads and gRPC handlers from git at that commit, stored
  once per (service, commit), plus a service card (`indexer` role; `INDEX_CARDS=0` skips it).
  `export` writes the TSV files the offline codebox reads at `/index`. Usage in `__main__.py`.
- **Analysts.** HolmesGPT runs in its own image on the shop's network (it can't share this
  environment); mini-swe-agent is a dependency and runs each command in the codebox container.
  Both worked on the demo tickets in the phase 2 spike (`planning/Phase_2_Spike.md`); their graph
  nodes are phase 6.
- **Front pipeline.** `enrich` extracts a UTC window and ticket clues, then code checks IDs,
  service names and changes. `retrieve` runs hybrid help and ticket searches. The legacy `jev`
  stage now calls the configured `classification` LLM role; Jev is unavailable. Below 0.7 type
  confidence or an unknown service goes to a person. `layer1` verifies every cited ID and needs
  a relevant help section; `requests` drafts an acknowledgement. `make front-eval` runs these
  nodes on 20 fixed tickets and records `evals/phase4_baseline.json`.
- **Status.** Context, enrichment, retrieval, categorization, routing, Layer 1, request triage
  and approval are real, as are Layer 2's tools and the code index. The Layer 2 nodes, Layer 3,
  reply delivery and memory write-back remain stubs.

## The sandbox shop

The OpenTelemetry Astronomy Shop 3.1.0 fork lives at `../opentelemetry-demo` (or
`SANDBOX_DIR`). `make sandbox` reproducibly builds the good `v1.3.0` and the `v1.4.0`
version with four planted bugs among four harmless commits. `make scenario-N` reproduces a
ticket against the real shop, verifies its trace evidence, then sends it. The shop's `agent_ro`
login can read catalog data only; orders live in traces and logs. Bug locations, service
endpoints, trace fields and detailed operations are in [sandbox/README.md](sandbox/README.md).
Use the `planted-bugs` skill for changes to the fork's commits or overlay.

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
make analyst-images                # sandbox/holmes:0.42.0 and sandbox/codebox
make models                        # model per role, missing keys (ROLE_PROFILE=openai make models)
make index-help index-tickets      # fill retrieval_docs, re-embed only changed text
make index-code v=v1.4.0           # code index + service cards for every service at a tag
make retrieval-hits               # isolated retrieval benchmark on triage_retrieval_test
make front-eval                    # 20 live front pipeline cases (indexed DB + model key)
make lint fmt                      # ruff, line length 100
```

## Testing

| Suite | Command | Needs | What it covers |
| --- | --- | --- | --- |
| default | `make test` | nothing | units, retrieval rules and labels, the whole graph in memory, simulated scenarios, sandbox kit, indexer, codebox helpers |
| `db` | `make test-db` | `make db` | migrations up/down, queries, retrieval index/search, history role, NOTIFY, worker pause/resume |
| `sandbox` | `make test-sandbox` | `make sandbox` | the fork's tags, each planted diff, `git blame` to the planted commits, images, the code index at both tags |
| `shop` | `make test-shop` | `make shop-up` | every scenario live (~3 min), recorded deploys, metrics, logs, `agent_ro` |
| `llm` | `make test-llm` | keys in `.env.agent` | one real typed call per provider profile, skipped without its key (a fraction of a cent) |
| `spike` | `make test-spike` | shop, `make analyst-images`, keys | both analysts on demo tickets (~3 min, a few cents), codebox and history guardrails |

- Markers are excluded by default (`pyproject.toml` addopts). `db`, `shop` and `spike` refuse to run unless
  `DATABASE_URL` names a database ending in `_test`; the make targets set it.
- **Replacing a stub node:** write its test first against `TicketState` (the state it receives,
  the keys it returns), with the model or tool faked, then implement; `tests/test_graph.py`
  keeps the lanes working end to end. Put each outside call (model, HolmesGPT, Postgres,
  HTTP) behind one small function a test can replace, send progress with `emit(...)`, and give a
  node that calls out a `RetryPolicy` in `app/graph/build.py`.
- **Scenario logic** is tested against `FakeShop` in `tests/test_scenarios.py`: every scenario
  must pass with its bug and fail without it. Keep that pair when adding a scenario.
- **Characterization data** (real responses) goes in `tests/fixtures/`, trimmed and free of
  personal data.
- **Retrieval labels** are fixed in `evals/tickets.yaml`. A retrieval miss is addressed in the
  index, query or content; do not change a label to match the current ranking. The seed data is
  explicitly synthetic and includes near-miss issue families.
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
- The frontend has no search box and nothing calls `SearchProducts`; don't build on search.
- Every model in `config/models.yaml` needs `settings.max_tokens`: without it OpenRouter reserves
  65536 output tokens per request and returns 402 once the key's credit can't cover that. Direct
  DeepSeek also needs thinking off for Pydantic AI's typed output.
- HolmesGPT can't be `uv add`ed: 0.42.0 needs `openai<3`, and uv quietly resolves a 2025 release
  that downgrades Pydantic AI to 1.x. It lives in `holmes/Dockerfile`. Its default toolsets
  include a shell, internet access and kubectl; `holmes/toolsets.yaml` turns them off.
- DeepSeek's API rejects a tool argument that is an object with no listed properties. HolmesGPT's
  `elasticsearch_search` has four, so `elasticsearch/data` is off and our `logs` toolset
  (`holmes/search_logs.py`) takes the query as a JSON string; the image also sets
  `TOOL_SCHEMA_NO_PARAM_OBJECT_IF_NO_PARAMS`. Check a new toolset's schemas on DeepSeek first.
- HolmesGPT shell-quotes every tool parameter (`shlex.quote`) before rendering the command, so
  write `{{ query }}` in a command unquoted.
- Provider limits look like model bugs: Gemini's free tier allows 20 requests a day on
  `gemini-3.8-flash` (one spike run uses most of it; the error names
  `GenerateRequestsPerDayPerProjectPerModel-FreeTier`), and an OpenAI account without credit
  answers 429 `credit_balance_exhausted` with a valid key. Switch profile
  (`ROLE_PROFILE=... make test-spike`) rather than editing code.
- Agents' step limits count model turns, not tool calls (HolmesGPT made up to 62 calls in 15 turns);
  enforce time and call budgets in the node.
- In the codebox, mount the fork's `.git` at `/git` and set `GIT_DIR=/git/worktrees/shop@<tag>`,
  `GIT_WORK_TREE=/repo`: mounting it at its host path silently fails under Docker Desktop. Set
  `PREV_GIT_DIR` too, or git in `/prev` silently shows the deployed tag (`codebox/bin/git`).
- The codebox's awk is mawk: the index's error patterns are POSIX ERE, not `re.escape` output
  (it escapes spaces), and helpers pass arguments via `ENVIRON`, never `awk -v`.
- Whole-graph tests need `front_stage_fakes` (`tests/conftest.py`), or `enrich` calls a model.

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
