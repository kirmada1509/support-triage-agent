"""config/models.yaml and roles.yaml -> the models each role gets. No model is called here."""

import pytest
from pydantic_ai.models.fallback import FallbackModel

from app import models_config
from app.settings import settings

PROFILES = ("gemini", "openai", "deepseek", "openrouter", "ollama", "ollama-think")


@pytest.fixture(autouse=True)
def keys(monkeypatch):
    """Building a provider needs a key, not a valid one."""
    for env in filter(None, models_config.PROVIDER_KEYS.values()):
        monkeypatch.setenv(env, "test")


@pytest.fixture(autouse=True)
def config(monkeypatch):
    """Set ROLE_PROFILE and ROLE_MODELS for one test."""

    def use(profile: str | None = None, overrides: str | None = None):
        monkeypatch.setattr(settings, "role_profile", profile)
        monkeypatch.setattr(settings, "role_models", overrides)
        models_config._roles.cache_clear()

    use()
    yield use
    models_config._roles.cache_clear()


def test_every_model_caps_its_output():
    """Without max_tokens, OpenRouter reserves 65536 output tokens per request and refuses the
    call once the key's credit can't cover that."""
    for spec in models_config._models().values():
        assert 0 < spec.settings["max_tokens"] <= 8192, spec.key


def test_every_model_has_a_known_provider():
    for spec in models_config._models().values():
        assert spec.provider in models_config.PROVIDER_KEYS, spec.key
        assert spec.litellm.split("/", 1)[0] == {"google": "gemini", "ollama": "ollama_chat"}.get(
            spec.provider, spec.provider
        )


def test_direct_deepseek_models_have_thinking_off():
    """DeepSeek's thinking mode rejects the forced tool choice Pydantic AI uses for typed output."""
    for spec in models_config._models().values():
        if spec.provider == "deepseek":
            assert spec.settings["extra_body"] == {"thinking": {"type": "disabled"}}, spec.key


def test_deepseek_is_the_default():
    assert models_config.required_keys() == {"DEEPSEEK_API_KEY"}


@pytest.mark.parametrize("profile", PROFILES)
def test_every_profile_covers_the_same_roles(config, profile):
    config(profile)
    assert set(models_config._roles()) == set(models_config.LIMITS) | {
        "data_analyst",
        "codebase_analyst",
        "indexer",
    }


@pytest.mark.parametrize(
    ("profile", "keys"),
    [
        ("gemini", {"GEMINI_API_KEY"}),
        ("openai", {"OPENAI_API_KEY"}),
        ("deepseek", {"DEEPSEEK_API_KEY"}),
        ("openrouter", {"OPENROUTER_API_KEY"}),
    ],
)
def test_a_profile_needs_only_its_providers_keys(config, profile, keys):
    """Fallbacks stay on the profile's provider, so switching provider means one key."""
    config(profile)
    assert models_config.required_keys() == keys


@pytest.mark.parametrize(
    ("profile", "system"),
    [
        ("gemini", "google"),
        ("openai", "openai"),
        ("deepseek", "deepseek"),
        ("openrouter", "openrouter"),
    ],
)
def test_a_profile_switches_the_provider(config, profile, system):
    config(profile)
    primary, fallback = models_config.pydantic_ai_model("verdict").models
    assert primary.system == system and fallback.system == system


def test_models_are_built_with_their_settings(config):
    config("deepseek")
    model = models_config.pydantic_ai_model("enrichment")
    assert isinstance(model, FallbackModel)
    primary, _ = model.models
    assert primary.model_name == "deepseek-flash"
    assert primary.settings["extra_body"] == {"thinking": {"type": "disabled"}}


