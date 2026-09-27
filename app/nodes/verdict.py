"""Verdict: one call on the strongest model over both analysts' checked Findings, then the
guardrails in code (apply_rules). A verdict without evidence from at least two independent
sources, or without what its kind needs, is inconclusive and goes to a person; it never guesses.
"""

import json

from app.events import ModelOutputEvent
from app.graph.state import TicketState
from app.graph.stream import emit
from app.models import Findings, Verdict
from app.nodes._config import ownership
from app.nodes._llm import call
from app.nodes.findings import same_commit

PROMPT = """You decide the outcome of a support investigation from two analysts' findings. The
data analyst read production telemetry and change history; the codebase analyst read the code.
After the first round they asked each other questions (handoffs); each later round answers one.
Where a later round disagrees with round 1, the later round is the one about this ticket. Only the
evidence below counts; every item was checked against the tool call it came from.

Kinds:
- false_positive: the system behaves as intended (the code shows the rule, and nothing changed
  it); the reply explains the intended behaviour to the customer.
- confirmed_bug: a recent code change broke it. file_line and commit must be copied from the
  codebase analyst's code and git evidence.
- config_incident: a configuration or feature-flag change caused it, not code; the evidence must
  include the flag change.
- inconclusive: the analysts disagree, or the evidence doesn't settle it.
Every kind but inconclusive needs production data (traces, metrics, logs) showing the symptom.

owning_service is one of: {services}. customer_reply is to the tenant's support contact: plain,
no internal names, file paths or commits; for a bug or incident say the team is on it, don't
promise a date. engineering_summary is for the owning team: root cause, evidence refs, and the
fix or rollback.

<brief>
{brief}
</brief>

<handoffs>
{handoffs}
</handoffs>

<findings>
{findings}
</findings>"""


def prompt(state: TicketState) -> str:
    found = [f.model_dump() for f in state.get("findings", [])]
    return PROMPT.format(
        services=", ".join(ownership()),
        brief=state["brief"].text,
        handoffs="\n".join(
            f"round {h.round}: {h.from_agent} asked {h.to_agent}: {h.question}"
            for h in state.get("handoffs", [])
        )
        or "none",
        findings=json.dumps(found, indent=1, default=str),
    )


# Evidence that production shows the symptom, as opposed to what could explain it.
SYMPTOM = {"trace", "metric", "log", "sql"}

HOLDING_REPLY = (
    "Thanks for reporting this. We're looking into it and a specialist will follow up with you "
    "shortly."
)


def _same_place(claimed: str, seen: str) -> bool:
    """The verdict's file:line against a code reference an analyst saw (a line or a range)."""
    path, _, line = claimed.partition(":")
    seen_path, _, seen_lines = seen.partition(":")
    if not (path and (path.endswith(seen_path) or seen_path.endswith(path))):
        return False
    if not line.isdigit() or not seen_lines:
        return True
    first, _, last = seen_lines.partition("-")
    if not first.isdigit():
        return True
    last_n = int(last) if last.isdigit() else int(first)
    return int(first) - 3 <= int(line) <= last_n + 3


def apply_rules(v: Verdict, findings: list[Findings], services: set[str]) -> Verdict:
    """The guardrails, in code: what each kind of verdict needs to stand."""
    evidence = [e for f in findings for e in f.evidence]
    sources = {e.source for e in evidence}
    file_line = v.file_line
    if file_line and not any(_same_place(file_line, e.ref) for e in evidence if e.source == "code"):
        file_line = None
    commit = v.commit
    if commit and not any(same_commit(commit, e.ref) for e in evidence if e.source == "git"):
        commit = None
    checked = v.model_copy(update={"file_line": file_line, "commit": commit})
    if v.kind == "inconclusive":
        return checked

    problems = []
    if v.owning_service not in services:
        problems.append(f"{v.owning_service!r} is not a known service")
    if len(sources) < 2:
        problems.append("fewer than two independent sources")
    if v.kind != "inconclusive" and not sources & SYMPTOM:
        problems.append("production data (traces, metrics, logs) doesn't show the symptom")
    if v.kind == "confirmed_bug" and not (file_line and commit):
        problems.append("no file:line and commit the codebase analyst saw")
    if v.kind == "config_incident" and "flag" not in sources:
        problems.append("no flag change in the evidence")
    if v.kind == "false_positive" and "code" not in sources:
        problems.append("no code showing the behaviour is intended")
    # The codebase analyst's judgment of the code it read: a later round's over an earlier one's,
    # but only about the same code. With questions both ways, a later round may have answered one
    # about another path (ticket 9: production's lookup error, not the listing query), so the
    # judgments that read the verdict's file:line decide when there are any.
    judged = [f for f in findings if f.agent == "codebase_analyst" and f.evidence]
    judged = [f for f in judged if f.intended is not None]
    here = [
        f
        for f in judged
        if file_line
        and any(_same_place(file_line, e.ref) for e in f.evidence if e.source == "code")
    ]
    judged = here or judged
    if judged:
        latest = max(judged, key=lambda f: f.round)
        if v.kind == "confirmed_bug" and latest.intended:
            problems.append(f"the codebase analyst (round {latest.round}) found it intended")
        if v.kind == "false_positive" and not latest.intended:
            problems.append(f"the codebase analyst (round {latest.round}) found a regression")
    if not problems:
        return checked
    return checked.model_copy(
        update={
            "kind": "inconclusive",
            "confidence": min(v.confidence, 0.5),
            "customer_reply": HOLDING_REPLY,
            "engineering_summary": f"Model said {v.kind}"
            + (f" at {v.file_line}" if v.file_line else "")
            + (f" (commit {v.commit})" if v.commit else "")
            + f", but: {'; '.join(problems)}. "
            + (v.engineering_summary or v.root_cause),
        }
    )


async def run(state: TicketState) -> dict:
    found = state.get("findings", [])
    model = None
    if not any(f.evidence for f in found):  # nothing to decide on: no model call
        v = Verdict(
            kind="inconclusive",
            root_cause="No analyst produced checked evidence: "
            + "; ".join(f.hypothesis for f in found),
            owning_service=state["brief"].suspected_service,
            confidence=0.0,
            customer_reply=HOLDING_REPLY,
        )
    else:
        claimed, model = await call("verdict", Verdict, prompt(state))
        v = apply_rules(claimed, found, set(ownership()))
    emit(ModelOutputEvent(stage="verdict", name="Verdict", data=v.model_dump(), model=model))
    return {"verdict": v, "reply": v.customer_reply, "_summary": f"{v.kind} ({v.confidence:.0%})"}
