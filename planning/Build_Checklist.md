# Build checklist

What's built and what isn't, phase by phase, against `Agent_Architecture_And_Build_Plan.md`.
Tick an item when it works and is tested the way the plan's "How it's tested" says; tick a
phase's "Done when" only when that whole criterion has been seen working.

Last updated Sep 26, 2026, after phase 2. Tests, all passing:

| Suite | Command | Needs | Tests |
| --- | --- | --- | --- |
| Units, graph in memory, scenario logic, sandbox kit, tracing, model config | `make test` | nothing | 86 |
| Database | `make test-db` | `make db` | 6 |
| The fork: tags, planted bugs, overlay, images | `make test-sandbox` | `make sandbox` | 18 |
| The running shop: every scenario, read-only role, metrics, logs | `make test-shop` | `make shop-up` | 15 |
| Real model calls on each provider profile | `make test-llm` | keys in `.env.agent` | 4 |
| Both analysts on demo tickets, codebox guardrails | `make test-spike` | shop, `make analyst-images`, keys | 4 |

## Phase 0: Sandbox (days 1–2)

- [x] Fork pinned to upstream release 3.1.0 (`dedc017`), rebuilt reproducibly by `make sandbox`
- [x] Four bugs planted among four harmless commits; `v1.3.0` and `v1.4.0` tagged, no upstream tags
- [x] Search bug swapped for the catalog-listing bug (nothing calls product search)
- [x] Versioned images for payment, quote, checkout and product-catalog (`make sandbox-images`)
- [x] `compose.versions.yaml`; every other service pinned to the 3.1.0 release images
- [x] Minimal mode with versioned services (`make shop-up`)
- [x] `deploy.sh` and `flag.sh` record deploys (with commit titles) and flag changes
- [x] Read-only `agent_ro` role: catalog only, read-only transactions, 5 s timeout
- [x] Tenant seed data (`figma-merch`, shoppers `figma-shopper-01` to `-20`) and `ownership.yaml`
- [x] Scenario scripts for tickets 1–7 and the two spare bugs, each checked in Jaeger (`make scenario-*`)
- [x] The plan's "still to confirm" list checked against the real shop
- [x] Tests: the fork's planted bugs (`make test-sandbox`), every scenario live (`make test-shop`), and the scenario logic against a simulated shop with and without each bug (`make test`)
- [ ] Look at each scenario in Grafana by hand (Prometheus queries are verified; dashboards aren't)
- [ ] Optional: a Grafana annotation for each deploy
- [ ] **Done when:** every scenario reproduces by hand and shows up in Jaeger and Grafana
  (Jaeger: yes, all six; Grafana: not yet looked at)

## Phase 1: Intake and events (day 3)

- [x] FastAPI webhook with HMAC check; a bad signature is rejected
- [x] `send_ticket.py`
- [x] Postgres schema: tickets, events, verdicts (and the later tables), Alembic migrations
- [x] Event models
- [x] Procrastinate tasks: `run_ticket`, `resume_ticket`
- [x] Context fetchers: tenant, recent tickets, deploys, flag changes, incidents (last 24 h)
- [x] **Done when:** a sent ticket is stored and queued with its context bundle

## Phase 2: Graph skeleton, model layer, open-source spike (day 4)

- [x] LangGraph `StateGraph`: every node as a stub, all edges, per-node retry policies
- [x] Postgres checkpointer; streaming into the `events` table with NOTIFY
- [x] `roles.yaml` to Pydantic AI and LiteLLM names, fallback models, `UsageLimits`
- [x] OpenTelemetry export: a span per ticket run and per node, in the shop's Jaeger (`make test`)
- [x] One Pydantic AI call on two providers by changing only `ROLE_PROFILE` (`make test-llm`);
  per-model settings in `models.yaml` fix DeepSeek's thinking mode and OpenRouter's token reservation
- [x] Provider-agnostic models: a profile per provider (`deepseek` default, `gemini`, `openai`,
  `openrouter`), `ROLE_MODELS` for single roles, the analysts' keys and settings from the config,
  `make models` (`make test`, `make test-llm`)
- [x] Every role on DeepSeek direct, the data analyst included: HolmesGPT's log search replaced by
  our `logs` toolset, which DeepSeek's API accepts (`make test`, `make test-spike`)
- [ ] Run `make test-llm` and `make test-spike` on `openai` (the account has no credit yet) and on
  `gemini` (the free tier's 20 requests a day on `gemini-3.8-flash` ran out mid-spike)
- [x] HolmesGPT 0.42.0 pinned in its own image (it can't share the app's environment); run on ticket 4
- [x] mini-swe-agent 2.4.6 pinned; run on tickets 4 and 3 in the read-only codebox
- [x] A stub approval pauses and resumes
- [x] The spike repeatable: `make test-spike`; findings in `planning/Phase_2_Spike.md`
- [x] **Done when:** a ticket runs end to end through the stub graph, a stub approval pauses and
  resumes, a Pydantic AI call works on two providers by config only, and both open-source agents
  run once

## Phase 3: Retrieval, and the eval dataset (days 5–6)

- [ ] 20-ticket eval dataset, labels only: type, service, verdict, team, answering help section, past tickets to find
- [ ] About 30 help-center articles, every rule checked against the code (no "product search tips": the storefront has no search)
- [ ] About 200 labelled seed tickets with near-misses (`seed/past_tickets.jsonl`)
- [ ] Tests first: section chunking, content hashing, reciprocal rank fusion, filters
- [ ] `EmbeddingClient` with the local bge-small model
- [ ] Indexing help sections and tickets into `retrieval_docs`
- [ ] Hybrid search: pgvector + full text, merged by reciprocal rank fusion
- [ ] Hit-rate script over the eval dataset's labels
- [ ] **Done when:** hit rates are measured for both indexes, and ticket 1's answering section is in the top 5

## Phase 4: Front-of-pipeline nodes (day 7)

- [ ] Tests first: enrichment validation, the confidence gate, routing, Layer 1 citation checks
- [ ] Context node on real data
- [ ] Enrichment with validation (ticket times are the customer's local time; the window must allow for it)
- [ ] Describe each service by what it does in the categorization prompts: models read "expired at
  checkout" as a checkout problem, not payment (spike)
- [ ] Retrieve node
- [ ] Jev with the LLM fallback below 0.7
- [ ] Layer 1 with citation checks
- [ ] Request triage
- [ ] **Done when:** all seven tickets get valid enrichment and the right lane, tickets 1 and 2
  get correct, cited replies, and the eval dataset's type, service and lane labels give a first score

## Phase 5: Layer 2 tools and indexer (days 8–9)

- [x] HolmesGPT toolsets load and connect: `prometheus/metrics`, `database/sql`, `jaeger`, `history`,
  `logs` (ours, replacing `elasticsearch/data`); its default shell, internet and kubectl toolsets are off (spike)
- [x] `search_logs.py`: only `_search` on `otel-logs-*`, at most 50 hits, one line each, tested on a
  saved OpenSearch response
- [ ] Give `/prev` in the codebox its own git environment (`GIT_DIR` currently points at the deployed tag)
- [ ] `condense_traces.py` keeps the shop's real attribute names (it looks for `app.user.id` and
  `app.payment.card_type`; the shop sends `user.id` and `demo.payment.card_type`)
- [ ] Characterization tests for `condense_traces.py` on saved Jaeger responses
- [x] Codebox container with read-only worktrees and no network; writes and network refused (`make test-spike`)
- [ ] Helper commands: `repo-map`, `lookup-error`, `find-symbol`, `rpc-handler` (drafted, not yet run)
- [ ] Indexer: universal-ctags, ast-grep, `protoc`, service cards; run from `deploy.sh` step 4
- [ ] **Done when:** each toolset and helper command returns condensed real data, a write attempt
  is refused, both versions are indexed, and those results are pinned by tests

## Phase 6: Layer 2 nodes (days 10–11)

- [ ] Tests first: evidence checks, error-signature normalization, round 2's trigger, the timeout path
- [ ] Duplicate check: exact signature, retrieval over open tickets, Jev confirmation
- [ ] Brief
- [ ] Data analyst node: runs HolmesGPT's container, enforces the 90 s timeout and tool-call budget
  itself (its step limit counts model turns: the spike made 36 calls in 15 turns), streams its tool calls
- [ ] Codebase analyst node (mini-swe-agent) with timeout, streaming its commands
- [ ] Findings conversion with evidence checks (HolmesGPT guesses about code it never read; drop those)
- [ ] Cost per analyst run from tokens and `models.yaml` prices (LiteLLM has no price for deepseek-flash)
- [ ] Round 2
- [ ] Verdict
- [ ] Write-back to ticket memory and `investigations`
- [ ] **Done when:** ticket 3 is a false positive, tickets 4 and 5 are bugs with the right file
  and commit, ticket 6 is a config incident, and ticket 7 links to ticket 4's open issue

## Phase 7: Layer 3 and console API (day 12)

- [x] Approval node with `interrupt()`, resumed by `POST /tickets/{id}/approve`
- [x] Console endpoints: queue, ticket, `/pipeline` from `get_graph()`, stored events, SSE stream
  with replay, approve, simulator, scorecard
- [ ] Layer 3: ownership lookup and Linear issue creation
- [ ] Customer acknowledgement and reply sending (Pylon, or logged without an account)
- [ ] **Done when:** a bug ticket produces a Linear issue, an approval resumes the paused run, and
  `curl` on the stream shows a live run's events arriving

## Phase 8: Triage Console (days 13–15)

- [ ] Scaffold, shadcn, AI Elements, React Flow UI, generated API client, sidebar shell
- [ ] `/tickets` queue
- [ ] `/ticket/[id]`: pipeline, stage inspector, streaming hook, output view
- [ ] Approve flow and replay
- [ ] `/simulator` and `/scorecard`
- [ ] Dark mode
- [ ] **Done when:** a live ticket lights up the flowchart stage by stage, every tool call shows
  its code, command or chart, a reply can be approved, and a past run replays

## Phase 9: Evals, model choice, rehearsal (days 16–17)

- [ ] The eval dataset as a Pydantic Evals run, per model and role, with and without retrieval
- [ ] Scorecard results in `eval_results`
- [ ] Models chosen per role
- [ ] Prompt fixes from the failures
- [ ] Two full rehearsals and a backup video
- [ ] **Done when:** at least 18 of 20 tickets are routed correctly on the chosen models, the
  scorecard is ready to show, and a run-through stays under 10 minutes
