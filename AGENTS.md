# AGENTS.md

Context and rules for coding agents working in this repo. Read it before changing anything, and
keep it true (see "Keeping this file current" at the end).

Last updated: Sep 28, 2026, console pipeline layout and DeepSeek balance.

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
                    /simulator/templates, /simulator/tickets, /evals/scorecard,
                    /providers/deepseek/balance
  api/schemas.py    request and response models
  graph/build.py    the StateGraph: NODES, edges, RETRY policies, pipeline_shape() for the console
  graph/state.py    TicketState (each node returns only the keys it changes)
  graph/routes.py   pick_lane, is_duplicate, pick_outcome: pure functions of the state
  graph/stream.py   emit() from inside nodes, staged() wrapper, run_graph() -> event sink
  graph/layout.yaml node positions for the console's left-to-right flowchart (used as is)
  nodes/*.py        one async run(state) per stage
  events.py         event models (discriminated union) the console renders
  code_snippets.py  checked codebox excerpts for engineering handoffs and final outcomes
  api/presentation.py pure typed-output hints at the API read boundary (stored raw output retained)
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
  analysts/         Layer 2's outside calls: holmes.py (HolmesGPT's container, budget enforced
                    from its stdout), codebox.py (mini-swe-agent in the codebox, in a thread)
  integrations/     Linear GraphQL issue creation, Pylon reply/internal-note HTTP adapters, and
                    the DeepSeek balance the console's sidebar shows
  outcome.py        final ticket result, emitted to SSE and exposed on ticket detail
config/             models.yaml (names, prices), roles.yaml (model per role), ownership.yaml,
                    ollama/Modelfile (the local qwen with a 32k context)
db/migrations/      Alembic; 0001 also creates the events NOTIFY trigger by hand
holmes/             HolmesGPT's image (Dockerfile), config.yaml, toolsets.yaml, condense_traces.py,
                    search_logs.py (the `logs` toolset's OpenSearch search), history_*.sql
codebox/            the codebase analyst's read-only container; bin/ has the helper commands
                    (read the exported index at /index, else ctags and rg) and a git wrapper
sandbox/            builds the shop fork: pin, overlay, patches, setup, images, compose wrapper
scenarios/          tickets.yaml (9 demo tickets), scenario.py, send_ticket.py, deploy.sh, flag.sh,
                    record.py (writes deploy and flag history)
tests/              pytest suites (see Testing); tests/fixtures/ holds real captured data
planning/           the plan, the build checklist, the phase 2 spike results, two HTML diagrams
                    (linked from the console's How it works page, served from here)
knowledge/          31 help articles / 62 sections with source map
seed/               200 labelled synthetic tickets and generator
evals/              20 fixed ticket labels, retrieval and Phase 4 model baselines
web/                Next.js Triage Console: generated API types, live/replay SSE, offline demo,
                    approval, simulator, scorecard, how it works (see web/README.md)
observability/      local file-log collector config for Grafana/OpenSearch (optional Compose profile)
.claude/skills/     project skills: sandbox-shop, planted-bugs (see "Skills and plugins")
```

## How it works (as built)

- **Intake.** The webhook checks `x-pylon-signature` (HMAC-SHA256 of the raw body with
  `PYLON_WEBHOOK_SECRET`), stores the ticket and defers `run_ticket`. It must answer fast.
- **Worker.** `run_ticket` runs the graph with the ticket ID as LangGraph's `thread_id`, so every
  step is checkpointed in Postgres. `approve` calls `interrupt()`; `POST .../approve` defers
  `resume_ticket`, which resumes with `Command(resume=decision)`. Both take a lock on the ticket ID.
- **Graph.** `context -> enrich -> (retrieve || jev) -> route`, then by lane: `layer1`,
  `requests`, or `duplicates -> brief -> (data_analyst || codebase_analyst) -> handoff`, then
  `handoff -> code_followup | data_followup -> handoff` until no question is left, then `verdict
  -> layer3 | approve`; approved lanes end `approve -> reply -> remember`, while a linked
  duplicate goes directly to `reply -> remember`. `findings` and `handoffs` are the state keys the
  analysts append to.
- **Nodes.** Plain async functions. Every node is wrapped by `staged()`, which emits
  running/done/failed events; a node may return `_summary` (one line for its flowchart node).
  Inside a node, `emit(...)` sends tool calls, model output and links to the console. Nodes that
  call outside services have a `RetryPolicy` in `build.py`.
- **Events.** Each emitted event is a row in `events`; a trigger NOTIFYs, and the SSE endpoint
  LISTENs on a plain psycopg connection. Stored events replay a run with no model calls.
- **Console.** `web/` reads FastAPI through OpenAPI-generated types. EventSource feeds TanStack
  Query; the investigation timeline renders observable events and API-presented typed outputs.
  `/ticket/demo` plays a captured run locally without backend requests.
  React Flow uses `/pipeline` positions and stage events. The scorecard is empty until Phase 9
  records eval results. See `web/README.md` for commands.
- **Database.** One Postgres 16 + pgvector (`make db`, localhost:5433, user/password/db
  `triage`). Our tables are SQLAlchemy models migrated by Alembic; Procrastinate and the LangGraph
  checkpointer own their tables, which Alembic ignores. `make migrate` also provisions
  `history_ro` from `HISTORY_DB_URL`, with SELECT on `deploys` and `flag_changes` only. HolmesGPT's
  history tool passes model values to `psql` variables in `holmes/history_*.sql`.
- **Retrieval.** `make index-help index-tickets` embeds 62 help sections and 200 synthetic ticket
  memories into `retrieval_docs` with local `BAAI/bge-small-en-v1.5` pinned at `5c38ec7c`;
  unchanged text is not re-embedded. Search filters the vector and full-text candidates, then
  fuses their ranks. `make retrieval-hits` scores it on a throwaway database
  (`evals/retrieval_baseline.json`).
- **Models: provider-agnostic.** No code names a provider. `config/roles.yaml` has one profile
  per provider (`deepseek` default, `gemini`, `openai`, `openrouter`), each role with a model and
  a same-provider fallback, plus `ollama` / `ollama-think`: local `qwen3.5:9b-32k` with thinking
  off / on, no key and no fallback (`make ollama-model` builds it). `ROLE_PROFILE` switches every role; `ROLE_MODELS="role=model,..."`
  moves single roles to any model in `config/models.yaml`. A model's `pydantic_ai` prefix decides
  its key (`PROVIDER_KEYS`). `pydantic_ai_model(role)` carries the model's `settings`; the
  analysts get `litellm_model`, `litellm_kwargs` (plus the model's `litellm_args`), `key_envs`,
  and `container_env` for HolmesGPT's container. A model's `time_scale` multiplies the analyst
  nodes' time budgets (`time_budget`), for slow local models. `LIMITS` caps each single call;
  `make models` shows roles and missing keys. A new provider needs `PROVIDER_KEYS` and `build_model`.
- **Tracing.** With `OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:8080/otlp-http` each ticket run
  is one trace in the shop's Jaeger (`support-triage-agent`): a span per ticket, node and model call.
- **Code index.** `deploy.sh` step 4 runs `python -m app.indexer index <service> <tag>`: ast-grep
  extracts symbols, error messages, flag reads and gRPC handlers from git at that commit, stored
  once per (service, commit), plus a service card (`indexer` role; `INDEX_CARDS=0` skips it).
  `export` writes the TSV files the offline codebox reads at `/index`. Usage in `__main__.py`.
- **Layer 2.** `duplicates` links a ticket to an open investigation with the same error
  signature (code), or to an open ticket that retrieval finds and a yes/no model call confirms
  by ID. `brief` is built in code (ticket as data, window, versions from the context's deploys or
  the fork's `versions.env`, past tickets as hypotheses). `data_analyst` runs HolmesGPT's
  container (`app/analysts/holmes.py`) and `codebase_analyst` runs mini-swe-agent in the codebox
  with the deployed commit's index at `/index` and the service card and change summary in its
  task (`app/analysts/codebox.py`); each streams its calls and stops at its time or call budget
  (constants in the node) to an inconclusive finding. `findings.convert` (role `findings`) turns
  an answer into Findings (it is told the customer's symptom, so `error_text` is the customer's
  error, not another shopper's) and `check_evidence` keeps only evidence a real call showed
  (evidence without a call ID, or with one that names no call, is tied to the first call that
  shows its ref, under the same check).
  **Handoff:** after round 1, `handoff` decides in code (`next_handoff`, no model call) whether one
  analyst needs the other: the data analyst's exact error goes to the code until it is located,
  if the code index places it in the suspected service (`origin`: the most specific matching
  error template; an error it can't place still goes);
  an analyst's own question (the `ASK DATA ANALYST:` / `ASK CODEBASE ANALYST:` line its prompt
  allows, read by `findings.request_in`) goes to the other; a code regression that production
  hasn't shown yet goes to the data analyst to confirm. `code_followup` (codebox, 90 s, 24
  commands) and `data_followup` (HolmesGPT, 150 s, 25 calls; asked for about 10) answer with the asker's checked
  findings in their task, as round N. Each question is asked once, each analyst answers at most
  two, at most three in all. `verdict` (role `verdict`) sees the handoffs and is then
  checked by `apply_rules`: two independent sources, a bug needs the file:line and commit the
  codebase analyst saw, an incident a flag change, a false positive the code, and neither may
  contradict the codebase analyst's latest judgment of the verdict's file:line. `remember` writes
  ticket memory and an `investigations` row. HolmesGPT's original tool-call IDs and the app's
  `hN` IDs both resolve to the same checked record; kept citations use `hN`. Analyst costs go to
  `tickets.cost_usd`.
- **Quote evidence.** The data analyst can search successful Jaeger traces by service, operation
  and time. Condensed successful quote traces include item count and total; the quote question
  compares these before and after the deploy. Generic trace search cannot supply the exact
  error handed to the codebase analyst.
- **Front pipeline.** `enrich` extracts a UTC window and ticket clues, then code checks IDs,
  service names and changes. `retrieve` runs hybrid help and ticket searches. The legacy `jev`
  stage calls the `classification` role (Jev is unavailable); below 0.7 type confidence or an
  unknown service goes to a person. `layer1` verifies every cited ID; `requests` drafts an
  acknowledgement. `make front-eval` scores them on 20 fixed tickets.
- **Layer 3 and delivery.** `layer3` maps the checked verdict service through `ownership.yaml`.
  With a Linear key it creates a team issue with checked code excerpts and emits its link;
  otherwise it records the finding locally and drafts a truthful reply. `reply` optionally files
  feature requests, posts Pylon replies and account-manager notes, or logs them when no account
  is configured. The intake
  payload may include `pylon_issue_id` and top-level `pylon_message_id`; Pylon lookup verifies
  the message is customer-visible. Successful `delivery` events are receipts for retries. The
  worker emits a final `outcome` event, also shown on `GET /tickets/{id}`. Approval depends on
  severity, revenue impact, confidence and draft quality, not Linear configuration.

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
./start_local.sh / ./stop_local.sh # local DB, API, worker, console; ownership-aware shutdown
./start_local.sh --follow          # labeled API/worker/web logs; Ctrl-C detaches the view
./start_local.sh --observability   # host logs in Grafana Explore, agent traces in Jaeger; needs shop
./logs_local.sh                    # attach to those logs after starting services
make api / make worker             # FastAPI on :8000 / Procrastinate worker (separate terminals)
make send t=4                      # send demo ticket 4 as-is
make sandbox sandbox-images shop-up  # build the fork, its images, start the shop
make scenario-4                    # reproduce ticket 4 and send it (needs make api)
make deploy s=quote v=v1.4.0       # switch a versioned service, recorded
make flag f=paymentFailure v=off   # change a flag, recorded (FLAG_RECORD=0 to skip recording)
make migration m="..." ; make migrate ; make check-migrations
make analyst-images                # sandbox/holmes:0.42.0 and sandbox/codebox
make models                        # model per role, missing keys (ROLE_PROFILE=openai make models)
make ollama-model                  # qwen3.5:9b-32k for ROLE_PROFILE=ollama / ollama-think
make index-help index-tickets      # fill retrieval_docs, re-embed only changed text
make index-code v=v1.4.0           # code index + service cards for every service at a tag
make retrieval-hits               # isolated retrieval benchmark on triage_retrieval_test
make front-eval                    # 20 live front pipeline cases (indexed DB + model key)
make lint fmt                      # ruff check + format check / fix, line length 100
cd web && pnpm install && pnpm dev # console on :3000; see web/README.md for checks
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
| `layer2` | `make test-layer2` | shop, `make sandbox-images analyst-images`, keys | tickets 3-7 reproduced and run through the whole graph (~25 min) |
| `handoff` | `make test-handoff` | shop, `make analyst-images`, a DeepSeek key (`PROFILE=ollama`: `make ollama-model`) | tickets 4, 8, 9 through the whole graph; both handoff directions; results in `evals/handoff_<profile>.json` (~15 min; hours on local qwen) |

- Markers are excluded by default (`pyproject.toml` addopts). `db`, `shop`, `spike`, `layer2` and `handoff` refuse to run unless
  `DATABASE_URL` names a database ending in `_test`; the make targets set it.
- **Changing a node:** write its test first against `TicketState` (the state it receives,
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

- The shop's own gotchas (its `.env`, Jaeger's memory, `flag.sh` and the fork, traces arriving in
  pieces, UTC, no search) are in [sandbox/README.md](sandbox/README.md#gotchas).
- `start_local.sh` needs `.env.agent` and runs migrations. It writes owned process IDs and logs
  under ignored `.local/`; `stop_local.sh` leaves manually started processes, existing Postgres,
  and the sandbox shop running. `logs_local.sh` follows the three host-service logs with labels;
  the `--follow` start option runs the same viewer after services are ready. With the shop up,
  `--observability` starts `local-log-collector` to ship those files to the shop's OpenSearch;
  Grafana Explore reads logs and Jaeger traces. The collector's offset volume survives stops.
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
  enforce time and call budgets in the node. At `--max-steps` HolmesGPT returns its last raw
  message (DeepSeek's `DSML` tool-call markup), not an answer, so the node stops it instead.
- HolmesGPT's stdout reports a tool's name when it starts, but its command and output are only
  available in the final JSON result. Running `tool_call` events therefore have `args: {}`;
  the console replaces each with its completed event by call ID once the analyst finishes.
- The API shapes recognized analyst terminal results for display without rewriting `events` or
  evidence records. `/ticket/demo` uses a sanitized stored fixture and local simulated approval;
  see `web/README.md`. Live view presents typed enrichment, findings, and verdict data as
  readable summaries and keeps full payloads in Raw. The same compact visual treatment is used
  across the queue, preview, simulator, and scorecard. The queue's New ticket dialog uses the
  simulator intake endpoint and opens the resulting run. A real replay still comes from FastAPI SSE.
- An analyst's "exact error" can be its own tool's error (a bad OpenSearch query): only a
  successful trace or log call may supply it (`ERROR_TOOLS` in `findings.py`), and a failed tool
  must exit non-zero so HolmesGPT marks it failed.
- HolmesGPT's answer can cite its native `call_...` IDs even when the findings prompt numbers
  calls `h1`, `h2`, etc. Preserve and validate both IDs, then normalize citations to `hN`; otherwise
  every valid evidence item can be dropped and the verdict becomes inconclusive.
- In the codebox, mount the fork's `.git` at `/git` and set `GIT_DIR=/git/worktrees/shop@<tag>`,
  `GIT_WORK_TREE=/repo`: mounting it at its host path silently fails under Docker Desktop. Set
  `PREV_GIT_DIR` too, or git in `/prev` silently shows the deployed tag (`codebox/bin/git`).
  The codebox runs as `analyst`, so `/index` must be world-readable (`export.write` sees to it).
- `host.docker.internal` exists only on Docker Desktop. A container that reaches the agent's
  Postgres (HolmesGPT's `history`) needs `--add-host host.docker.internal:host-gateway` on Linux.
- The codebox's awk is mawk: the index's error patterns are POSIX ERE, not `re.escape` output
  (it escapes spaces), and helpers pass arguments via `ENVIRON`, never `awk -v`.
- Ollama serves every model with a 4096-token context unless told otherwise, and silently cuts
  longer prompts: the local profiles use `qwen3.5:9b-32k` (`config/ollama/Modelfile`). Turning
  qwen's thinking off takes a different spelling per client: `extra_body.reasoning_effort: none`
  for Pydantic AI (Ollama's `/v1`, where `think: false` is ignored), a top-level
  `reasoning_effort` for LiteLLM's `ollama_chat` (in `extra_body` it is ignored), and
  `REASONING_EFFORT=none` for HolmesGPT. On a 16 GB Mac with the shop up it runs at about 5
  output tokens/s (swap), hence `time_scale`.
- Qwen 9B leaves `call_id` off evidence, and DeepSeek's findings calls shorten HolmesGPT's native
  IDs (`call_02_ET_2z5u...`, where `call_NN` is only a per-turn counter) to `call_07`;
  `check_evidence` ties such evidence to the call that shows its ref rather than dropping it.
- With several scenarios in one window, the shop carries other tickets' errors (payment's expiry
  bug during the cart ticket). The handoff sends an error to the code only if the code index
  places it in the suspected service, and a code judgment only counts for the file:line it read.
- Whole-graph tests need `front_stage_fakes` (`tests/conftest.py`, which pulls in
  `layer2_fakes`), or `enrich` calls a model and Layer 2 starts real containers.

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
