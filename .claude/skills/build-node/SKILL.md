---
name: build-node
description: Replace a stub pipeline node (app/nodes/*.py) with the real implementation, test-first. Use when implementing any stage of the LangGraph pipeline (context, enrich, retrieve, jev, layer1, requests, duplicates, brief, data_analyst, codebase_analyst, round2, verdict, layer3, reply, remember) or adding logic a node calls.
---

# Build a pipeline node, test-first

1. **Find the spec.** Read the node's docstring (`TODO(phase N)` says what replaces the stub),
   its item in `planning/Build_Checklist.md`, and its section in
   `planning/Agent_Architecture_And_Build_Plan.md`. Note the `TicketState` keys it reads and
   returns (`app/graph/state.py`) and the models involved (`app/models.py`).

2. **Split the node** into:
   - pure logic code can check (validation, routing, citation or evidence checks, parsing):
     tested first, with pytest;
   - the outside call (model, Jev, HolmesGPT, mini-swe-agent, Postgres, HTTP): one small
     function tests can replace;
   - model behaviour: judged by the eval dataset (`evals/`), not by unit tests.

3. **Write the failing tests first**, in `tests/test_units.py` or a new `tests/test_<area>.py`:
   - the pure logic, including what gets dropped or refused (bad IDs, empty input, timeouts);
   - the node itself: call `await node.run(state)` with a hand-built state and the outside call
     monkeypatched; assert the returned keys and the events it emits.
   Run `make test` and see them fail for the right reason.

4. **Implement.** Keep the node `async def run(state: TicketState) -> dict`, returning only the
   keys it changes (plus optional `_summary`). Send progress with `emit(...)` from
   `app/graph/stream.py`, using the event models in `app/events.py` (events are told apart by
   `kind`, tool outputs by `render`; if no output type fits, add one to the `Output` union). Model calls: `pydantic_ai_model(role)` or
   `litellm_model(role)` from `app/models_config.py`, and the role's entry in `LIMITS`. Every ID
   a model returns must be checked against what it was given in this run; drop what fails.

5. **Keep the graph whole.** `make test` runs `tests/test_graph.py`, the pipeline end to end in
   memory; it must still pass. If the node now needs a real service, fake it in
   `tests/conftest.py` the way `fetch_context` is faked. If it calls out, give it a
   `RetryPolicy` in `app/graph/build.py`.

6. **Check it for real** once, against the sandbox where it applies (`make shop-up`,
   `make api`, `make worker`, `make scenario-N`), and read the events it stored.

7. **Finish with the `wrap-up` skill**: tick the checklist item, update AGENTS.md's "How it
   works" if the node is no longer a stub, and commit.
