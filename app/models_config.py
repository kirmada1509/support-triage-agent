"""roles.yaml + models.yaml -> the model each role uses, in both naming schemes.

Pydantic AI takes names like "openai:gpt-5.4-mini"; HolmesGPT and mini-swe-agent take LiteLLM
strings like "openai/gpt-5.4-mini". Nothing outside the config names a provider: ROLE_PROFILE
picks a set of roles, ROLE_MODELS overrides single roles, and each model carries its own request
settings from models.yaml. `python -m app.models_config` (make models) prints the result.
"""

import os
from dataclasses import dataclass, field
from decimal import Decimal
from functools import cache

import yaml
from pydantic_ai.models import Model, infer_model
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.ollama import OllamaProvider
from pydantic_ai.settings import ModelSettings
from pydantic_ai.usage import UsageLimits

from app.settings import settings

# The environment variable each provider's key is read from, by Pydantic AI and LiteLLM alike.
# A local Ollama needs none.
PROVIDER_KEYS = {
    "google": "GEMINI_API_KEY",
    "openai": "OPENAI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "ollama": None,
}


@dataclass(frozen=True)
class ModelSpec:
    key: str
    pydantic_ai: str
    litellm: str
    price: dict
    settings: ModelSettings
    litellm_args: dict = field(default_factory=dict)  # extra LiteLLM parameters
    container_env: dict = field(default_factory=dict)  # for HolmesGPT's container
    time_scale: float = 1.0  # multiplies the analysts' time budgets (slow local models)

    @property
    def provider(self) -> str:
        return self.pydantic_ai.split(":", 1)[0]

    @property
    def key_env(self) -> str | None:
        return PROVIDER_KEYS[self.provider]


@dataclass(frozen=True)
class RoleSpec:
    role: str
    primary: ModelSpec
    fallback: ModelSpec | None


@cache
def _models() -> dict[str, ModelSpec]:
    raw = yaml.safe_load((settings.config_dir / "models.yaml").read_text())
    return {
        k: ModelSpec(
            key=k,
            pydantic_ai=v["pydantic_ai"],
            litellm=v["litellm"],
            price=v["price"],
            settings=v.get("settings", {}),
            litellm_args=v.get("litellm_args", {}),
            container_env={k: str(e) for k, e in v.get("container_env", {}).items()},
            time_scale=float(v.get("time_scale", 1.0)),
        )
        for k, v in raw.items()
    }


def _overrides() -> dict[str, str]:
    pairs = [p.strip() for p in (settings.role_models or "").split(",") if p.strip()]
    if bad := [p for p in pairs if "=" not in p]:
        raise ValueError(f"ROLE_MODELS: expected role=model, got {bad}")
    return {r.strip(): m.strip() for r, m in (p.split("=", 1) for p in pairs)}


@cache
def _roles() -> dict[str, dict]:
    """The profile's roles with ROLE_MODELS applied, every model checked against models.yaml."""
    raw = yaml.safe_load((settings.config_dir / "roles.yaml").read_text())
    profile = settings.role_profile or raw["profile"]
    if profile not in raw["profiles"]:
        raise ValueError(f"ROLE_PROFILE={profile}: roles.yaml has {', '.join(raw['profiles'])}")
    roles = {k: dict(v) for k, v in raw["profiles"][profile].items()}
    for name, model in _overrides().items():
        if name not in roles:
            raise ValueError(f"ROLE_MODELS: no role {name}; roles are {', '.join(roles)}")
        roles[name] = {"model": model}
    models = _models()
    for name, r in roles.items():
        for key in filter(None, (r["model"], r.get("fallback"))):
            if key not in models:
                raise ValueError(f"{name}: no model {key} in models.yaml")
    return roles


def role(name: str) -> RoleSpec:
    r = _roles()[name]
    models = _models()
    fb = r.get("fallback")
    return RoleSpec(role=name, primary=models[r["model"]], fallback=models[fb] if fb else None)


