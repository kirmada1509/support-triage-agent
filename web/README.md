# Triage Console

Next.js App Router frontend for the Support Triage Agent. It reads the existing FastAPI contract;
`lib/schema.d.ts` is generated from `/openapi.json`. The ticket page uses the backend's pipeline
nodes and positions, SSE stage events, and final outcome. Live and replay use the same timeline.

## Run

From the repository root, `./start_local.sh` starts Postgres, the API, worker, and this console;
`./start_local.sh --follow` also shows labeled live logs, and `./logs_local.sh` attaches later.
`./stop_local.sh` stops the services it started. For separate terminals, start the API, worker,
and database as described in the root README, then:

```bash
cd web
pnpm install
pnpm dev                 # http://localhost:3000
pnpm gen:api             # regenerate types while the API is running on :8000
pnpm typecheck
pnpm lint
pnpm build
```

For browser-based API, worker, and web logs alongside Jaeger traces, start the sandbox shop and
use `./start_local.sh --observability`. Open [Grafana Explore](http://localhost:8080/grafana/explore)
and select the OpenSearch or Jaeger data source. This runs a small collector for the host log files;
the application services still run locally.

Set `NEXT_PUBLIC_API_URL` if FastAPI is not on `http://localhost:8000`. The API allows the console
origin at `http://localhost:3000` by default. For a live technical investigation, also start the
sandbox shop and its analyst images as described in `../sandbox/README.md`.

The UI uses copied shadcn/ui, AI Elements, and React Flow UI primitives. Custom integration code is
limited to the typed API client, SSE hook, output-type switch, stage node, and page compositions.
The backend persists HolmesGPT and codebox output unchanged. At API read time, a conservative
presentation adapter recognizes validated Prometheus series/tables, log results, and unambiguous
code/diffs; each typed event retains `raw_output`, and unknown output stays terminal. The output
switch renders `code`, `diff`, `series`, `trace`, `table`, `log`, `commit`, and `json` variants. It
does not parse analyst stdout. The scorecard reads
`/evals/scorecard`; it shows an empty state until evaluation results are recorded in the database.
HolmesGPT streams tool names as calls start; their arguments and output arrive when its run
finishes. The timeline shows a running call without inventing arguments in the meantime.

Routes: `/tickets`, `/ticket/{id}` (or `?replay=1`), `/simulator`, `/scorecard`.

For UI development without backend services or LLM credentials, run `cd web && pnpm dev` and open
`http://localhost:3000/ticket/demo`. This uses a sanitized 126-event payment investigation fixture
through the same pipeline and timeline. Play, Pause, Step, and Restart control local playback; it
pauses at the recorded approval. Simulated Approve/Edit resumes locally, and any edited reply is
shown in the local outcome. This route makes no FastAPI, SSE, worker, provider, or approval POST
requests. Real `?replay=1` still uses the backend-controlled stream timing.
