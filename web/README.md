# Triage Console

Next.js App Router frontend for the Support Triage Agent. It reads the existing FastAPI contract;
`lib/schema.d.ts` is generated from `/openapi.json`. The ticket page uses the backend's pipeline
nodes and positions, SSE stage events, and final outcome. Live and replay use the same timeline.

## Run

From the repository root, `./start_local.sh` starts Postgres, the API, worker, and this console;
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

Set `NEXT_PUBLIC_API_URL` if FastAPI is not on `http://localhost:8000`. The API allows the console
origin at `http://localhost:3000` by default. For a live technical investigation, also start the
sandbox shop and its analyst images as described in `../sandbox/README.md`.

The UI uses copied shadcn/ui, AI Elements, and React Flow UI primitives. Custom integration code is
limited to the typed API client, SSE hook, output-type switch, stage node, and page compositions.
The backend emits HolmesGPT and codebox results as `terminal` outputs today. The output switch
also renders the structured `code`, `diff`, `series`, `trace`, `table`, `log`, `commit`, and `json`
variants when they are emitted. It does not parse analyst stdout. The scorecard reads
`/evals/scorecard`; it shows an empty state until evaluation results are recorded in the database.

Routes: `/tickets`, `/ticket/{id}` (or `?replay=1`), `/simulator`, `/scorecard`.
