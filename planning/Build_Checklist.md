# Build checklist

What's built and what isn't, phase by phase, against `Agent_Architecture_And_Build_Plan.md`.
Tick an item when it works and is tested the way the plan's "How it's tested" says; tick a
phase's "Done when" only when that whole criterion has been seen working.

Last updated Sep 26, 2026: phase 5 done (every suite run on Linux Docker; `test-llm`'s `openai` case still has no credit). Suite inventory (provider calls depend on credit):

| Suite | Command | Needs | Tests |
| --- | --- | --- | --- |
| Units, graph in memory, front pipeline, scenario logic, sandbox kit, tracing, model config, retrieval, indexer, codebox helpers, trace condensing | `make test` | nothing | 159 |
| Database | `make test-db` | `make db` | 10 |
| The fork: tags, planted bugs, overlay, images, the code index at both tags | `make test-sandbox` | `make sandbox` | 27 |
| The running shop: every scenario, read-only role, metrics, logs | `make test-shop` | `make shop-up` | 15 |
| Real model calls on each provider profile, a real payment service card | `make test-llm` | keys in `.env.agent` | 5 |
| Both analysts on demo tickets, codebox and history guardrails | `make test-spike` | shop, `make analyst-images`, keys | 6 |

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
- [ ] Run `make test-llm` and `make test-spike` on `openai` (the account still had no credit on Sep 26) and on
  `gemini` (the free tier's 20 requests a day on `gemini-3.8-flash` ran out mid-spike)
- [x] HolmesGPT 0.42.0 pinned in its own image (it can't share the app's environment); run on ticket 4
- [x] mini-swe-agent 2.4.6 pinned; run on tickets 4 and 3 in the read-only codebox
- [x] A stub approval pauses and resumes
- [x] The spike repeatable: `make test-spike`; findings in `planning/Phase_2_Spike.md`
- [x] **Done when:** a ticket runs end to end through the stub graph, a stub approval pauses and
  resumes, a Pydantic AI call works on two providers by config only, and both open-source agents
  run once

## Phase 3: Retrieval, and the eval dataset (days 5–6)

- [x] 20-ticket eval dataset, labels only: type, service, verdict, team, answering help section, past tickets to find
- [x] 31 help-center articles / 62 sections, each checked against shop source listed in `knowledge/sources.yaml`; no search-box advice
- [x] 200 labelled synthetic past tickets with near-misses (`seed/past_tickets.jsonl`)
- [x] Tests first: section chunking, content hashing, reciprocal rank fusion, filters (`make test`)
- [x] `EmbeddingClient` with local `BAAI/bge-small-en-v1.5` (384 dimensions)
- [x] Incremental indexing of help sections and tickets into `retrieval_docs` (`make test-db`, `make index-help index-tickets`)
- [x] Hybrid search: pgvector + full text, merged by reciprocal rank fusion with kind, status and service filters
- [x] Hit-rate script over fixed eval labels (`make retrieval-hits`): help 7/7 top 5, ticket memory
  13/18 exact ID top 3 and 17/18 same synthetic issue family top 3; ticket 1's answer ranked first
- [x] **Done when:** hit rates measured for both indexes and ticket 1's answer in top 5

## Phase 4: Front-of-pipeline nodes (day 7)

- [x] Tests first: enrichment validation, confidence gate, routing and Layer 1 citation checks
- [x] Context node on real data (`make test-db`, phase 1)
- [x] Enrichment with identifier, change, service and UTC window validation; unknown customer
  timezone gets a broad bounded window
- [x] Service descriptions live in `ownership.yaml`; prompts distinguish card declines from
  checkout features such as Apple Pay
- [x] Retrieve node: top five help sections and top three similar tickets from hybrid search
- [x] Jev unavailable: structured LLM classification in the existing `jev` stage, with a 0.7
  confidence gate and severity escalation for revenue blocking
- [x] Layer 1 with code-checked citation IDs and a minimum help hit
- [x] Request triage with a truthful acknowledgement before any team handoff exists
- [x] Live `make front-eval` baseline on 20 fixed tickets with DeepSeek Flash: 20/20 type,
  service and effective lane; all 20 valid windows and 7/7 expected help citations. Tickets 1–7
  took their expected lanes; ticket 2 produced an Apple Pay feature acknowledgement
- [x] **Done when:** all seven tickets get valid enrichment and the right lane, ticket 1 gets a
  correct cited answer, ticket 2 gets a correct acknowledgement, and type, service and lane labels
  have a first score

## Phase 5: Layer 2 tools and indexer (days 8–9)

- [x] HolmesGPT toolsets load and connect: `prometheus/metrics`, `database/sql`, `jaeger`, `history`,
  `logs` (ours, replacing `elasticsearch/data`); its default shell, internet and kubectl toolsets are off (spike)
- [x] `history` uses a dedicated `history_ro` login with SELECT only on deploys and flag changes;
  model values are passed to `psql` as quoted variables, with hostile-input checks (`make test-db`,
  `make test-spike`)
- [x] `search_logs.py`: only `_search` on `otel-logs-*`, at most 50 hits, one line each, tested on a
  saved OpenSearch response
- [x] Give `/prev` in the codebox its own git environment: `codebox/bin/git` switches to
  `PREV_GIT_DIR` in `/prev` or with `-C /prev` (tested on real worktrees and in the container,
  `make test-spike`)
- [x] `condense_traces.py` keeps the shop's real attribute names (`user.id`, every `demo.*`)
- [x] Characterization tests for `condense_traces.py` on saved Jaeger responses
- [x] Codebox container with read-only worktrees and no network; writes and network refused (`make test-spike`)
- [x] Helper commands `repo-map`, `lookup-error`, `find-symbol`, `rpc-handler`, `flag-reads` read
  the exported index at `/index` with mawk (the codebox's awk), fall back to ctags and rg; tested
  on a fixture export and on the real v1.4.0 index (`lookup-error` on the customer's quoted
  expiry message gives `charge.js:89` only)
- [x] Indexer (plan changed: ast-grep for everything, the `.proto` for method names, no ctags or
  `protoc`): symbols, error messages, flag reads, gRPC handlers for JS, Go, PHP and C#; stored per
  (service, commit), exported as TSV; `python -m app.indexer`, `make index-code v=...`,
  `deploy.sh` step 4. All five services indexed at both tags, pinned in `make test-sandbox`
  and round-tripped through Postgres (`make test-db`)
- [x] Service cards from a real model (`indexer` role, DeepSeek V4 Pro): `make index-code` at
  both tags wrote all five; the payment card states Visa and Mastercard only, pinned in `make test-llm`
- [x] `make test-spike` rerun with the index mounted at `/index` and `PREV_GIT_DIR` (6/6). It found
  two bugs, fixed test first: the export was unreadable by the codebox's `analyst` user (mkdtemp is
  0700), and `host.docker.internal` only exists on Docker Desktop (HolmesGPT runs now add
  `--add-host host.docker.internal:host-gateway`)
- [x] `make lint` also runs `ruff format --check`; `evals/phase4.py` formatted
- [x] **Done when:** each toolset and helper command returns condensed real data, a write attempt
  is refused, both versions are indexed, and those results are pinned by tests

## Phase 6: Layer 2 nodes (days 10–11)

- [ ] Tests first: evidence checks, error-signature normalization, round 2's trigger, the timeout path
- [ ] Duplicate check: exact signature, retrieval over open tickets, structured LLM confirmation
- [ ] Brief
- [ ] Data analyst node: runs HolmesGPT's container, enforces the 90 s timeout and tool-call budget
  itself (its step limit counts model turns: the spike made 36 calls in 15 turns), streams its tool calls;
  maps `host.docker.internal` to the host gateway as `tests/test_spike.py` does
- [ ] Codebase analyst node (mini-swe-agent) with timeout, streaming its commands; it exports
  the deployed commit's index (`app.indexer.__main__.export_index`) to mount at `/index`, sets
  `PREV_GIT_DIR`, and puts the service card and change summary in the task prompt
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
