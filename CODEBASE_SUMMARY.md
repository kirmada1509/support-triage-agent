# Codebase summary

Status: September 26, 2026, through Phase 4. This describes working code in the repository;
the build plan and later-phase stubs are called out separately below. For implementation rules,
read [AGENTS.md](AGENTS.md). For item-by-item progress, read
[planning/Build_Checklist.md](planning/Build_Checklist.md).

## What the project does

This is a support-ticket triage demo backed by a modified OpenTelemetry Astronomy Shop. A signed
Pylon-style webhook accepts tickets, a Postgres worker runs a checkpointed LangGraph pipeline,
and an API exposes the ticket queue, stage events, replay, approval, and simulator endpoints.
The working front pipeline enriches a ticket, searches help content and past tickets, classifies
its lane, and either prepares a cited product answer or triages a request. Technical tickets
enter a wired investigation lane whose graph nodes still use placeholder findings and verdicts.

The graph currently runs:

```text
webhook → context → enrichment → retrieval + classification → route
                                                ├─ how-to → Layer 1 answer
                                                ├─ request → request triage
                                                ├─ tech issue → duplicate/analyst/verdict stubs
                                                └─ uncertain → approval
all lanes → approval → reply stub → memory stub
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

The application uses Python 3.12, FastAPI, Pydantic AI, LangGraph, Procrastinate, SQLAlchemy,
psycopg, PostgreSQL 16 and pgvector. `app/models.py` defines the typed objects passed between
nodes; `app/tables.py` defines application-owned tables and `db/migrations/` migrates them.
Procrastinate and LangGraph manage their own tables in the same database. Some schema tables,
including investigations, code index and eval results, exist ahead of their workflows.

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
  helper commands. Both analysts produced useful answers in the Phase 2 spike, but the graph
  does not invoke them yet. See [planning/Phase_2_Spike.md](planning/Phase_2_Spike.md).
- `knowledge/` contains 31 source-checked articles split into 62 indexed sections. `seed/`
  contains 200 labelled synthetic past tickets. `evals/tickets.yaml` fixes 20 ticket labels.
  The stored retrieval baseline found the answering section in the top five for 7/7 labelled
  how-to cases. A single DeepSeek Flash Phase 4 run scored 20/20 on type, service and effective
  lane, with 7/7 expected help citations; see
  [evals/phase4_baseline.json](evals/phase4_baseline.json). These are demo baselines, not a
  production reliability guarantee.

## Still incomplete

- The Phase 5 code index is built (all five services at both tags, stored per commit, exported
  to the codebox's helper commands), but service cards have not yet been written by a real model
  and the spike has not been rerun with the index mounted. The restricted analyst environments
  work as standalone spikes, not graph investigations.
- `duplicates`, `brief`, both analyst nodes, `round2`, `verdict` and `remember` are Phase 6
  placeholders. A technical ticket cannot yet get a trustworthy root cause, duplicate link or
  memory write-back from the graph.
- `layer3` returns a fake Linear issue ID. `reply` does not send a Pylon message. The approval
  API works, but downstream engineering/customer delivery is Phase 7 work.
- `web/` is a placeholder; the Next.js Triage Console is Phase 8 work. The API and event types
  it will consume already exist. The scorecard endpoint reads the database, but Phase 9 has not
  populated full eval results or performed complete rehearsals.
- The Phase 0 Grafana dashboard review and several Phase 5 tool checks remain open. See the
  checklist for exact status; do not infer completion from a wired graph edge or a schema table.

## Run and verify

```bash
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
```

For the sandbox and live shop tests, use [README.md](README.md) and
[sandbox/README.md](sandbox/README.md). `make test-shop` and `make test-spike` need the running
shop; `make test-llm` needs provider keys. Secrets belong in the ignored `.env.agent` file.
