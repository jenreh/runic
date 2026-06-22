"""Deterministic, network-free fakes implementing the runic.rag ports."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Callable

from runic.rag.domain import Chunk, Extraction, RetrievalContext

__all__ = [
    "FakeEmbedder",
    "FakeExtractor",
    "FakeReranker",
]


class FakeEmbedder:
    """Deterministic embedder: identical text → identical unit vector.

    Similar text need NOT map to similar vectors — only determinism and a
    stable dimension are guaranteed, which is all unit tests rely on.
    """

    def __init__(self, dim: int) -> None:
        if dim <= 0:
            raise ValueError("dim must be positive")
        self._dim = dim

    @property
    def dimension(self) -> int:
        """The fixed embedding dimension."""
        return self._dim

    def embed(self, text: str) -> list[float]:
        """Return a deterministic unit vector for *text*."""
        raw: list[float] = []
        counter = 0
        # Expand a sha256 stream until we have `dim` floats.
        while len(raw) < self._dim:
            digest = hashlib.sha256(f"{text}|{counter}".encode()).digest()
            for byte in digest:
                raw.append((byte / 255.0) * 2.0 - 1.0)
                if len(raw) >= self._dim:
                    break
            counter += 1
        norm = math.sqrt(sum(component * component for component in raw))
        if norm == 0.0:
            # Degenerate; return a canonical basis vector.
            vec = [0.0] * self._dim
            vec[0] = 1.0
            return vec
        return [component / norm for component in raw]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed each string; order matches *texts*."""
        return [self.embed(text) for text in texts]


class FakeExtractor:
    """Extractor returning canned :class:`Extraction` results.

    *canned* may be a mapping from chunk text to an :class:`Extraction`, or a
    callable taking the chunk and returning one. Unknown text yields an empty
    extraction when a mapping is used.
    """

    def __init__(
        self,
        canned: dict[str, Extraction] | Callable[[Chunk], Extraction],
    ) -> None:
        self._canned = canned

    def extract(self, chunk: Chunk, *, entity_types: list[str]) -> Extraction:  # noqa: ARG002
        """Return the canned extraction for *chunk*."""
        # isinstance narrows the union cleanly for the type checker (callable()
        # leaves the dict branch ambiguous); the value is re-narrowed because
        # isinstance(_, dict) loses the dict's value-type generic.
        if isinstance(self._canned, dict):
            match = self._canned.get(chunk.text)
            return match if isinstance(match, Extraction) else Extraction()
        return self._canned(chunk)


class FakeReranker:
    """Passthrough reranker: trims the first context to *top_k* entities/chunks."""

    def rerank(
        self, query: str, contexts: list[RetrievalContext], *, top_k: int
    ) -> RetrievalContext:
        """Return the first context, truncated to *top_k* entities and chunks."""
        if not contexts:
            return RetrievalContext(query=query)
        first = contexts[0]
        return RetrievalContext(
            query=first.query,
            entities=list(first.entities[:top_k]),
            chunks=list(first.chunks[:top_k]),
            relations=list(first.relations),
        )
