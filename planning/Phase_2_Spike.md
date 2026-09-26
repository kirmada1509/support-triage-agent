# Phase 2 spike: results

Sep 26, 2026. Each open-source part and the model layer was run once against the real sandbox,
on the models `config/roles.yaml` gives them, to find poor fits before later phases depend on
them. Repeat it with `make test-spike` (`tests/test_spike.py`) after upgrading either agent.

## What was tried, and what happened

| Part | Result | Numbers |
| --- | --- | --- |
| Agent tracing | Works. One trace per ticket run, a span per node, in the shop's Jaeger as `support-triage-agent` | endpoint `http://localhost:8080/otlp-http` |
| Pydantic AI, two providers | Works on DeepSeek direct and OpenRouter after two settings fixes (below); `ROLE_PROFILE` switches | a typed call is ~1 s, well under a cent |
| HolmesGPT 0.42.0, ticket 4 | Right service, version, deploy time, commit, all 4 shoppers, the "this month only" pattern, backed by traces and logs | 103 s, 36 tool calls, $0.012 (OpenRouter DeepSeek V4 Flash) |
| mini-swe-agent 2.4.6, ticket 4 | Found `charge.js:88`, the commit by blame, and the README line it contradicts: regression | 23 s, 14 commands (DeepSeek Flash direct) |
| mini-swe-agent 2.4.6, ticket 3 | Card-type check traced to upstream's first commit: intended; flagged the expiry bug separately | 57 s, 33 commands |

## Poor fits found, and what changed

1. **HolmesGPT can't share the app's Python environment.** 0.42.0 needs `openai<3` and
   `fastapi<0.137`; Pydantic AI 2.x needs `openai` 3. uv silently resolved an ancient 0.12.6
   that downgraded Pydantic AI to 1.x. **Change:** HolmesGPT runs in its own image
   (`holmes/Dockerfile`, `make analyst-images`) on the shop's network; the `data_analyst` node
   will run it there (`holmes ask ... --json-output-file`) instead of importing it.
2. **DeepSeek's own API rejects HolmesGPT's tool schemas** ("An object with no properties is not
   allowed"). OpenRouter's DeepSeek accepts them. **First change:** the data analyst went through
   OpenRouter. **Later change:** the only offender was `elasticsearch_search` (its `query`,
   `sort`, `source` and `aggregations` are free-form objects). `elasticsearch/data` is off, and
   our `logs` toolset (`holmes/search_logs.py`, tested) takes the query as a JSON string, so
   every role runs on DeepSeek direct: ticket 4 in 156 s, 62 tool calls, $0.06, all checks
   passing. mini-swe-agent's single tool was always fine on DeepSeek direct.
3. **DeepSeek's thinking mode rejects the forced tool choice Pydantic AI uses for typed output**,
   and **OpenRouter reserves 65536 output tokens per request** unless `max_tokens` is set, then
   refuses the call once credit runs low. **Change:** every model in `config/models.yaml` has
   `settings` (a `max_tokens` cap; thinking off for direct DeepSeek), applied per model.
4. **HolmesGPT enables a shell, internet access and kubectl by default.** **Change:**
   `holmes/toolsets.yaml` disables them; only our five toolsets and its planning tool remain.
5. **The draft toolset names were wrong for 0.42.0**: OpenSearch logs came through
   `elasticsearch/data` (`api_url`, since replaced by `logs`, see 2), and `database/sql` gained
   `read_only: true`; its tools are `database_sql_query`, `_list_tables` and `_describe_table`.
6. **Git worktrees don't work in the codebox as mounted.** A worktree's `.git` points at an
   absolute host path, and mounting `.git` at that path doesn't work under Docker Desktop.
   **Change:** mount the fork's `.git` at `/git` with `GIT_DIR=/git/worktrees/shop@<tag>` and
   `GIT_WORK_TREE=/repo`. The helper commands also weren't readable by the `analyst` user (mode
   711); now 755.

## Still to handle (in the phase that owns it)

- **Limits are per model turn, not per tool call** (phase 6). HolmesGPT's `--max-steps 15` still
  allowed 36 tool calls in 103 s, and mini-swe-agent's step limit counts turns too. The node
  must enforce the plan's 90 s and tool-call budget itself and stop to `inconclusive`.
- **HolmesGPT guesses about code** ("likely `<` instead of `<=`") without reading any (phase 6).
  The brief tells it not to; the findings check must drop claims no tool call supports.
- **`GIT_DIR` also applies in `/prev`**, so git there shows v1.4.0's history (phase 5). The
  prompt says to use `git show v1.3.0:<path>`; better to give `/prev` its own git environment.
- **Models read "expired at checkout" as a checkout problem**, not payment (phase 4). The
  categorization prompt needs each service described by what it does, not by page name.
- **Cost reporting:** LiteLLM has no price for `deepseek-flash`, so mini-swe-agent reports no
  cost; compute it from tokens with `config/models.yaml` prices (phase 6).
