"""Unit tests for :class:`~runic.rag.facade.GraphRAG` construction helpers.

These need no live backend and make no network calls — both embedder
constructors only build a (lazy) OpenAI-compatible client object. They pin the
``embedding_provider`` dispatch so the batteries-included path can run fully
offline against Ollama.

Field values are forced via ``model_copy`` rather than the constructor so the
tests are deterministic regardless of any ambient ``.env`` / ``OPENAI_API_KEY``.
"""

from __future__ import annotations

import pytest

from runic.rag.adapters import OllamaEmbedder, OpenAIEmbedder
from runic.rag.config import RagSettings
from runic.rag.exceptions import ConfigError
from runic.rag.facade import GraphRAG


def test_build_embedder_selects_ollama() -> None:
    """``embedding_provider='ollama'`` builds an OllamaEmbedder (no OpenAI key)."""
    settings = RagSettings().model_copy(
        update={"embedding_provider": "ollama", "openai_api_key": None}
    )

    embedder = GraphRAG._build_embedder(settings)

    assert isinstance(embedder, OllamaEmbedder)


def test_build_embedder_defaults_to_openai() -> None:
    """The default embedding provider stays OpenAI."""
    settings = RagSettings().model_copy(
        update={"embedding_provider": "openai", "openai_api_key": "sk-test"}
    )

    embedder = GraphRAG._build_embedder(settings)

    assert isinstance(embedder, OpenAIEmbedder)


def test_build_embedder_openai_still_requires_key() -> None:
    """Selecting the OpenAI embedder without a key fails fast (unchanged contract)."""
    settings = RagSettings().model_copy(
        update={"embedding_provider": "openai", "openai_api_key": None}
    )

    with pytest.raises(ConfigError):
        GraphRAG._build_embedder(settings)
