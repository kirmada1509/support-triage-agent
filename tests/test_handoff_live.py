"""The two-way analyst handoff, live: tickets 4, 8 and 9 are reproduced against the running shop and
run through the whole graph with ROLE_PROFILE's models (DeepSeek by default; `ollama` runs the
local qwen3.5:9b). Ticket 4 hands production's exact error to the code; 8 and 9 are silent bugs,
where the code finds the change and production has to confirm it. Each run is recorded in
evals/handoff_<profile>.json (kind, service, file, commit, handoffs, seconds) before it is
asserted, so a failing profile still leaves its numbers.

Run with `make test-handoff` (needs make shop-up, make analyst-images and DEEPSEEK_API_KEY; about
15 minutes). PROFILE=ollama uses local qwen instead (make ollama-model): on a 16 GB laptop with
the shop up that takes hours, at about 5 output tokens/s.
"""

import asyncio
import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy.engine import make_url

from app import db, models_config
from app.indexer.__main__ import index_service
from app.nodes._config import ownership
from app.nodes.findings import same_commit
from app.nodes.retrieve import embedder
from app.retrieval import cli as retrieval_cli
from app.retrieval.index import index_help, index_tickets
from app.settings import ROOT, settings
from tests.test_layer2_live import SANDBOX, commit_of, investigate, reproduce, scenario

pytestmark = pytest.mark.handoff


@dataclass(frozen=True)
class Expected:
    service: str
    path: str  # the planted file
    commit_title: str  # the planted commit


TICKETS = {
    "4": Expected("payment", "src/payment/charge.js", "refactor: simplify card expiry comparison"),
    "8": Expected("checkout", "src/checkout/main.go", "chore: tidy up post-order cleanup"),
    "9": Expected(
        "product-catalog",
        "src/product-catalog/main.go",
        "feat: hide unpriced products from the catalog listing",
    ),
}
PROFILE = settings.role_profile or "default"
RESULTS = ROOT / "evals" / f"handoff_{PROFILE}.json"
DIRECTIONS: set[str] = set()


def profile_roles() -> list[str]:
    return list(models_config._roles())


@pytest.fixture(scope="module", autouse=True)
def prepared():
    """A fresh _test database with help, ticket memory and the code index at both tags (no
    service cards: they're orientation only, and a card is a model call per service)."""
    if not (make_url(settings.database_url).database or "").endswith("_test"):
        pytest.fail("DATABASE_URL must name a database ending in _test (make test-handoff)")
    if missing := models_config.missing_keys():
        pytest.fail(f"set {', '.join(sorted(missing))} in .env.agent")
    if not scenario.Shop(scenario.SHOP_URL).reachable():
        pytest.fail("the shop isn't up; run make shop-up")
    if models_config.role("verdict").primary.provider == "ollama":
        try:
            httpx.get(settings.ollama_base_url.removesuffix("/v1") + "/api/tags", timeout=3)
        except httpx.HTTPError:
            pytest.fail("Ollama isn't running; start it and run make ollama-model")

    async def fill():
        await index_help(retrieval_cli.help_sections(), embedder())
        await index_tickets(retrieval_cli.past_tickets(), embedder())
        for tag in ("v1.3.0", "v1.4.0"):
            for service in ownership():
                print(await index_service(SANDBOX, service, tag, cards=False))
        await db.engine.dispose()

    asyncio.run(fill())
    RESULTS.write_text(
        json.dumps(
            {
                "profile": PROFILE,
                "models": sorted({models_config.role(r).primary.key for r in profile_roles()}),
                "started": datetime.now(UTC).isoformat(timespec="seconds"),
                "tickets": {},
            },
            indent=1,
        )
    )


@pytest.fixture(autouse=True)
async def fresh_connections():
    yield
    await db.engine.dispose()  # each test has its own event loop


def record(n: str, state: dict, seconds: float) -> dict:
    """One ticket's result in the eval file, before any assertion."""
    v, e = state.get("verdict"), TICKETS[n]
    handoffs = [f"{h.from_agent}->{h.to_agent} ({h.reason})" for h in state.get("handoffs", [])]
    result = {
        "seconds": round(seconds),
        "lane": state.get("lane"),
        "kind": v.kind if v else None,
        "owning_service": v.owning_service if v else None,
        "file_line": v.file_line if v else None,
        "commit": v.commit if v else None,
        "confidence": v.confidence if v else None,
        "handoffs": handoffs,
        "findings": [
            {
                "agent": f.agent,
                "round": f.round,
                "completed": f.completed,
                "evidence": len(f.evidence),
                "request": f.request,
                "hypothesis": f.hypothesis[:300],
            }
            for f in state.get("findings", [])
        ],
    }
    result["correct"] = bool(
        v
        and v.kind == "confirmed_bug"
        and v.owning_service == e.service
        and e.path in (v.file_line or "")
        and v.commit
        and same_commit(v.commit, commit_of(e.commit_title))
    )
    data = json.loads(RESULTS.read_text())
    data["tickets"][n] = result
    RESULTS.write_text(json.dumps(data, indent=1))
    return result


@pytest.mark.parametrize("n", TICKETS)
async def test_the_analysts_hand_over_and_find_the_bug(n):
    t0 = time.monotonic()
    state = await investigate(n, *reproduce(n))
    result = record(n, state, time.monotonic() - t0)
    DIRECTIONS.update(h.split(" ")[0] for h in result["handoffs"])
    print(f"  handoffs: {result['handoffs']}")
    # a handoff is on demand: when round 1 already settles it, nobody needs to ask
    assert result["correct"], f"expected the planted {TICKETS[n].service} bug: {result}"


def test_both_directions_were_used():
    """At least one ticket needs each direction: production's error to the code, and a question
    about what the code implies back to production."""
    if not DIRECTIONS:
        pytest.skip("no ticket ran")
    assert DIRECTIONS >= {"data_analyst->codebase_analyst", "codebase_analyst->data_analyst"}
