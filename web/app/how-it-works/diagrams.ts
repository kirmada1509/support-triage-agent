// The architecture diagrams in ../planning, served as they are by ./[slug]/route.ts.
export const diagrams = [
  {
    slug: "system-map",
    file: "Triage Agent System Map.html",
    title: "Triage Agent System Map",
    description: "Every part of the system and how a ticket moves through them: Pylon, the API, the worker and its LangGraph pipeline, both analysts, the sandbox shop, Postgres and the outside services.",
  },
  {
    slug: "bug-walkthrough",
    file: "Expired-Card Bug Walkthrough.html",
    title: "Expired-Card Bug Walkthrough",
    description: "One bug ticket from start to finish: categorization, the brief, both analysts in parallel, the handoff where they ask each other, the verdict and the Linear issue.",
  },
] as const;
