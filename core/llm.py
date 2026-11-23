"""
Pick the vision LLM backend from configuration.

    LLM_PROVIDER=ollama     (default) local models via Ollama, no API key
    LLM_PROVIDER=gemini     Google Gemini API      needs GOOGLE_API_KEY (free tier available)
    LLM_PROVIDER=openai     OpenAI API             needs OPENAI_API_KEY
    LLM_PROVIDER=anthropic  Anthropic Claude API   needs ANTHROPIC_API_KEY

LLM_MODEL overrides the provider's default model. Every backend receives the same
LangChain message (text + base64 image), so the LangGraph pipeline does not change.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv
from langchain_core.language_models.chat_models import BaseChatModel

load_dotenv()

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
REQUEST_TIMEOUT_S = float(os.getenv("LLM_TIMEOUT", "120"))
CLOUD_MAX_RETRIES = 3  # backoff on 429/5xx, e.g. free-tier rate limits


@dataclass(frozen=True)
class Provider:
    name: str
    default_model: str
    api_key_env: str | None
    package: str
    label: str


PROVIDERS: dict[str, Provider] = {
    "ollama": Provider("ollama", "llava", None, "langchain-ollama", "Ollama (local)"),
    "gemini": Provider("gemini", "gemini-3.5-flash-lite", "GOOGLE_API_KEY", "langchain-google-genai", "Google Gemini"),
    "openai": Provider("openai", "gpt-4.1-mini", "OPENAI_API_KEY", "langchain-openai", "OpenAI"),
    "anthropic": Provider(
        "anthropic", "claude-haiku-5-5", "ANTHROPIC_API_KEY", "langchain-anthropic", "Anthropic Claude"
    ),
}


class LLMConfigError(RuntimeError):
    """Misconfiguration the user can fix (unknown provider, missing key or package)."""


def get_provider(name: str | None = None) -> Provider:
    key = (name or os.getenv("LLM_PROVIDER") or "ollama").strip().lower()
    if key not in PROVIDERS:
        raise LLMConfigError(f"Unknown LLM_PROVIDER '{key}'. Choose one of: {', '.join(PROVIDERS)}.")
    return PROVIDERS[key]


def default_model(provider: str | None = None) -> str:
    """LLM_MODEL if set, else DEFAULT_MODEL (legacy Ollama setting), else the provider default."""
    p = get_provider(provider)
    explicit = os.getenv("LLM_MODEL") or (os.getenv("DEFAULT_MODEL") if p.name == "ollama" else None)
    return explicit or p.default_model


def backend_hint(provider: str | None = None, model: str | None = None) -> str:
    """One-line fix-it hint for error messages."""
    p = get_provider(provider)
    model = model or default_model(p.name)
    if p.name == "ollama":
        return f"Check that Ollama is running at {OLLAMA_BASE_URL} and the model '{model}' is pulled."
    return f"Check {p.api_key_env} in .env, that '{model}' is a valid {p.label} model, and your rate limits."


@lru_cache(maxsize=16)
def get_chat_model(provider: str | None = None, model: str | None = None) -> BaseChatModel:
    """Build (and cache) a deterministic chat model for the given provider/model."""
    p = get_provider(provider)
    model = model or default_model(p.name)

    if p.api_key_env and not os.getenv(p.api_key_env):
        raise LLMConfigError(f"{p.api_key_env} is not set. Add it to .env to use LLM_PROVIDER={p.name}.")

    try:
        if p.name == "ollama":
            from langchain_ollama import ChatOllama

            return ChatOllama(model=model, temperature=0, base_url=OLLAMA_BASE_URL)
        if p.name == "gemini":
            from langchain_google_genai import ChatGoogleGenerativeAI

            return ChatGoogleGenerativeAI(
                model=model, temperature=0, timeout=REQUEST_TIMEOUT_S, max_retries=CLOUD_MAX_RETRIES
            )
        if p.name == "openai":
            from langchain_openai import ChatOpenAI

            return ChatOpenAI(model=model, temperature=0, timeout=REQUEST_TIMEOUT_S, max_retries=CLOUD_MAX_RETRIES)
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model=model,
            temperature=0,
            max_tokens=1024,
            timeout=REQUEST_TIMEOUT_S,
            max_retries=CLOUD_MAX_RETRIES,
        )
    except ImportError as exc:
        raise LLMConfigError(f"LLM_PROVIDER={p.name} needs the '{p.package}' package: pip install {p.package}") from exc
