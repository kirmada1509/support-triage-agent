# Evals

`tickets.yaml` fixes the 20 labels before the phase 4 model prompts: the seven demo tickets plus
vague wording, combined requests, a wrong-service claim, an angry false positive, and a prompt
injection attempt. Each has expected type, service, verdict, team, answering help section, and
past-ticket IDs. Phase 9 will extend these baseline runs with Pydantic Evals.

`retrieval_baseline.json` is produced by `make retrieval-hits` on a throwaway database. It records
help-section top-five and past-ticket top-three hits without giving search the expected service.
Ticket 7's open `T-4` memory row is inserted only for the benchmark and removed afterward. The
report retains both exact-ID and same-family synthetic ticket rates so near-miss behavior is
visible rather than hidden by the wording variants.

`phase4.py` is the live front-pipeline baseline. After `make index-help index-tickets`, run
`make front-eval` with the active model profile's key. It executes enrichment, retrieval,
classification and the chosen Layer 1 or request node for all 20 cases, then writes
`phase4_baseline.json`. The report scores type, service and the actual route after confidence
gating; checks that each UTC window is within seven days; and counts expected help citations.
Inputs contain ticket text and the service glossary, but no labels, deploys, flags or incidents.
Use `uv run python -m evals.phase4 --ids 2,16 --output /tmp/phase4-focus.json` for a focused run.
