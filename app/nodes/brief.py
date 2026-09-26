"""The investigation brief both analysts receive: the customer's words (as data), the time window,
identifiers, the suspected service and the versions it runs, recent changes, and similar past
tickets as hypotheses (never facts). Built in code: everything in it is already checked.
"""

from app.analysts.codebox import running_version
from app.graph.state import TicketState
from app.models import Brief


async def run(state: TicketState) -> dict:
    t, e, c = state["ticket"], state["enrichment"], state["classification"]
    ctx = state.get("context")
    deploys = sorted(ctx.deploys if ctx else [], key=lambda d: d.deployed_at)
    flags = ctx.flag_changes if ctx else []
    service = c.service
    last = next((d for d in reversed(deploys) if d.service == service), None)
    deployed = last.version if last else running_version(service)
    previous = last.previous_version if last else None

    changes = [
        f"- {d.deployed_at:%Y-%m-%d %H:%M} UTC deploy {d.service} "
        f"{d.previous_version or '?'} -> {d.version}: {'; '.join(d.commit_titles) or 'no titles'}"
        for d in deploys
    ] + [
        f"- {f.changed_at:%Y-%m-%d %H:%M} UTC flag {f.flag}: {f.old_variant} -> {f.new_variant}"
        for f in flags
    ]
    past = [
        f"{r.id}: {' '.join(r.text.split())[:300]}"
        for r in state.get("retrieved", [])
        if r.kind == "ticket"
    ][:3]
    text = (
        f"<ticket>\n{t.subject}\n{t.body}\n</ticket>\n"
        f"Symptom: {e.symptom}\n"
        f"Window: {e.window_start:%Y-%m-%d %H:%M} to {e.window_end:%Y-%m-%d %H:%M} UTC "
        f"({e.window_basis})\n"
        f"Identifiers: {e.identifiers or 'none given'}\n"
        f"Suspected service: {service} (likely: {', '.join(e.likely_services) or service}), "
        f"running {deployed}" + (f", deployed over {previous}" if previous else "") + "\n"
        "Changes in the last 24 h:\n" + ("\n".join(changes) or "- none recorded")
    )
    b = Brief(
        text=text,
        suspected_service=service,
        deployed_version=deployed,
        previous_version=previous,
        past_investigations=past,
    )
    return {
        "brief": b,
        "_summary": f"{service} at {deployed}" + (f" (was {previous})" if previous else ""),
    }
