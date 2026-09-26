---
name: wrap-up
description: Finish a task in this repo - run the right test suites, update planning/Build_Checklist.md, AGENTS.md and the READMEs so they match the code, then commit. Use at the end of every change, before reporting it done.
---

# Wrap up a change

1. **Run the tests** that cover what changed, and read the results:
   - always: `make lint test`
   - database: `make test-db`
   - `sandbox/` or the fork: `make test-sandbox`
   - scenarios, the shop, deploy or flag scripts: `make test-shop` (needs `make shop-up`)
   Don't report a suite as passing without having run it; say which ones you skipped and why.

2. **Update the checklist** (`planning/Build_Checklist.md`): tick items that now work and are
   tested; tick a phase's "Done when" only when the whole criterion has been seen working; add
   anything newly found under the phase that will fix it; update the test-count table and the
   "Last updated" line.

3. **Update AGENTS.md** where the change made it wrong: the repository map, "How it works" (a
   stub became real), commands, test suites, the sandbox facts, conventions. Add a gotcha if one
   cost real time. Remove what's no longer true. Bump "Last updated".

4. **Update the other docs** only where they describe what changed: `README.md` (running
   things), `sandbox/README.md` (the sandbox), the plan (a design decision changed; say why).
   Link instead of repeating.

5. **Commit** on the phase branch (`phase-N-name`; create it from `main` if needed): stage
   the change and its docs together, a short imperative subject, a bullet body of what and why,
   the trailer the harness asks for. Check `git status` first: never commit `.env.agent`, and
   leave the fork (`../opentelemetry-demo`) clean.
