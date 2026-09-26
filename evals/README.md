# Evals (phase 9)

Pydantic Evals dataset of 20 labelled tickets: the 7 demo tickets plus vague wording, two
issues in one ticket, a ticket naming the wrong service, an angry customer describing expected
behaviour, and one prompt-injection attempt. Each is labelled with expected type, service,
verdict, team, and the past tickets retrieval should find. Results go to `eval_results`, which
`GET /evals/scorecard` serves.
