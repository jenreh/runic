"""Embedding adapters for runic.rag.

Two interchangeable :class:`~runic.rag.ports.Embedder` implementations, both
backed by the OpenAI Python SDK's sync client (the Ollama variant simply points
that client at an OpenAI-compatible Ollama endpoint):

* :class:`OpenAIEmbedder` (default) — uses ``OPENAI_API_KEY`` and the optional
  ``openai_base_url``.
* :class:`OllamaEmbedder` (opt-in) — an OpenAI-compatible client pointed at
  ``OLLAMA_BASE_URL`` (default ``http://localhost:11434/v1``).

Both batch :meth:`embed_batch` into a single request and surface an empty or
failed provider response as a clear :class:`~runic.rag.exceptions.RagError`.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol

from openai import OpenAI, OpenAIError

from runic.rag.config import RagSettings
from runic.rag.exceptions import ConfigError, RagError

if TYPE_CHECKING:
    from collections.abc import Sequence

log = logging.getLogger(__name__)

__all__ = [
    "OllamaEmbedder",
    "OpenAIEmbedder",
]

_DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434/v1"


class _EmbeddingResponse(Protocol):
    """Structural view of an embeddings response (only ``data`` is read)."""

    @property
    def data(self) -> object: ...


class _Embeddings(Protocol):
    """The ``embeddings`` namespace of an OpenAI-compatible client."""

    def create(self, *, model: str, input: list[str]) -> _EmbeddingResponse: ...  # noqa: A002


class _EmbeddingsClient(Protocol):
    """The narrow slice of the OpenAI client the embedder depends on (ISP)."""

    @property
    def embeddings(self) -> _Embeddings: ...


class _BaseEmbedder:
    """Shared embedding logic over an OpenAI-compatible sync client.

    The concrete subclasses only differ in how the client is constructed; all
    request shaping, batching and error handling lives here (DRY / SRP).
    """

    def __init__(self, settings: RagSettings, client: _EmbeddingsClient) -> None:
        self._model = settings.embedding_model
        self._dim = settings.embedding_dim
        self._client = client

    @property
    def dimension(self) -> int:
        """The dimensionality of vectors produced by this embedder."""
        return self._dim

    def embed(self, text: str) -> list[float]:
        """Embed a single string."""
        return self.embed_batch([text])[0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed many strings in one request; result order matches *texts*."""
        if not texts:
            return []
        try:
            response = self._client.embeddings.create(
                model=self._model,
                input=texts,
            )
        except OpenAIError as exc:
            raise RagError(f"Embedding request failed: {exc}") from exc

        vectors = self._extract_vectors(response, expected=len(texts))
        log.debug(
            "Embedded %d text(s) with model=%s dim=%d",
            len(vectors),
            self._model,
            self._dim,
        )
        return vectors

    def _extract_vectors(
        self, response: _EmbeddingResponse, *, expected: int
    ) -> list[list[float]]:
        """Pull ordered embedding lists out of a provider response.

        Raises :class:`RagError` if the response is empty or its item count
        does not match the number of inputs.
        """
        data: Sequence[object] | None = getattr(response, "data", None)
        if not data:
            raise RagError("Embedding response contained no data.")
        if len(data) != expected:
            raise RagError(
                f"Embedding response size mismatch: expected {expected}, "
                f"got {len(data)}."
            )
        ordered = sorted(data, key=lambda item: getattr(item, "index", 0))
        vectors: list[list[float]] = []
        for item in ordered:
            embedding = getattr(item, "embedding", None)
            if not embedding:
                raise RagError("Embedding response contained an empty vector.")
            vectors.append([float(value) for value in embedding])
        return vectors


class OpenAIEmbedder(_BaseEmbedder):
    """Default embedder using the OpenAI embeddings endpoint."""

    def __init__(
        self, settings: RagSettings, *, client: _EmbeddingsClient | None = None
    ) -> None:
        super().__init__(settings, client or self._build_client(settings))

    @staticmethod
    def _build_client(settings: RagSettings) -> OpenAI:
        """Construct an OpenAI client from *settings* credentials."""
        if not settings.openai_api_key:
            raise ConfigError(
                "OPENAI_API_KEY is required when embedding_provider='openai'."
            )
        return OpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
        )


class OllamaEmbedder(_BaseEmbedder):
    """Opt-in embedder using an OpenAI-compatible Ollama endpoint."""

    def __init__(
        self, settings: RagSettings, *, client: _EmbeddingsClient | None = None
    ) -> None:
        super().__init__(settings, client or self._build_client(settings))

    @staticmethod
    def _build_client(settings: RagSettings) -> OpenAI:
        """Construct an OpenAI-compatible client pointed at the Ollama server."""
        base_url = settings.ollama_base_url or _DEFAULT_OLLAMA_BASE_URL
        return OpenAI(api_key="ollama", base_url=base_url)
