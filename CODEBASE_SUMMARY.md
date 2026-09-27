# Codebase summary

Status: September 27, 2026, through Phase 8 console implementation in local-outcome mode. This
describes working code in the repository; the build plan and later phases are separate. For
implementation rules,
read [AGENTS.md](AGENTS.md). For item-by-item progress, read
[planning/Build_Checklist.md](planning/Build_Checklist.md).

## What the project does

This is a support-ticket triage demo backed by a modified OpenTelemetry Astronomy Shop. A signed
Pylon-style webhook accepts tickets, a Postgres worker runs a checkpointed LangGraph pipeline,
and an API exposes the ticket queue, stage events, replay, approval, and simulator endpoints.
The working front pipeline enriches a ticket, searches help content and past tickets, classifies
its lane, and either prepares a cited product answer or triages a request. Technical tickets
get a duplicate check, then a Layer 2 investigation: HolmesGPT reads the shop's telemetry and
mini-swe-agent reads its code, in parallel, and a checked verdict says false positive, bug (with
file and commit), config incident, or inconclusive.

The graph currently runs:

```text
webhook → context → enrichment → retrieval + classification → route
                                                ├─ how-to → Layer 1 answer
                                                ├─ request → request triage
                                                ├─ tech issue → duplicates → brief → analysts
                                                │     → round 2 → verdict
                                                └─ uncertain → approval
confirmed bug or incident → local finding (optional Linear issue) → approval if required
feature request → optional roadmap handoff; billing/account → optional account-manager note
approved lanes (and linked duplicates) → Pylon reply or local log → memory → final outcome
```

`jev` remains the graph stage and event name for compatibility. Jev is unavailable, so that
stage calls the configured structured LLM classifier. It is not a Jev API integration.

## Implemented components

| Area | What works now | Main code |
| --- | --- | --- |
| Ticket intake | Raw-body HMAC-SHA256 check, ticket persistence, queued worker job, simulator that sends through the signed webhook | `app/api/main.py`, `app/tasks.py`, `scenarios/send_ticket.py` |
| Pipeline runtime | LangGraph edges and lane routing, per-stage retries, Postgres checkpoints, typed state, stage and tool events, pause/resume for human approval | `app/graph/`, `app/nodes/approve.py`, `app/events.py` |
| Ticket context | Tenant, recent tickets, recent deploys and flag changes, incidents, and service descriptions from the database/config | `app/db.py`, `app/nodes/context.py`, `config/ownership.yaml` |
| Enrichment | One typed model call extracts identifiers, UTC window, symptom, likely services and relevant changes; code drops unsupported IDs, service names and changes and bounds the window to seven days | `app/nodes/enrich.py` |
| Retrieval | Heading-based help sections and ticket memories are embedded incrementally; pgvector and Postgres full-text results are merged with reciprocal rank fusion; the node fetches five help sections and three similar tickets | `app/retrieval/`, `app/nodes/retrieve.py` |
| Classification | One typed LLM call estimates ticket type, service, severity and revenue blocking; code validates the service, gates type confidence below 0.7, and escalates high-confidence revenue blocking | `app/nodes/jev.py`, `app/graph/routes.py` |
| How-to answers | One model call uses retrieved help sections; code verifies citation IDs and requires a relevant help hit before the draft can be treated as confident | `app/nodes/layer1.py` |
| Requests | One model call identifies feature, billing or account requests; code builds a truthful acknowledgement without claiming a team handoff has already happened | `app/nodes/requests.py` |
| API and events | Queue/detail/pipeline endpoints, stored events, live SSE via Postgres LISTEN/NOTIFY, timed replay, approve endpoint, simulator templates and scorecard read endpoint | `app/api/`, `app/db.py`, `db/migrations/` |
| Model setup and tracing | Configurable DeepSeek, Gemini, OpenAI and OpenRouter profiles, per-role overrides/fallbacks/limits; optional OpenTelemetry ticket, stage and Pydantic AI spans | `config/models.yaml`, `config/roles.yaml`, `app/models_config.py`, `app/tracing.py` |
| Code index | ast-grep extracts service symbols, error messages, flag reads and gRPC handlers at each deployed commit; service cards and exported TSV files guide the offline codebase analyst | `app/indexer/`, `codebox/bin/` |
| Layer 2 | Duplicate linking, deterministic brief, parallel HolmesGPT and codebox analysts, checked findings, optional round 2, verdict rules, investigation memory and cost tracking | `app/nodes/duplicates.py`, `app/nodes/brief.py`, `app/nodes/findings.py`, `app/nodes/verdict.py`, `app/analysts/` |
| Layer 3 and delivery | Ownership-based Linear issues with checked evidence, optional links, priority and a durable event receipt; feature roadmap issues; Pylon customer replies and account-manager notes, with a logged fallback and retry receipts | `app/nodes/layer3.py`, `app/nodes/reply.py`, `app/integrations/` |
| Final result | A typed outcome event records the verdict or request, root cause, checked code excerpts, optional engineering issue, approval and reply delivery; the ticket detail endpoint exposes it | `app/code_snippets.py`, `app/outcome.py`, `app/tasks.py`, `app/api/main.py` |
| Triage Console | Next.js queue, compact backend-shaped pipeline, live/replay event timeline, typed tool output rendering, approval, simulator, scorecard, and light/dark mode | `web/app/`, `web/lib/`, `web/components/` |

