"""Turn an analyst's text answer + tool log into Findings, and check the evidence.

HolmesGPT and mini-swe-agent answer in text. A Pydantic AI call (role "findings") converts the
answer and its tool log into Findings; code then drops any evidence that doesn't point at a tool
call that actually happened and showed it. Only what an analyst queried or read during the run
counts: the data analyst can't cite code (it never reads any), the codebase analyst can't cite
telemetry.
"""

import re

from app.models import Evidence, Findings, ToolRecord
from app.nodes._llm import call
from app.nodes.duplicates import error_signature

_METRIC_TOOLS = {
    "execute_prometheus_instant_query",
    "execute_prometheus_range_query",
    "get_metric_names",
    "get_metric_metadata",
    "get_label_values",
    "get_all_labels",
    "get_series",
    "list_prometheus_rules",
}
TOOLS_FOR = {
    "trace": {"find_traces", "find_error_traces", "find_traces_for_user", "get_trace"},
    "metric": _METRIC_TOOLS,
    "log": {"search_logs", "log_indices"},
    "sql": {"database_sql_query", "database_sql_list_tables", "database_sql_describe_table"},
    "deploy": {"deploys"},
    "flag": {"flag_changes"},
    "code": {"bash"},
    "git": {"bash"},
}
# Where an analyst's exact error message may come from: the shop's own spans and logs, or code.
ERROR_TOOLS = {
    "data_analyst": {"find_error_traces", "find_traces_for_user", "get_trace"} | TOOLS_FOR["log"],
    "codebase_analyst": {"bash"},
}
_SHA = re.compile(r"^[0-9a-f]{7,40}$")
SOURCES_OF = {
    "data_analyst": {"trace", "metric", "log", "sql", "deploy", "flag"},
    "codebase_analyst": {"code", "git"},
}


PROMPT = """Convert a support investigation analyst's answer into Findings. The analyst is the
{agent}. Its answer and every tool call it made are below; use nothing else.

- hypothesis: what the analyst concluded, in one or two sentences.
- evidence: each fact the answer relies on, citing the call_id of the tool call whose output
  shows it. ref is the exact trace ID, file:line, commit sha, or query from that call. source:
  {sources}.
- error_text: the exact error message the shop's service gave the customer's requests, as a
  span, log or the code shows it; never an error from a tool or query itself. Leave it empty if
  there is none.
- intended: codebase analyst only: true if the code it cites behaves as intended, false if a
  change made it a regression, empty if it didn't say.
- confidence: 0 to 1, how well the tool outputs support the hypothesis.

<answer>
{answer}
</answer>

<tool_calls>
{calls}
</tool_calls>"""

CALL_CHARS = 900  # of each call's output shown to the model
PROMPT_CHARS = 60_000

SOURCE_HELP = {
    "data_analyst": "trace (a trace ID), metric (a PromQL query), log (a log search), sql (a "
    "catalog query), deploy (a deploy record), flag (a flag change)",
    "codebase_analyst": "code (file:line), git (a commit sha)",
}


def _prompt(agent: str, answer: str, calls: list[ToolRecord]) -> str:
    shown, used = [], 0
    for c in calls:
        args = " ".join(str(v) for v in c.args.values())[:300]
        entry = f"[{c.call_id}] {c.tool} {args}\n{c.output[:CALL_CHARS]}"
        if used + len(entry) > PROMPT_CHARS:
            shown.append(f"({len(calls) - len(shown)} more calls left out)")
            break
        shown.append(entry)
        used += len(entry)
    return PROMPT.format(
        agent=agent, sources=SOURCE_HELP[agent], answer=answer, calls="\n\n".join(shown)
    )


async def convert(agent: str, answer: str, calls: list[ToolRecord], round: int = 1) -> Findings:
    """One typed call (role "findings"); the result still goes through check_evidence."""
    f, _ = await call("findings", Findings, _prompt(agent, answer, calls))
    return f.model_copy(update={"agent": agent, "round": round})


def _seen(c: ToolRecord) -> str:
    return " ".join([*(str(v) for v in c.args.values()), c.output]).lower()


def same_commit(a: str, b: str) -> bool:
    a, b = a.split()[0].lower() if a.split() else "", b.split()[0].lower() if b.split() else ""
    return min(len(a), len(b)) >= 7 and (a.startswith(b) or b.startswith(a))


def _supported(e: Evidence, agent: str, calls: dict[str, ToolRecord]) -> bool:
    call = calls.get(e.call_id or "")
    if call is None or not call.ok:
        return False
    if e.source not in SOURCES_OF[agent] or call.tool not in TOOLS_FOR[e.source]:
        return False
    seen = _seen(call)
    if e.source == "trace":
        return e.ref.lower() in seen
    if e.source == "git":
        sha = e.ref.split()[0].lower() if e.ref.split() else ""
        return bool(_SHA.match(sha)) and any(same_commit(sha, word) for word in seen.split())
    if e.source == "code":
        return e.ref.split(":")[0].lower() in seen
    return True  # a query the analyst ran with the right tool; its wording needn't match


def check_evidence(findings: Findings, calls: list[ToolRecord]) -> Findings:
    """Keep evidence tied to a real tool call that showed it; cap confidence when none is left."""
    by_id = {c.call_id: c for c in calls}
    for c in calls:
        if c.provider_call_id and c.provider_call_id not in by_id:
            by_id[c.provider_call_id] = c
    kept = [
        e.model_copy(update={"call_id": by_id[e.call_id].call_id})
        for e in findings.evidence
        if e.call_id and _supported(e, findings.agent, by_id)
    ]
    error_text = findings.error_text
    sources = [c for c in calls if c.ok and c.tool in ERROR_TOOLS[findings.agent]]
    if error_text and not any(
        error_signature(error_text) in error_signature(_seen(c)) for c in sources
    ):
        error_text = None
    confidence = findings.confidence if kept else min(findings.confidence, 0.3)
    return findings.model_copy(
        update={"evidence": kept, "confidence": confidence, "error_text": error_text}
    )


def limit_hit(agent: str, reason: str) -> Findings:
    """An analyst run that hit its time or call budget: no evidence, no guess."""
    return Findings(
        agent=agent,
        hypothesis=f"inconclusive: {reason}",
        evidence=[],
        confidence=0.0,
        completed=False,
    )
