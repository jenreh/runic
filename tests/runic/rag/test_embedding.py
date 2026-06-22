"""Unit tests for the OpenAI / Ollama embedding adapters (no network)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from runic.rag.adapters.embedding import OllamaEmbedder, OpenAIEmbedder
from runic.rag.config import RagSettings
from runic.rag.exceptions import ConfigError, RagError


@pytest.fixture(autouse=True)
def _clear_rag_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate from RUNIC_RAG_* / OPENAI / OLLAMA vars and any on-disk .env."""
    import os

    for key in list(os.environ):
        if key.startswith("RUNIC_RAG_") or key in {"OPENAI_API_KEY", "OLLAMA_BASE_URL"}:
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(
        "runic.rag.config.RagSettings.model_config",
        {**RagSettings.model_config, "env_file": None},
    )


@dataclass
class _FakeEmbeddingItem:
    embedding: list[float]
    index: int


@dataclass
class _FakeEmbeddingResponse:
    data: list[_FakeEmbeddingItem]


@dataclass
class _FakeEmbeddings:
    """Records calls and returns canned, deliberately out-of-order responses."""

    dim: int
    calls: list[dict[str, Any]] = field(default_factory=list)
    error: Exception | None = None
    override: _FakeEmbeddingResponse | None = None

    def create(self, *, model: str, input: list[str]) -> _FakeEmbeddingResponse:  # noqa: A002
        self.calls.append({"model": model, "input": list(input)})
        if self.error is not None:
            raise self.error
        if self.override is not None:
            return self.override
        # Return items in reversed index order to prove the adapter sorts.
        items = [
            _FakeEmbeddingItem(embedding=[float(i)] * self.dim, index=i)
            for i in range(len(input))
        ]
        return _FakeEmbeddingResponse(data=list(reversed(items)))


@dataclass
class _FakeClient:
    embeddings: _FakeEmbeddings


def _settings(**overrides: Any) -> RagSettings:
    # ``openai_api_key`` / ``ollama_base_url`` have unprefixed validation
    # aliases, so they must be supplied by their alias name, not field name.
    base: dict[str, Any] = {
        "embedding_dim": 4,
        "embedding_model": "text-embedding-3-small",
        "OPENAI_API_KEY": "sk-test",
    }
    base.update(overrides)
    return RagSettings(**base)


def _make(cls: type, dim: int = 4, **settings_kw: Any) -> tuple[Any, _FakeEmbeddings]:
    fake = _FakeEmbeddings(dim=dim)
    embedder = cls(
        _settings(embedding_dim=dim, **settings_kw), client=_FakeClient(fake)
    )
    return embedder, fake


# ── dimension ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("cls", [OpenAIEmbedder, OllamaEmbedder])
def test_dimension_from_settings(cls: type) -> None:
    embedder, _ = _make(cls, dim=7)
    assert embedder.dimension == 7


# ── request shape & batching ────────────────────────────────────────────────


@pytest.mark.parametrize("cls", [OpenAIEmbedder, OllamaEmbedder])
def test_embed_single_request_shape(cls: type) -> None:
    embedder, fake = _make(cls)
    vector = embedder.embed("hello")
    assert vector == [0.0, 0.0, 0.0, 0.0]
    assert len(fake.calls) == 1
    assert fake.calls[0] == {"model": "text-embedding-3-small", "input": ["hello"]}


@pytest.mark.parametrize("cls", [OpenAIEmbedder, OllamaEmbedder])
def test_embed_batch_single_request(cls: type) -> None:
    embedder, fake = _make(cls)
    vectors = embedder.embed_batch(["a", "b", "c"])
    # One batched request for all three inputs.
    assert len(fake.calls) == 1
    assert fake.calls[0]["input"] == ["a", "b", "c"]
    assert len(vectors) == 3


@pytest.mark.parametrize("cls", [OpenAIEmbedder, OllamaEmbedder])
def test_embed_batch_orders_by_index(cls: type) -> None:
    # The fake returns reversed items; the adapter must restore input order.
    embedder, _ = _make(cls)
    vectors = embedder.embed_batch(["a", "b", "c"])
    assert vectors == [[0.0] * 4, [1.0] * 4, [2.0] * 4]


