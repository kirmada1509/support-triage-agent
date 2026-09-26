"""config/models.yaml and roles.yaml -> the models each role gets. No model is called here."""

import pytest
from pydantic_ai.models.fallback import FallbackModel

from app import models_config
from app.settings import settings


@pytest.fixture(autouse=True)
def keys(monkeypatch):
    """Building a provider needs a key, not a valid one."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test")


@pytest.fixture
def profile(monkeypatch):
    def use(name: str | None):
        monkeypatch.setattr(settings, "role_profile", name)
        models_config._roles.cache_clear()

    yield use
    models_config._roles.cache_clear()


def test_every_model_caps_its_output():
    """Without max_tokens, OpenRouter reserves 65536 output tokens per request and refuses the
    call once the key's credit can't cover that."""
    for spec in models_config._models().values():
        assert 0 < spec.settings["max_tokens"] <= 8192, spec.key


def test_direct_deepseek_models_have_thinking_off():
    """DeepSeek's thinking mode rejects the forced tool choice Pydantic AI uses for typed output."""
    for spec in models_config._models().values():
        if spec.pydantic_ai.startswith("deepseek:"):
            assert spec.settings["extra_body"] == {"thinking": {"type": "disabled"}}, spec.key


def test_models_are_built_with_their_settings(profile):
    profile("cheap")
    model = models_config.pydantic_ai_model("enrichment")
    assert isinstance(model, FallbackModel)
    primary, fallback = model.models
    assert primary.system == "deepseek" and primary.model_name == "deepseek-flash"
    assert primary.settings["extra_body"] == {"thinking": {"type": "disabled"}}
    assert fallback.system == "openrouter" and "extra_body" not in fallback.settings


def test_a_profile_switches_the_provider_and_nothing_else(profile):
    roles = {}
    for name in ("cheap", "openrouter"):
        profile(name)
        roles[name] = set(models_config._roles())
        primary = models_config.pydantic_ai_model("verdict").models[0]
        assert primary.system == ("deepseek" if name == "cheap" else "openrouter")
    assert roles["cheap"] == roles["openrouter"]
