# Support Triage Agent

An AI first pass for B2B support tickets. A ticket arrives through a Pylon-style signed webhook,
is enriched and categorized by a structured LLM call, and takes one of three lanes: a cited
Layer 1 answer, request triage, or, for tech issues, a Layer 2 investigation. There a data
analyst (HolmesGPT, reading production traces, metrics, logs, deploys and flags) and a read-only
codebase analyst (mini-swe-agent, reading the deployed code and its git history) work as a team
against a real microservice shop: they start in parallel, then hand each other questions. False
positives are answered directly; real bugs go to the owning engineering team (Layer 3). A person
approves anything uncertain, and a live Triage Console shows every stage.

**Try it:** https://support-triage-agent-delta.vercel.app. Open a recorded investigation from
the queue, play the offline demo at
[/ticket/demo](https://support-triage-agent-delta.vercel.app/ticket/demo), or read
[How it works](https://support-triage-agent-delta.vercel.app/how-it-works). **New ticket** starts
a real run, which spends DeepSeek credit (shown in the sidebar).

The design is in `planning/Agent_Architecture_And_Build_Plan.md`, with two architecture
diagrams alongside it. Coding agents: start with [AGENTS.md](AGENTS.md) (context, rules, and the
playbooks in `.claude/skills/`).

## Status

Phases 0–8 are built, with a few follow-ups open (checking the scenarios in Grafana by hand,
Layer 2 run-to-run variance); [planning/Build_Checklist.md](planning/Build_Checklist.md) tracks
each item. Phase 9 (evals and model choice) is next, so the console's scorecard is still empty.

- **Front pipeline:** signed intake, a checkpointed LangGraph, enrichment, hybrid retrieval over
  31 help articles and 200 labelled synthetic past tickets, LLM categorization with a confidence
  gate, cited Layer 1 answers and request triage. Jev is unavailable; its `jev` stage name stays
  for stored events.
- **Layer 2:** duplicate linking, a brief built in code, both analysts in parallel, then a
  two-way handoff decided in code: the data analyst's exact error goes to the codebase analyst,
  either analyst can ask the other one question, and a code regression production hasn't shown
  yet goes back to the data analyst. At most three questions per ticket. The verdict is one model
  call whose claims are checked in code against the evidence both analysts really saw. Live on
  DeepSeek, the handoff tickets (4, 8, 9) all end at their planted file and commit
  ([evals/handoff_deepseek.json](evals/handoff_deepseek.json)).
- **Layer 3 and delivery:** Linear issues and Pylon replies when their keys are set; otherwise
  the finding and reply are recorded locally. Every ticket ends with a final outcome.
- **Triage Console:** queue with preview, live and replayed investigations on a left-to-right
  pipeline, approvals, simulator, scorecard, How it works, and the DeepSeek credit left.
- **Hosted:** the console on Vercel; the API, Postgres, worker and sandbox shop on a VPS (see
  [Deployment](#deployment)).

## Models

No code names a provider. `config/roles.yaml` gives each role (enrichment, classification,
findings, verdict, the analysts, ...) a model and a same-provider fallback, per profile:
`deepseek` (the default), `gemini`, `openai`, `openrouter`, and `ollama` / `ollama-think` for a
local `qwen3.5:9b` with thinking off or on (`make ollama-model`; slow on a laptop).
`ROLE_PROFILE=openai` switches every role, `ROLE_MODELS="verdict=gpt-5.4,..."` moves single
roles, and `make models` shows the choice and any missing keys. Keys go in `.env.agent`.

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
make index-help index-tickets      # the retrieval index (see Retrieval)
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

A tech ticket only gets a real Layer 2 investigation with the sandbox shop running and the
analysts' images built (see [Sandbox](#sandbox)); `make scenario-N` reproduces demo ticket N in
the shop and sends it. API docs are at http://localhost:8000/docs.

## Tests

| Command | Needs | Covers |
| --- | --- | --- |
| `make test` | nothing | units, the whole graph in memory, scenario logic against a simulated shop, the handoff rules (294 tests) |
| `make test-db` | `make db` | migrations, queries, retrieval, NOTIFY, worker pause/resume, on a throwaway `triage_test` database |
| `make test-sandbox` / `make test-shop` | the fork / the running shop | the planted bugs and every scenario live |
| `make test-llm` | keys | one real typed call per provider profile |
| `make test-spike`, `make test-layer2`, `make test-handoff` | shop, analyst images, keys | the analysts, tickets 3–7, and the handoff tickets 4, 8, 9 through the whole graph |

`make lint` runs ruff; the console has `pnpm typecheck`, `pnpm lint` and `pnpm build`. The
[Testing section of AGENTS.md](AGENTS.md#testing) has the details.

## Deployment

| Part | Where | Address |
| --- | --- | --- |
| Console | Vercel (prebuilt from this machine) | https://support-triage-agent-delta.vercel.app |
| API, Postgres, Caddy (HTTPS) | VPS, Docker Compose | https://support-triage-agent.duckdns.org |
| Worker, sandbox shop, analyst images | same VPS (the worker as a systemd service) | not public |

The worker, the shop and the analysts share one Docker host because the analysts start their own
containers and mount the fork by host path. Only SSH, 80 and 443 are public. After a change,
commit it, then run `./deploy/vps/deploy.sh` (it deploys `HEAD`) and, for the console,
`./deploy/vercel.sh`. First-time setup, secrets and logs: [deploy/README.md](deploy/README.md).
The hosted API has no login: anyone with the console can create tickets and approve replies.

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
                  simulator, scorecard, DeepSeek balance
  graph/          LangGraph: state, build (nodes, edges, retries), routes, stream, layout.yaml
  nodes/          one async function per pipeline stage (handoff.py: the analysts' questions)
  analysts/       HolmesGPT's container and mini-swe-agent in the codebox, with budgets
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
knowledge/ seed/ evals/   help, synthetic memory, fixed labels, Phase 4 and handoff results
planning/         the plan, the build checklist, two architecture diagrams (served by the console)
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
make analyst-images   # sandbox/holmes:0.42.0 and sandbox/codebox
make scenario-4       # reproduce ticket 4 in the shop, check it in Jaeger, send the ticket
```

The nine demo tickets in `scenarios/tickets.yaml` cover a Layer 1 answer, a feature request, a
false positive, the four planted bugs (tickets 4, 5, 8, 9), a flag incident, and a vague repeat
that should be linked as a duplicate.

`make deploy s=payment v=v1.4.0` switches a service's version and records the deploy;
`make flag f=paymentFailure v=25%` changes a flag and records it. Both write to this repo's
Postgres, which is where the agent reads deploy and flag history.
