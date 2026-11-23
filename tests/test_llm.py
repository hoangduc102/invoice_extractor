"""Provider selection in core/llm.py (no network calls: models are only constructed)."""

from __future__ import annotations

import pytest

from core import llm

ENV_VARS = ["LLM_PROVIDER", "LLM_MODEL", "DEFAULT_MODEL", "GOOGLE_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for var in ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    llm.get_chat_model.cache_clear()
    yield
    llm.get_chat_model.cache_clear()


def test_defaults_to_ollama():
    assert llm.get_provider().name == "ollama"
    assert llm.default_model() == "llava"
    assert type(llm.get_chat_model()).__name__ == "ChatOllama"


def test_provider_from_env_is_case_insensitive(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", " Gemini ")
    assert llm.get_provider().name == "gemini"
    assert llm.default_model() == llm.PROVIDERS["gemini"].default_model


def test_unknown_provider():
    with pytest.raises(llm.LLMConfigError, match="Unknown LLM_PROVIDER 'mistral'"):
        llm.get_provider("mistral")


def test_model_overrides(monkeypatch):
    monkeypatch.setenv("DEFAULT_MODEL", "llava:13b")  # legacy setting, Ollama only
    assert llm.default_model("ollama") == "llava:13b"
    assert llm.default_model("openai") == "gpt-4.1-mini"
    monkeypatch.setenv("LLM_MODEL", "custom-model")
    assert llm.default_model("openai") == "custom-model"


@pytest.mark.parametrize(
    "provider, key, class_name",
    [
        ("gemini", "GOOGLE_API_KEY", "ChatGoogleGenerativeAI"),
        ("openai", "OPENAI_API_KEY", "ChatOpenAI"),
        ("anthropic", "ANTHROPIC_API_KEY", "ChatAnthropic"),
    ],
)
def test_cloud_providers_need_a_key(monkeypatch, provider, key, class_name):
    with pytest.raises(llm.LLMConfigError, match=f"{key} is not set"):
        llm.get_chat_model(provider)

    monkeypatch.setenv(key, "test-key")
    model = llm.get_chat_model(provider)
    assert type(model).__name__ == class_name
    assert model.temperature == 0
    assert model.max_retries == llm.CLOUD_MAX_RETRIES


def test_backend_hint_mentions_the_right_fix():
    assert "Ollama is running" in llm.backend_hint("ollama", "llava")
    assert "GOOGLE_API_KEY" in llm.backend_hint("gemini")


def test_eval_model_spec_parsing(monkeypatch):
    from evaluation.evaluate import parse_model_spec

    assert parse_model_spec("gemini/gemini-3.6-flash") == ("gemini", "gemini-3.6-flash")
    assert parse_model_spec("qwen3-vl:2b") == ("ollama", "qwen3-vl:2b")  # Ollama tag kept intact
    assert parse_model_spec("hf.co/org/model") == ("ollama", "hf.co/org/model")  # unknown prefix not split
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    assert parse_model_spec(None) == ("openai", "gpt-4.1-mini")
