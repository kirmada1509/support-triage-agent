# Evals (dataset in phase 3, runs in phase 9)

`tickets.yaml` fixes the 20 labels before the phase 4 model prompts: the seven demo tickets plus
vague wording, combined requests, a wrong-service claim, an angry false positive, and a prompt
injection attempt. Each has expected type, service, verdict, team, answering help section, and
past-ticket IDs. Phase 9 will turn these labels into Pydantic Evals runs.

`retrieval_baseline.json` is produced by `make retrieval-hits` on a throwaway database. It records
help-section top-five and past-ticket top-three hits without giving search the expected service.
Ticket 7's open `T-4` memory row is inserted only for the benchmark and removed afterward. The
report retains both exact-ID and same-family synthetic ticket rates so near-miss behavior is
visible rather than hidden by the wording variants.
