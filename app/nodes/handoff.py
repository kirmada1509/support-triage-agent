"""The analysts' handoff: after a round, one analyst may need something only the other can check.
Code decides from the checked Findings who answers what next, with no model call:

1. data -> code: the exact error production showed, until the code has located it, if the code
   index places it in the suspected service (or can't place it);
2. an analyst's own question (the ASK line of its answer), newest round first;
3. code -> data: the code found a regression but production hasn't shown the symptom yet (the
   safety net for an analyst that forgets to ask).

A question is asked once, each analyst answers at most MAX_PER_ANALYST, the loop stops after
MAX_HANDOFFS, and an analyst that ran out of budget on a question isn't asked another.
routes.pick_handoff sends the question to code_followup or data_followup, and both come back here.
"""

import re
from collections import Counter
from collections.abc import Callable

from app import db
from app.events import ModelOutputEvent
from app.graph.state import TicketState
from app.graph.stream import emit
from app.indexer import build
from app.indexer.__main__ import sandbox_dir
from app.models import Findings, Handoff
from app.nodes.duplicates import error_signature
from app.nodes.verdict import SYMPTOM

STAGE = "handoff"
MAX_HANDOFFS = 3
MAX_PER_ANALYST = 2
OTHER = {"data_analyst": "codebase_analyst", "codebase_analyst": "data_analyst"}
LABEL = {"data_analyst": "data analyst", "codebase_analyst": "codebase analyst"}
MIN_TEMPLATE = 12  # a shorter error template ("not found") would match too much


async def error_templates(version: str) -> list[tuple[str, str]]:
    """(service, error template) for every service in the code index at a tag; tests replace it."""
    try:
        sha = build.resolve(sandbox_dir(), version)
    except Exception:  # no fork or no such tag: nothing to place an error with
        return []
    return [(ix.service, e.text) for ix in await db.load_code_index(sha) for e in ix.errors]


# What's left of a placeholder after error_signature: a number (#), an ID, or Go's %v verbs.
_HOLE = re.compile(r"%[-+# 0-9.]*[a-z]|#|<id>")


def _pieces(template: str) -> list[str]:
    return [p for p in _HOLE.split(error_signature(template)) if p.strip()]


def origin(error_text: str, templates: list[tuple[str, str]]) -> str | None:
    """The service whose code produced an error: the most specific template whose fixed text the
    message contains in order (a wrapped error contains its caller's template too, but that one
    has less fixed text)."""
    seen = error_signature(error_text)
    matches = []
    for service, template in templates:
        pieces = _pieces(template)
        literal = sum(len(p) for p in pieces)
        if literal >= MIN_TEMPLATE and re.search(".*?".join(map(re.escape, pieces)), seen):
            matches.append((literal, service))
    return max(matches)[1] if matches else None


def _key(question: str) -> str:
    return " ".join(re.findall(r"\w+", question.lower()))


def _located(found: list[Findings], error_text: str) -> bool:
    """The codebase analyst found where the code produces this error."""
    signature = error_signature(error_text)
    return any(
        f.agent == "codebase_analyst"
        and f.error_text
        and error_signature(f.error_text) == signature
        and any(e.source == "code" for e in f.evidence)
        for f in found
    )


def _candidates(found: list[Findings], rnd: int, about: Callable[[str], bool]):
    newest = sorted(found, key=lambda f: f.round, reverse=True)
    error_text = next(
        (f.error_text for f in newest if f.agent == "data_analyst" and f.error_text), None
    )
    if error_text and not _located(found, error_text) and about(error_text):
        yield Handoff(
            round=rnd,
            from_agent="data_analyst",
            to_agent="codebase_analyst",
            question=f'Production shows this exact error: "{error_text}". Where does the code '
            "produce it, and did a recent commit change that path?",
            reason="error_text",
        )
    for f in newest:
        if f.request:
            yield Handoff(
                round=rnd,
                from_agent=f.agent,
                to_agent=OTHER[f.agent],
                question=f.request,
                reason="request",
            )
    regressions = [
        f
        for f in newest
        if f.agent == "codebase_analyst"
        and f.intended is False
        and any(e.source == "code" for e in f.evidence)
    ]
    shown = any(e.source in SYMPTOM for f in found if f.agent == "data_analyst" for e in f.evidence)
    if regressions and not shown:
        f = regressions[0]
        refs = ", ".join(e.ref for e in f.evidence if e.source in ("code", "git"))
        yield Handoff(
            round=rnd,
            from_agent="codebase_analyst",
            to_agent="data_analyst",
            question=f"The code shows a regression: {f.hypothesis} ({refs}). Does production "
            "show it? Compare the requests this code path handles before and after the deploy: "
            "counts, and one trace or log from each side.",
            reason="confirm_regression",
        )


def next_handoff(
    found: list[Findings],
    asked: list[Handoff],
    about: Callable[[str], bool] = lambda error_text: True,
) -> Handoff | None:
    """The next question between the analysts, or None when they're done. `about` says whether a
    production error belongs to the ticket's service, so it's worth finding in the code."""
    if len(asked) >= MAX_HANDOFFS:
        return None
    rnd = max([f.round for f in found] + [h.round for h in asked] + [1]) + 1
    done = {(h.to_agent, _key(h.question)) for h in asked}
    answered = Counter(h.to_agent for h in asked)
    spent = {f.agent for f in found if f.round > 1 and not f.completed}
    for h in _candidates(found, rnd, about):
        if answered[h.to_agent] >= MAX_PER_ANALYST or h.to_agent in spent:
            continue
        if (h.to_agent, _key(h.question)) not in done:
            return h
    return None


def shared_findings(found: list[Findings], agent: str) -> str:
    """What one analyst has found so far, for the other: checked findings only, newest first."""
    lines = []
    for f in sorted(found, key=lambda f: f.round, reverse=True):
        if f.agent != agent or not f.completed:
            continue
        lines.append(f"- round {f.round}: {f.hypothesis} (confidence {f.confidence:.1f})")
        if f.error_text:
            lines.append(f'  exact error seen: "{f.error_text}"')
        lines += [f"  {e.source} {e.ref}: {e.observation}" for e in f.evidence]
    return "\n".join(lines)


async def run(state: TicketState) -> dict:
    found = state.get("findings", [])
    b = state["brief"]
    templates = []
    if any(f.error_text for f in found if f.agent == "data_analyst"):
        templates = await error_templates(b.deployed_version)

    def about(error_text: str) -> bool:
        return origin(error_text, templates) in (None, b.suspected_service)

    h = next_handoff(found, state.get("handoffs", []), about)
    if h is None:
        return {"handoff": None, "_summary": f"{len(found)} findings; no open questions"}
    emit(ModelOutputEvent(stage=STAGE, name="Handoff", data=h.model_dump()))
    return {
        "handoff": h,
        "handoffs": [h],
        "_summary": f"{LABEL[h.from_agent]} asks the {LABEL[h.to_agent]}: {h.question[:90]}",
    }