@pytest.mark.parametrize("cls", [OpenAIEmbedder, OllamaEmbedder])
def test_embed_batch_empty_short_circuits(cls: type) -> None:
    embedder, fake = _make(cls)
    assert embedder.embed_batch([]) == []
    assert fake.calls == []


@pytest.mark.parametrize("cls", [OpenAIEmbedder, OllamaEmbedder])
def test_vectors_are_floats(cls: type) -> None:
    embedder, fake = _make(cls)
    fake.override = _FakeEmbeddingResponse(
        data=[_FakeEmbeddingItem(embedding=[1, 2, 3, 4], index=0)]
    )
    vector = embedder.embed("x")
    assert vector == [1.0, 2.0, 3.0, 4.0]
    assert all(isinstance(value, float) for value in vector)


# ── error handling ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("cls", [OpenAIEmbedder, OllamaEmbedder])
def test_provider_error_wrapped_as_rag_error(cls: type) -> None:
    from openai import APIError

    embedder, fake = _make(cls)
    fake.error = APIError("boom", request=None, body=None)  # ty: ignore[invalid-argument-type]
    with pytest.raises(RagError, match="Embedding request failed"):
        embedder.embed("x")


@pytest.mark.parametrize("cls", [OpenAIEmbedder, OllamaEmbedder])
def test_empty_data_raises_rag_error(cls: type) -> None:
    embedder, fake = _make(cls)
    fake.override = _FakeEmbeddingResponse(data=[])
    with pytest.raises(RagError, match="no data"):
        embedder.embed("x")


@pytest.mark.parametrize("cls", [OpenAIEmbedder, OllamaEmbedder])
def test_size_mismatch_raises_rag_error(cls: type) -> None:
    embedder, fake = _make(cls)
    fake.override = _FakeEmbeddingResponse(
        data=[_FakeEmbeddingItem(embedding=[0.0] * 4, index=0)]
    )
    with pytest.raises(RagError, match="size mismatch"):
        embedder.embed_batch(["a", "b"])


@pytest.mark.parametrize("cls", [OpenAIEmbedder, OllamaEmbedder])
def test_empty_vector_raises_rag_error(cls: type) -> None:
    embedder, fake = _make(cls)
    fake.override = _FakeEmbeddingResponse(
        data=[_FakeEmbeddingItem(embedding=[], index=0)]
    )
    with pytest.raises(RagError, match="empty vector"):
        embedder.embed("x")


# ── client construction (DIP default path) ───────────────────────────────────


def test_openai_requires_api_key() -> None:
    settings = RagSettings(embedding_dim=4, openai_api_key=None)
    with pytest.raises(ConfigError, match="OPENAI_API_KEY"):
        OpenAIEmbedder(settings)


def test_openai_builds_client_with_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_openai(**kwargs: Any) -> _FakeClient:
        captured.update(kwargs)
        return _FakeClient(_FakeEmbeddings(dim=4))

    monkeypatch.setattr("runic.rag.adapters.embedding.OpenAI", fake_openai)
    OpenAIEmbedder(_settings(openai_base_url="https://proxy.example/v1"))
    assert captured["api_key"] == "sk-test"
    assert captured["base_url"] == "https://proxy.example/v1"


def test_ollama_builds_client_with_default_base_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_openai(**kwargs: Any) -> _FakeClient:
        captured.update(kwargs)
        return _FakeClient(_FakeEmbeddings(dim=4))

    monkeypatch.setattr("runic.rag.adapters.embedding.OpenAI", fake_openai)
    OllamaEmbedder(_settings(ollama_base_url=None))
    assert captured["api_key"] == "ollama"
    assert captured["base_url"] == "http://localhost:11434/v1"


def test_ollama_honours_configured_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_openai(**kwargs: Any) -> _FakeClient:
        captured.update(kwargs)
        return _FakeClient(_FakeEmbeddings(dim=4))

    monkeypatch.setattr("runic.rag.adapters.embedding.OpenAI", fake_openai)
    OllamaEmbedder(_settings(OLLAMA_BASE_URL="http://ollama.local:11434/v1"))
    assert captured["base_url"] == "http://ollama.local:11434/v1"
