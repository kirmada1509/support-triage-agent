# Build checklist

What's built and what isn't, phase by phase, against `Agent_Architecture_And_Build_Plan.md`.
Tick an item when it works and is tested the way the plan's "How it's tested" says; tick a
phase's "Done when" only when that whole criterion has been seen working.

Last updated Sep 28, 2026, left-to-right pipeline layout and DeepSeek balance in the console; two-way analyst handoff verified live on DeepSeek (4/4), local Ollama profiles available; populated scorecard awaits Phase 9 data. Suite inventory (provider calls depend on credit):

| Suite | Command | Needs | Tests |
| --- | --- | --- | --- |
| Units, graph in memory, front pipeline, scenario logic, sandbox kit, tracing, model config, retrieval, indexer, codebox helpers, trace condensing, Layer 2 rules, handoff and nodes, Linear/Pylon/DeepSeek-balance adapters, final outcome, console presentation adapter and fixture | `make test` | nothing | 294 |
| Database | `make test-db` | `make db` | 16 |
| The fork: tags, planted bugs, overlay, images, the code index at both tags | `make test-sandbox` | `make sandbox` | 28 |
| The running shop: every scenario, read-only role, metrics, logs | `make test-shop` | `make shop-up` | 15 |
| Real model calls on each provider profile, a real payment service card | `make test-llm` | keys in `.env.agent` | 5 |
| Both analysts on demo tickets, codebox and history guardrails | `make test-spike` | shop, `make analyst-images`, keys | 6 |
| Demo tickets 3-7 through the whole graph, live | `make test-layer2` | shop, `make sandbox-images analyst-images`, keys | 5 |
| The two-way handoff on tickets 4, 8, 9, live | `make test-handoff` | shop, `make analyst-images`, DeepSeek key | 4 |

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

- [x] Tests first: evidence checks, error-signature normalization (code templates too), round 2's
  trigger, the timeout and call-budget path, the verdict's rules (`tests/test_layer2.py`,
  `tests/test_layer2_nodes.py`)
- [x] Duplicate check: exact signature against open investigations, retrieval over open tickets,
  a structured confirmation that must name a candidate (live: 7 links to 4; 6 is not linked)
- [x] Brief, built in code with no model call (plan changed): ticket as data, window, versions,
  recent changes, past tickets as hypotheses
- [x] Data analyst node: HolmesGPT's container with the time and call budget enforced from its
  streamed "Running tool" lines (240 s, 40 calls: measured runs took 50-210 s and 21-37 calls,
  plan changed); streams its calls
- [x] Codebase analyst node (mini-swe-agent in a thread, commands counted and streamed): exports
  the deployed commit's index to `/index`, sets `PREV_GIT_DIR`, puts the service card and change
  summary in the task (120 s, 20 commands)
- [x] Findings conversion with evidence checks: a cited call must exist, have succeeded and show
  the ref; the data analyst can't cite code, the codebase analyst can't cite telemetry; an exact
  error must come from a trace or log (not a tool's own error)
- [x] Cost per analyst run (HolmesGPT's own total; the codebox's from tokens and `models.yaml`),
  added to `tickets.cost_usd` by the worker
- [x] Round 2 (now `code_followup`, see the two-way handoff below): the data analyst's exact error to the codebox once (90 s, 24 commands;
  raised from 16 after a live Amex run exhausted the smaller budget);
  `lookup-error` now finds a template from the start of a message
- [x] Verdict, then `apply_rules`: two sources, production must show the symptom, a bug needs the
  file:line and commit the codebase analyst saw, an incident a flag change, a false positive the
  code; the codebase analyst's latest judgment of the verdict's file:line decides bug vs intended
  (scoped to the place after the two-way handoff; the latest overall when none read it)
- [x] Write-back to ticket memory and `investigations`
- [x] Added a read-only Jaeger search for successful service/operation traces and quote totals in
  condensed summaries; quote investigations now search before/after quote deploys first. Local
  tests cover the tool definition, summary, prompt and evidence checks
- [x] Rebuilt with `make analyst-images`; `make test-spike` passed 6/6 after the log-search,
  `lookup-error`, and Jaeger tool changes
- [x] HolmesGPT's native tool-call IDs are preserved and checked alongside the app's `hN` IDs;
  valid citations are normalized to `hN`. A live run dropped all 14 data citations and ended
  inconclusive; subsequent live runs kept evidence with this ID handling
- [x] Ticket 5 in the ordered `make test-layer2` run: confirmed quote bug at
  `src/quote/app/routes.php:34-39`, commit `8dd1ecde`, after scenarios 3 and 4
