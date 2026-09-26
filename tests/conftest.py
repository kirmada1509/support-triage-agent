from datetime import UTC, datetime, timedelta

import pytest
import yaml

from app.models import ContextBundle, Deploy, Ticket
from app.settings import ROOT

NOW = datetime(2026, 9, 23, 10, 20, tzinfo=UTC)


def demo_ticket(n: str) -> Ticket:
    tickets = yaml.safe_load((ROOT / "scenarios" / "tickets.yaml").read_text())["tickets"]
    t = next(t for t in tickets if t["id"] == n)
    return Ticket(
        id=f"T-{n}", tenant_id="figma-merch", subject=t["subject"], body=t["body"], received_at=NOW
    )


@pytest.fixture(autouse=True)
def no_db(request, monkeypatch):
    """The context node reads Postgres; tests hand it a fixed bundle instead (except the
    `db` tests, which use the real thing)."""
    if request.node.get_closest_marker("db"):
        return

    async def fake_fetch_context(ticket, services, hours=24):
        return ContextBundle(
            services=services,
            deploys=[
                Deploy(
                    id=1,
                    service="payment",
                    version="v1.4.0",
                    previous_version="v1.3.0",
                    git_sha="a1b2c3d",
                    deployed_at=NOW - timedelta(minutes=50),
                    commit_titles=["refactor: simplify card expiry comparison"],
                )
            ],
        )

    monkeypatch.setattr("app.nodes.context.fetch_context", fake_fetch_context)
