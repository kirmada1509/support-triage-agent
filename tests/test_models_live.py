"""Real model calls: the same Pydantic AI code runs on each provider's profile, and only
ROLE_PROFILE changes. A profile whose key isn't in .env.agent is skipped.

Run with `make test-llm` (a few calls, a fraction of a cent).
"""

from typing import Literal

import pytest
from pydantic import BaseModel
from pydantic_ai import Agent

from app import models_config
from app.settings import settings
from tests.conftest import demo_ticket

pytestmark = pytest.mark.llm


class Triage(BaseModel):
    ticket_type: Literal["how_to", "tech_issue", "request"]
    service: Literal["payment", "checkout", "cart", "quote", "product-catalog", "other"]


@pytest.fixture
def profile(monkeypatch):
    def use(name: str):
        monkeypatch.setattr(settings, "role_profile", name)
        monkeypatch.setattr(settings, "role_models", None)
        models_config._roles.cache_clear()

    yield use
    models_config._roles.cache_clear()


@pytest.mark.parametrize(
    ("name", "provider", "model"),
    [
        ("gemini", "google", "gemini-3.1-flash-lite"),
        ("openai", "openai", "gpt-5.4-mini"),
        ("deepseek", "deepseek", "deepseek-flash"),
        ("openrouter", "openrouter", "deepseek-v4-flash"),
    ],
)
async def test_same_call_on_each_provider(profile, name, provider, model):
    profile(name)
    if missing := set(models_config.key_envs("enrichment")) & models_config.missing_keys():
        pytest.skip(f"no {', '.join(missing)}")
    spec = models_config.role("enrichment")
    assert spec.primary.pydantic_ai.startswith(f"{provider}:")
    agent = Agent(models_config.pydantic_ai_model("enrichment"), output_type=Triage)
    t = demo_ticket("4")
    result = await agent.run(
        f"Classify this support ticket.\n<ticket>{t.subject}\n{t.body}</ticket>",
        usage_limits=models_config.LIMITS["enrichment"],
    )
    # the plumbing, not the judgment (that's the evals' job): a typed answer, from this model
    assert isinstance(result.output, Triage) and result.output.ticket_type == "tech_issue"
    assert model in result.response.model_name


async def test_payment_service_card_names_only_the_accepted_cards():
    """A real service card for payment at v1.4.0 (needs make sandbox): it states the card-type
    rule as the code does, Visa and Mastercard only, which tickets 1 and 3 depend on."""
    from app.indexer import build, card
    from app.indexer.__main__ import sandbox_dir
    from app.nodes._config import ownership

    if missing := set(models_config.key_envs("indexer")) & models_config.missing_keys():
        pytest.skip(f"no {', '.join(missing)}")
    if not (sandbox_dir() / ".git").exists():
        pytest.skip("no fork; run make sandbox")
    index = build.index_at(sandbox_dir(), "payment", "src/payment", "v1.4.0")
    text = (await card.write_card(index, ownership()["payment"]["description"])).lower()
    assert "visa" in text and "mastercard" in text
    assert not any(other in text for other in ("amex", "american express", "discover"))