- [ ] Layer 2 run-to-run variance (HolmesGPT repeats queries; 50-210 s): measure in phase 9
- [x] Two-way handoff replaces the one-way round 2 (plan changed): `handoff` decides in code who
  asks whom (production's exact error to the code, an analyst's `ASK ...:` question, a code
  regression production hasn't shown yet to the data), `code_followup` / `data_followup` answer
  with the asker's checked findings; each question once, two per analyst, three in all
  (`tests/test_handoff.py`, node and graph tests, both directions and the cap)
- [x] Tickets 8 (cart keeps items after EUR/CAD orders) and 9 (The Comet Book missing): silent
  bugs where the code finds the change and production confirms it; `make scenario-8/9`
- [x] Local Ollama profiles `ollama` (qwen3.5:9b-32k, thinking off) and `ollama-think`, no key;
  thinking set per client, 32k context (`make ollama-model`), per-model `time_scale` for the
  analysts' budgets; uncited evidence tied to the call that shows its ref
- [x] Live fixes from `make test-handoff` on DeepSeek, each test first: a code judgment counts
  for the file:line it read (ticket 9: production's lookup error at main.go:406, found intended,
  overrode the listing regression at :235); the findings call gets the customer's symptom; an
  error goes to the code only if the code index places it in the suspected service (ticket 8
  chased payment's expiry error from ticket 4's scenario); evidence citing a call ID that names
  no call (DeepSeek shortened HolmesGPT's native IDs) is tied to the call that shows it; the data
  follow-up asks for about 10 calls under its hard 25
- [x] `make test-handoff` on DeepSeek with every fix: 4/4 in 9m27s; tickets 4, 8, 9 are
  confirmed bugs at the planted file and commit (92%, 85%, 93%), ticket 4 handed production's
  error to the code, ticket 9 asked production to confirm the listing regression, ticket 8 needed
  neither (`evals/handoff_deepseek.json`); ticket 3 still a false positive (86%) after the
  judgment scoping. Earlier runs: 1/4 before the fixes, then 3/4, then 4/4
- [ ] Data follow-ups still hit their 25-call stop on some questions (per-shopper breakdowns):
  measure in phase 9 with the Layer 2 variance
- [ ] Local qwen3.5:9b is too slow here for the analysts (~5 output tokens/s on a 16 GB M5 with
  the shop up, swapping; one ticket 30-60 min): the live run was stopped; revisit with more memory
  (thinking off first)
- [x] **Done when:** ticket 3 is a false positive, tickets 4 and 5 are bugs with the right file
  and commit, ticket 6 is a config incident, and ticket 7 links to ticket 4's open issue
  (one ordered run passed 5/5 in 11m57s; 85%, 90%, 90%, 88%, linked)

## Phase 7: Layer 3 and console API (day 12)

- [x] Approval node with `interrupt()`, resumed by `POST /tickets/{id}/approve`
- [x] Console endpoints: queue, ticket, `/pipeline` from `get_graph()`, stored events, SSE stream
  with replay, approve, simulator, scorecard
- [x] Layer 3: ownership lookup, checked evidence description, Linear GraphQL issue creation,
  durable event receipt and issue link (worker test uses a fake Linear response)
- [x] Customer acknowledgement and reply sending: Pylon reply and internal note adapters,
  feature request roadmap handoff, logged fallback without an account; approval rejection sends
  nothing, and retries check delivery receipts
- [x] Final `outcome` event and `GET /tickets/{id}.outcome`: verdict, root cause, code location,
  optional issue, approval and reply delivery; a no-Linear bug finishes with a visible result
- [x] Engineering handoffs and final outcomes include short code or diff excerpts only when a
  checked code reference matches successful codebox output. Historical stored runs gain the
  same presentation on API reads without changing stored evidence. The local demo includes its
  captured payment diff; no model call or codebox rerun is needed.
- [x] Approval resumes a paused worker run (`make test-db`)
- [x] `curl -N` on a live API stream received a newly inserted stage event from Postgres
- [x] **Done when:** a bug ticket finishes with a readable local outcome (database worker test),
  approval resumes the paused run, and `curl` receives a live SSE event. Real Linear/Pylon
  delivery was not requested for this demo and remains unvalidated without account credentials.

## Phase 8: Triage Console (days 13–15)

- [x] Next.js App Router, shadcn/ui, AI Elements, React Flow UI, OpenAPI-generated API client,
  sidebar shell; `pnpm typecheck`, `pnpm lint`, and `pnpm build` pass
- [x] `/tickets` queue, status filters, selected preview, and real ticket detail
- [x] `/tickets` New ticket dialog submits subject, customer message, and tenant through the
  existing simulator intake endpoint and opens the returned live investigation. Browser verified
  request, navigation, and failure feedback with intercepted POSTs; no agent run was started.
- [x] `/ticket/[id]`: backend pipeline topology and positions, stage-focused live timeline,
  SSE hook, typed output renderers, ticket details, and final outcome
- [x] Approval and edit flow resumes the same worker run; backend-timed replay uses the same UI
- [x] `/simulator` loads real templates, creates a ticket, and opens its live investigation;
  `/scorecard` reads the real endpoint and shows an honest empty state when it has no rows
- [x] Light and dark mode, responsive details Sheet, loading and failure states
- [x] Root `start_local.sh` and `stop_local.sh` bring up and stop local Postgres, API, worker,
  and console without stopping an existing Postgres or the sandbox shop; tested both DB ownership
  paths and repeat start/stop
- [x] `start_local.sh --follow` and `logs_local.sh` show labeled API, worker, and web logs in one
  terminal; tested that Ctrl-C leaves the services running
- [x] Optional `--observability` starts a file-log collector on the shop network; all three
  local services reached OpenSearch with distinct service names, a new API access log appeared
  without restarting the collector, and Grafana's OpenSearch and Jaeger data sources responded
- [x] Ticket selection opens the right preview on desktop and a visible Sheet below `xl`;
  fixed a hidden mobile Sheet that left its blur overlay over the desktop page. Verified both
  layouts and that resizing from a narrow view closes the Sheet.
- [x] Running HolmesGPT calls with no arguments yet reported no longer render misleading
  `Parameters {}`; the timeline waits for the backend's completed event to show the command
  and output. Verified against ticket T-390875's stored running and completed tool events.
- [x] Enrichment shows a readable case summary; data and codebase analyst work is grouped by
  stage in collapsible timeline entries. Commands use a copyable Bash Code Block, mixed diffs
  are highlighted, and active stage headings show small spinners. Stage selection opens its
  analyst group; Raw remains chronological.
- [x] FastAPI read-boundary adapter presents stored Prometheus outputs as series/tables, logs as
  logs, and unambiguous code as code while preserving raw text; malformed results remain terminal.
  Verified with captured T-390875 API events and six provider-free tests.
- [x] `/ticket/demo` uses a validated, sanitized 126-event payment fixture with no FastAPI,
  worker, provider, or approval POST calls. Browser verified Play/Pause/Step/Restart, approval
  pause, edited local reply, final local outcome, stage filtering, and light/dark mode while API
  was unavailable; the browser request log contained no backend requests.
- [x] Investigation polish: the typed verdict and analyst findings render as readable summaries
  in Live while Raw keeps the original data. Stage and customer avatars, restrained spinners,
  approval waiting state, pipeline auto-centering and scroll controls, and hidden scrollbars make
  the recorded run easier to follow. Running analyst groups show four recent updates with a
  Show all control; the full history remains available when the group finishes.
- [x] Final-result code excerpts use the existing AI Elements Code Block with file, line range,
  source call, and copy action; browser verified the offline payment run in light mode.
- [x] Applied the investigation screen's compact headers, semantic badges, small icons, dividers,
  and light/dark styling across navigation, ticket queue and preview, simulator, and scorecard.
  Browser verified queue selection, scenario selection, and the empty scorecard state without
  creating a ticket or starting an agent run.
- [x] Manual browser run: simulator ticket T-2FC8BE streamed to a local outcome without refresh;
  approval ticket T-8BEEAC resumed after an edited reply; `make scenario-4` sent T-BD9A0F,
  showed HolmesGPT and codebase analyst calls, stage transitions, approval, and a confirmed-bug
  local outcome; replay delivered stored events in order
- [x] The pipeline is laid out left to right in `app/graph/layout.yaml` (columns and lanes) and
  used as is: no overlapping nodes, full stage names, long edges routed under the chart or into
  approve from above, and each handoff <-> follow-up pair drawn as one line. Browser verified on
  T-EEFB42 (handoff run) and the offline demo. The verdict and final outcome cards lost their
  thick left border.
- [x] The sidebar header shows the DeepSeek credit left (`GET /providers/deepseek/balance`,
  refreshed every minute; "No key" without `DEEPSEEK_API_KEY`, amber when low or unavailable);
  five provider-free tests, browser verified against the real account.
- [x] **Done when:** a live ticket lights up the flowchart stage by stage, tool calls show their
  commands and typed output when safely recognized, a reply can be approved, and a past run
  replays. The captured payment run renders real series, table, log, and code events through the
  API adapter. The scorecard remains honestly empty until Phase 9 fills `eval_results`.

## Phase 9: Evals, model choice, rehearsal (days 16–17)

- [ ] The eval dataset as a Pydantic Evals run, per model and role, with and without retrieval
- [ ] Scorecard results in `eval_results`
- [ ] Models chosen per role
- [ ] Prompt fixes from the failures
- [ ] Two full rehearsals and a backup video
- [ ] **Done when:** at least 18 of 20 tickets are routed correctly on the chosen models, the
  scorecard is ready to show, and a run-through stays under 10 minutes
