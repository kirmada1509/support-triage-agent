"""Real model calls: the same Pydantic AI code runs on DeepSeek directly and on OpenRouter, and
only ROLE_PROFILE changes. Needs DEEPSEEK_API_KEY and OPENROUTER_API_KEY in .env.agent.

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
        models_config._roles.cache_clear()

    yield use
    models_config._roles.cache_clear()


@pytest.mark.parametrize(
    ("name", "provider", "model"),
    [("cheap", "deepseek", "deepseek-flash"), ("openrouter", "openrouter", "deepseek-v4-flash")],
)
async def test_same_call_on_each_provider(profile, name, provider, model):
    profile(name)
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
