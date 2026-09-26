# Evals (dataset in phase 3, runs in phase 9)

Pydantic Evals dataset of 20 labelled tickets, written before the first prompt so every LLM node
has a target: the 7 demo tickets plus vague wording, two issues in one ticket, a ticket naming
the wrong service, an angry customer describing expected behaviour, and one prompt-injection
attempt. Each is labelled with expected type, service, verdict, team, the help section that
answers it, and the past tickets retrieval should find. Results go to `eval_results`, which
`GET /evals/scorecard` serves.
