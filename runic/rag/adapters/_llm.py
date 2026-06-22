"""pydantic-ai model and agent construction for runic.rag.

Builds an OpenAI-compatible chat model and an :class:`~pydantic_ai.Agent` from
:class:`~runic.rag.config.RagSettings`. Two providers are supported:

* ``openai`` (default) — uses ``OPENAI_API_KEY`` and the optional
  ``openai_base_url``.
* ``ollama`` — an OpenAI-compatible endpoint reached via
  :class:`~pydantic_ai.providers.openai.OpenAIProvider` configured with
  ``ollama_base_url`` (default ``http://localhost:11434/v1``).

Verified against pydantic-ai-slim v1.107: ``OpenAIChatModel`` and
``OpenAIProvider`` live at the import paths used below.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from runic.rag.config import RagSettings
from runic.rag.exceptions import ConfigError

log = logging.getLogger(__name__)

__all__ = [
    "build_agent",
    "build_chat_model",
]

_DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434/v1"


def _build_provider(settings: RagSettings) -> OpenAIProvider:
    """Return an OpenAI-compatible provider for the configured LLM backend."""
    if settings.llm_provider == "ollama":
        base_url = settings.ollama_base_url or _DEFAULT_OLLAMA_BASE_URL
        return OpenAIProvider(base_url=base_url, api_key="ollama")

    if not settings.openai_api_key:
        raise ConfigError("OPENAI_API_KEY is required when llm_provider='openai'.")
    return OpenAIProvider(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
    )


def build_chat_model(settings: RagSettings) -> OpenAIChatModel:
    """Construct an :class:`OpenAIChatModel` from *settings*."""
    provider = _build_provider(settings)
    model = OpenAIChatModel(settings.llm_model, provider=provider)
    log.debug(
        "Built chat model %s via provider=%s", settings.llm_model, settings.llm_provider
    )
    return model


def build_agent(
    settings: RagSettings,
    *,
    output_type: Any = None,
    system_prompt: str,
) -> Agent[None, Any]:
    """Construct a pydantic-ai :class:`Agent` over the configured chat model.

    When *output_type* is None the agent yields plain ``str`` output; otherwise
    pydantic-ai validates the model response against the given schema.
    """
    model = build_chat_model(settings)
    if output_type is None:
        return Agent(model, system_prompt=system_prompt)
    return Agent(model, output_type=output_type, system_prompt=system_prompt)