def test_role_models_overrides_single_roles_across_providers(config):
    config("gemini", "data_analyst=gpt-5.4-mini, verdict = or-deepseek-v4-pro")
    assert models_config.litellm_model("data_analyst") == "openai/gpt-5.4-mini"
    assert models_config.role("data_analyst").fallback is None
    assert models_config.pydantic_ai_model("verdict").system == "openrouter"
    assert models_config.litellm_model("codebase_analyst") == "gemini/gemini-3.8-flash"
    assert models_config.required_keys() == {
        "GEMINI_API_KEY",
        "OPENAI_API_KEY",
        "OPENROUTER_API_KEY",
    }


@pytest.mark.parametrize(
    ("profile", "overrides", "error"),
    [
        ("claude", None, "ROLE_PROFILE"),
        (None, "verdict=gpt-9", "gpt-9"),
        (None, "judge=gpt-5.4", "judge"),
        (None, "verdict", "role=model"),
    ],
)
def test_bad_config_fails_loudly(config, profile, overrides, error):
    config(profile, overrides)
    with pytest.raises(ValueError, match=error):
        models_config.role("verdict")


def test_the_analysts_get_their_key_and_request_settings(config):
    """HolmesGPT's container and mini-swe-agent's LiteLLM get what the role's model needs,
    whichever provider it is on."""
    config("deepseek")
    assert models_config.key_envs("data_analyst") == ["DEEPSEEK_API_KEY"]
    assert models_config.litellm_kwargs("codebase_analyst") == {
        "max_tokens": 4096,
        "extra_body": {"thinking": {"type": "disabled"}},
        "drop_params": True,
    }
    config("openai")
    assert models_config.key_envs("codebase_analyst") == ["OPENAI_API_KEY"]
    assert models_config.litellm_kwargs("codebase_analyst") == {
        "max_tokens": 8192,
        "drop_params": True,
    }


def test_missing_keys_names_what_to_set(config, monkeypatch):
    config("openai")
    monkeypatch.delenv("OPENAI_API_KEY")
    assert models_config.missing_keys() == {"OPENAI_API_KEY"}


def test_the_local_profiles_need_no_key(config):
    for profile in ("ollama", "ollama-think"):
        config(profile)
        assert models_config.required_keys() == set()
        assert models_config.key_envs("data_analyst") == []


def test_local_qwen_has_thinking_off_unless_asked(config):
    """Ollama's OpenAI-compatible API takes reasoning_effort in the body; LiteLLM's ollama_chat
    and HolmesGPT (REASONING_EFFORT) take it as a parameter."""
    config("ollama")
    model = models_config.pydantic_ai_model("enrichment")
    assert model.system == "ollama" and model.model_name == "qwen3.5:9b-32k"
    assert model.settings["extra_body"] == {"reasoning_effort": "none"}
    assert models_config.litellm_model("codebase_analyst") == "ollama_chat/qwen3.5:9b-32k"
    assert models_config.litellm_kwargs("codebase_analyst")["reasoning_effort"] == "none"
    assert models_config.container_env("data_analyst")["REASONING_EFFORT"] == "none"
    config("ollama-think")
    assert "reasoning_effort" not in models_config.litellm_kwargs("codebase_analyst")
    assert "REASONING_EFFORT" not in models_config.container_env("data_analyst")


def test_holmes_reaches_the_hosts_ollama(config):
    config("ollama")
    env = models_config.container_env("data_analyst")
    assert env["OLLAMA_API_BASE"] == "http://host.docker.internal:11434"
    assert env["OVERRIDE_MAX_CONTENT_SIZE"] == "32768"
    config("deepseek")
    assert models_config.container_env("data_analyst") == {}


def test_slow_local_models_scale_the_analysts_time_budgets(config):
    """Budgets were set from DeepSeek runs; a local model on a laptop gets proportionally longer
    before a run counts as inconclusive."""
    config("deepseek")
    assert models_config.time_budget("data_analyst", 240) == 240
    config("ollama")
    assert models_config.time_budget("data_analyst", 240) > 240
    assert models_config.time_budget("codebase_analyst", 90) > 90
