# Triage Console (phase 8)

Next.js App Router + TanStack Query + shadcn/ui + AI Elements + React Flow UI. Pages compose
library components; the only custom files are `lib/api.ts`, `lib/use-ticket-events.ts`,
`components/output-view.tsx` and `components/stage-node.tsx`.

```bash
pnpm create next-app@latest web --ts --tailwind --app   # run from the repo root
cd web && pnpm dlx shadcn@latest init
pnpm dlx shadcn@latest add sidebar table badge card tabs resizable sheet tooltip progress \
  skeleton chart form select textarea sonner
pnpm dlx ai-elements@latest add tool code-block terminal commit stack-trace chain-of-thought \
  task sources confirmation message shimmer
pnpm dlx shadcn@latest add https://ui.reactflow.dev/base-node https://ui.reactflow.dev/node-status-indicator \
  https://ui.reactflow.dev/animated-svg-edge https://ui.reactflow.dev/zoom-slider
pnpm add @tanstack/react-query @tanstack/react-table @xyflow/react openapi-fetch openapi-react-query \
  nuqs @melloware/react-logviewer @uiw/react-json-view date-fns next-themes
pnpm add -D openapi-typescript
# package.json: "gen:api": "openapi-typescript http://localhost:8000/openapi.json -o lib/schema.d.ts"
```

Check the exact React Flow UI component names on its site before running the fourth command.
`create-next-app` wants an empty folder: move this README aside first.