The application uses Python 3.12, FastAPI, Pydantic AI, LangGraph, Procrastinate, SQLAlchemy,
psycopg, PostgreSQL 16 and pgvector. `app/models.py` defines the typed objects passed between
nodes; `app/tables.py` defines application-owned tables and `db/migrations/` migrates them.
Procrastinate and LangGraph manage their own tables in the same database. The investigation and
code index tables are used by Phase 6; eval results remain ahead of their workflow.

## Shop, tools, and evaluation data

- `sandbox/` reproducibly builds a fork of Astronomy Shop 3.1.0 beside this repo. `v1.3.0` is the
  good version; `v1.4.0` mixes four planted bugs with four ordinary changes. Versioned payment,
  quote, checkout and product-catalog images can be switched individually. See
  [sandbox/README.md](sandbox/README.md) for the bugs and setup.
- `scenarios/` contains seven demo tickets plus two spare bug scenarios. Bug scenarios place real
  shop orders, verify the expected trace evidence, record deploy/flag changes and then send
  the ticket. `config/ownership.yaml` is the single service vocabulary.
- The shop's `agent_ro` login can read only catalog data. HolmesGPT's separate `history_ro`
  login can read only deploy and flag history; its SQL takes model values as quoted parameters.
  The codebox mounts read-only shop worktrees and has no network access.
- `holmes/` holds the pinned HolmesGPT container and its restricted metrics, logs, traces,
  catalog and history tools. `codebox/` holds the offline mini-swe-agent environment and code
  helper commands. The graph runs both (`app/analysts/`), each with a time and call budget;
  every piece of evidence must point at a tool call that showed it. See
  [planning/Phase_2_Spike.md](planning/Phase_2_Spike.md) for the spike that chose them.
- Jaeger search can list successful traces for a service and operation. Condensed successful
  quote traces show item count and total, so the analyst can compare shipping amounts across
  versions without chasing unrelated payment errors.
- HolmesGPT's original tool-call IDs and the app's stage IDs are both validated against the
  actual calls. Accepted citations use the stage ID, so the console can link them to tool events.
- `knowledge/` contains 31 source-checked articles split into 62 indexed sections. `seed/`
  contains 200 labelled synthetic past tickets. `evals/tickets.yaml` fixes 20 ticket labels.
  The stored retrieval baseline found the answering section in the top five for 7/7 labelled
  how-to cases. A single DeepSeek Flash Phase 4 run scored 20/20 on type, service and effective
  lane, with 7/7 expected help citations; see
  [evals/phase4_baseline.json](evals/phase4_baseline.json). These are demo baselines, not a
  production reliability guarantee.

## Still incomplete

- Layer 2 is model behaviour on a small demo. An ordered `make test-layer2` run passed all five
  tickets in 11m57s: false positive, two correctly located bugs, config incident, and duplicate
  link. Earlier runs varied; Phase 9 will measure reliability and latency across repeats.
- Linear and Pylon are optional. Their HTTP contracts pass with fake external responses; the
  local `.env.agent` has no credentials, so real external delivery has not been validated. A
  no-Linear worker run finishes with a visible local outcome. The live SSE stream delivered a
  newly inserted event to `curl`, and approval/resume passed the database suite.
- The console has been checked against real live tickets, including a technical investigation,
  edited approval, replay, and local final outcome. The analysts persist terminal output; the
  API presents validated Prometheus data, logs, and unambiguous code/diffs as typed outputs
  without changing the stored event. A recorded run exercises series, table, log, and code
  renderers and a source-backed final diff in `/ticket/demo` without backend or model calls. The scorecard endpoint reads the database,
  but Phase 9 has not populated eval results or performed complete rehearsals.
- The Phase 0 Grafana dashboard review remains open. See the
  checklist for exact status; do not infer completion from a wired graph edge or a schema table.

## Run and verify

```bash
./start_local.sh                # local Postgres, API, worker and console; stop with ./stop_local.sh
./start_local.sh --follow       # labeled live logs; ./logs_local.sh reattaches later
./start_local.sh --observability # local logs in Grafana Explore; worker traces in Jaeger
make install db migrate          # dependencies and application database
make index-help index-tickets    # populate retrieval_docs
make api                         # FastAPI on localhost:8000
make worker                      # in a second terminal
make send t=1                    # send a demo ticket through intake
make models                      # show model assignments and missing keys
make test                        # unit and in-memory graph suite
make test-db                     # isolated test database suite
make retrieval-hits              # isolated retrieval benchmark
make front-eval                  # live 20-ticket front-pipeline eval; needs model key
make index-code v=v1.4.0        # code index and service cards at a shop tag
make test-layer2                # live tickets 3–7; requires the running shop and analyst images
cd web && pnpm install && pnpm dev # Triage Console on localhost:3000
```

For the sandbox and live shop tests, use [README.md](README.md) and
[sandbox/README.md](sandbox/README.md). `make test-shop` and `make test-spike` need the running
shop; `make test-llm` needs provider keys. Secrets belong in the ignored `.env.agent` file.