def _specs(role_name: str) -> list[ModelSpec]:
    spec = role(role_name)
    return [m for m in (spec.primary, spec.fallback) if m]


def key_envs(role_name: str) -> list[str]:
    """The key variables a role's models need, e.g. to pass into an analyst's container."""
    return list(dict.fromkeys(m.key_env for m in _specs(role_name) if m.key_env))


def required_keys() -> set[str]:
    return {env for name in _roles() for env in key_envs(name)}


def missing_keys() -> set[str]:
    return {env for env in required_keys() if not os.environ.get(env)}


# Providers that speak the OpenAI chat API, so their models can be built with settings attached.
_OPENAI_COMPATIBLE = {"openai", "deepseek", "openrouter"}


def build_model(spec: ModelSpec) -> Model:
    provider, name = spec.pydantic_ai.split(":", 1)
    if provider == "ollama":  # a local Ollama's OpenAI-compatible API
        ollama = OllamaProvider(base_url=settings.ollama_base_url)
        return OpenAIChatModel(name, provider=ollama, settings=spec.settings)
    if provider in _OPENAI_COMPATIBLE:
        return OpenAIChatModel(name, provider=provider, settings=spec.settings)
    if provider == "google":  # Gemini API, GEMINI_API_KEY
        return GoogleModel(name, provider="google", settings=spec.settings)
    if spec.settings:
        raise ValueError(f"{spec.key}: settings aren't supported for provider {provider}")
    return infer_model(spec.pydantic_ai)


def pydantic_ai_model(role_name: str) -> Model:
    """The role's model for a Pydantic AI Agent, falling back on API errors."""
    spec = role(role_name)
    primary = build_model(spec.primary)
    if spec.fallback is None:
        return primary
    return FallbackModel(primary, build_model(spec.fallback))


def litellm_model(role_name: str) -> str:
    return role(role_name).primary.litellm


def litellm_kwargs(role_name: str) -> dict:
    """The role's request settings for LiteLLM (mini-swe-agent's model_kwargs); parameters a
    provider doesn't take are dropped rather than refused."""
    spec = role(role_name).primary
    s = spec.settings
    kept = {k: s[k] for k in ("max_tokens", "extra_body") if k in s}
    return kept | spec.litellm_args | {"drop_params": True}


def time_budget(role_name: str, seconds: float) -> float:
    """An analyst node's time budget for the role's model: budgets were measured on hosted
    models, and a local one on a laptop is several times slower."""
    return seconds * role(role_name).primary.time_scale


def container_env(role_name: str) -> dict[str, str]:
    """Settings (not keys) HolmesGPT's container needs for the role's model, e.g. where a local
    model runs and whether it thinks."""
    return dict(role(role_name).primary.container_env)


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
    "classification": UsageLimits(request_limit=3, total_tokens_limit=20_000),
    "layer1": UsageLimits(request_limit=3, total_tokens_limit=30_000),
    "requests": UsageLimits(request_limit=3, total_tokens_limit=10_000),
    "findings": UsageLimits(request_limit=3, total_tokens_limit=40_000),
    "verdict": UsageLimits(request_limit=3, total_tokens_limit=40_000, cost_limit=Decimal("0.05")),
    "indexer": UsageLimits(request_limit=3, total_tokens_limit=120_000),
}


if __name__ == "__main__":
    profile = (
        settings.role_profile
        or yaml.safe_load((settings.config_dir / "roles.yaml").read_text())["profile"]
    )
    print(
        f"profile {profile}"
        + (f", ROLE_MODELS {settings.role_models}" if settings.role_models else "")
    )
    for name in _roles():
        spec = role(name)
        fb = spec.fallback.key if spec.fallback else "-"
        print(f"  {name:17} {spec.primary.key:20} fallback {fb:22} {', '.join(key_envs(name))}")
    missing = missing_keys()
    print("missing keys: " + (", ".join(sorted(missing)) if missing else "none"))
