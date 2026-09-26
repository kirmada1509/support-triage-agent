"""roles.yaml + models.yaml -> the model each role uses, in both naming schemes.

Pydantic AI takes names like "deepseek:deepseek-flash"; HolmesGPT and mini-swe-agent take LiteLLM
strings like "deepseek/deepseek-flash". Switching provider or model is a config change only.
"""

from dataclasses import dataclass
from decimal import Decimal
from functools import cache

import yaml
from pydantic_ai.models import Model, infer_model
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.usage import UsageLimits

from app.settings import settings


@dataclass(frozen=True)
class ModelSpec:
    key: str
    pydantic_ai: str
    litellm: str
    price: dict


@dataclass(frozen=True)
class RoleSpec:
    role: str
    primary: ModelSpec
    fallback: ModelSpec | None


@cache
def _models() -> dict[str, ModelSpec]:
    raw = yaml.safe_load((settings.config_dir / "models.yaml").read_text())
    return {
        k: ModelSpec(key=k, pydantic_ai=v["pydantic_ai"], litellm=v["litellm"], price=v["price"])
        for k, v in raw.items()
    }


@cache
def _roles() -> dict[str, dict]:
    raw = yaml.safe_load((settings.config_dir / "roles.yaml").read_text())
    profile = settings.role_profile or raw["profile"]
    return raw["profiles"][profile]


def role(name: str) -> RoleSpec:
    r = _roles()[name]
    models = _models()
    fb = r.get("fallback")
    return RoleSpec(role=name, primary=models[r["model"]], fallback=models[fb] if fb else None)


def pydantic_ai_model(role_name: str) -> Model:
    """The role's model for a Pydantic AI Agent, falling back on API errors."""
    spec = role(role_name)
    primary = infer_model(spec.primary.pydantic_ai)
    if spec.fallback is None:
        return primary
    return FallbackModel(primary, infer_model(spec.fallback.pydantic_ai))


def litellm_model(role_name: str) -> str:
    return role(role_name).primary.litellm


def cost_usd(model_key: str, input_tokens: int, output_tokens: int, cached: int = 0) -> float:
    p = _models()[model_key].price
    uncached = max(input_tokens - cached, 0)
    return (
        uncached * p["input"]
        + cached * p.get("cached_input", p["input"])
        + output_tokens * p["output"]
    ) / 1_000_000


# Limits per single-call role; the analysts have their own step limits and a hard timeout.
LIMITS = {
    "enrichment": UsageLimits(request_limit=3, total_tokens_limit=20_000),
    "layer1": UsageLimits(request_limit=3, total_tokens_limit=30_000),
    "requests": UsageLimits(request_limit=3, total_tokens_limit=10_000),
    "findings": UsageLimits(request_limit=3, total_tokens_limit=40_000),
    "verdict": UsageLimits(request_limit=3, total_tokens_limit=40_000, cost_limit=Decimal("0.05")),
}
