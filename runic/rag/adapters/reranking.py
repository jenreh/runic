"""Reranker adapters for runic.rag (concept ADR-017).

Two implementations of the :class:`~runic.rag.ports.Reranker` port:

* :class:`RRFReranker` — the default. Fuses several per-retriever
  :class:`~runic.rag.domain.RetrievalContext` objects with Reciprocal Rank
  Fusion (RRF): each item's fused score is the sum of ``1 / (k0 + rank)`` over
  every context it appears in, where *rank* is its 0-based position in that
  context. Entities fuse by ``canonical_key`` and chunks by ``id``. The result
  is one fused context, sorted by descending fused score and truncated to
  ``top_k``. RRF is deterministic and needs no model, which is why it is the
  default. See https://plg.uwaterloo.ca/~gvcormac/cormacksigir09-rrf.pdf.

* :class:`CrossEncoderReranker` — optional. Scores each ``(query, text)`` pair
  with a sentence-transformers cross-encoder. ``sentence-transformers`` is not a
  hard dependency, so it is imported lazily and a clear :class:`RagError`
  explains how to install it when missing.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from runic.rag.domain import (
    ChunkHit,
    EntityHit,
    RelationHit,
    RetrievalContext,
)
from runic.rag.exceptions import RagError

if TYPE_CHECKING:
    from collections.abc import Iterable

log = logging.getLogger(__name__)

__all__ = [
    "CrossEncoderReranker",
    "RRFReranker",
]

_DEFAULT_RRF_K0 = 60
"""Standard RRF rank constant (Cormack et al., 2009)."""


def _merge_relations(contexts: list[RetrievalContext]) -> list[RelationHit]:
    """Union relations across *contexts*, de-duplicated by identity, in order."""
    seen: set[tuple[str, str, str, str]] = set()
    merged: list[RelationHit] = []
    for context in contexts:
        for relation in context.relations:
            identity = (
                relation.source_key,
                relation.target_key,
                relation.rel_type,
                relation.description,
            )
            if identity in seen:
                continue
            seen.add(identity)
            merged.append(relation)
    return merged


class RRFReranker:
    """Reciprocal Rank Fusion reranker — the default :class:`Reranker`.

    Fuses entities (by ``canonical_key``) and chunks (by ``id``) across the
    supplied contexts; relations are de-duplicated by identity. The fused
    ``score`` on each returned hit is the RRF score, so callers can inspect it.

    *k0* is the RRF rank constant (default 60): larger values flatten the
    contribution of top ranks. Output order is fully deterministic — ties on
    fused score break on the key / id (ascending) for stable results.
    """

    def __init__(self, *, k0: int = _DEFAULT_RRF_K0) -> None:
        if k0 <= 0:
            raise ValueError("k0 must be positive")
        self._k0 = k0

    def rerank(
        self, query: str, contexts: list[RetrievalContext], *, top_k: int
    ) -> RetrievalContext:
        """Fuse *contexts* with RRF and return one ``top_k``-trimmed context."""
        if not contexts:
            return RetrievalContext(query=query)

        entities = self._fuse_entities(contexts, top_k=top_k)
        chunks = self._fuse_chunks(contexts, top_k=top_k)
        relations = _merge_relations(contexts)
        log.debug(
            "RRF fused %d contexts -> %d entities, %d chunks, %d relations (k0=%d)",
            len(contexts),
            len(entities),
            len(chunks),
            len(relations),
            self._k0,
        )
        return RetrievalContext(
            query=query,
            entities=entities,
            chunks=chunks,
            relations=relations,
        )

    def _fuse_entities(
        self, contexts: list[RetrievalContext], *, top_k: int
    ) -> list[EntityHit]:
        """Fuse entity hits across *contexts* by ``canonical_key``."""
        scores: dict[str, float] = {}
        first_seen: dict[str, EntityHit] = {}
        for context in contexts:
            for rank, hit in enumerate(context.entities):
                key = hit.canonical_key
                scores[key] = scores.get(key, 0.0) + self._contribution(rank)
                first_seen.setdefault(key, hit)
        ordered = self._ranked_keys(scores)[:top_k]
        return [
            first_seen[key].model_copy(update={"score": scores[key]}) for key in ordered
        ]

    def _fuse_chunks(
        self, contexts: list[RetrievalContext], *, top_k: int
    ) -> list[ChunkHit]:
        """Fuse chunk hits across *contexts* by ``id``."""
        scores: dict[str, float] = {}
        first_seen: dict[str, ChunkHit] = {}
        for context in contexts:
            for rank, hit in enumerate(context.chunks):
                scores[hit.id] = scores.get(hit.id, 0.0) + self._contribution(rank)
                first_seen.setdefault(hit.id, hit)
        ordered = self._ranked_keys(scores)[:top_k]
        return [
            first_seen[key].model_copy(update={"score": scores[key]}) for key in ordered
        ]

    def _contribution(self, rank: int) -> float:
        """RRF contribution of a single appearance at 0-based *rank*.

        The canonical Cormack RRF formula uses 1-based ranks, so the 0-based
        ``rank`` is offset by 1: ``1 / (k0 + rank + 1)``.
        """
        return 1.0 / (self._k0 + rank + 1)

    @staticmethod
    def _ranked_keys(scores: dict[str, float]) -> list[str]:
        """Keys sorted by descending score, ties broken by ascending key."""
        return sorted(scores, key=lambda key: (-scores[key], key))


class CrossEncoderReranker:
    """Cross-encoder reranker backed by sentence-transformers (optional).

    The model is loaded lazily on first use. ``sentence-transformers`` is not a
    runic.rag dependency; when it is missing a :class:`RagError` explains how to
    install it. Entities and chunks are scored independently by their text
    against the query, sorted by descending model score, then truncated to
    ``top_k``. Items are de-duplicated by ``canonical_key`` / ``id`` (best score
    wins). Relations are unioned, mirroring :class:`RRFReranker`.
    """

    _INSTALL_HINT = (
        "CrossEncoderReranker requires the 'sentence-transformers' package. "
        "Install it with: uv add sentence-transformers"
    )

    def __init__(
        self, model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    ) -> None:
        self._model_name = model_name
        self._model: Any | None = None

    def _load_model(self) -> Any:
        """Lazily import sentence-transformers and build the cross-encoder."""
        if self._model is not None:
            return self._model
        try:
            from sentence_transformers import (  # ty: ignore[unresolved-import]
                CrossEncoder,
            )
        except ImportError as exc:  # pragma: no cover - exercised via fake patch
            raise RagError(self._INSTALL_HINT) from exc
        log.debug("Loading cross-encoder model %s", self._model_name)
        self._model = CrossEncoder(self._model_name)
        return self._model

    def rerank(
        self, query: str, contexts: list[RetrievalContext], *, top_k: int
    ) -> RetrievalContext:
        """Score and reorder entities/chunks across *contexts* with the model."""
        if not contexts:
            return RetrievalContext(query=query)

        model = self._load_model()
        entities = self._rerank_entities(model, query, contexts, top_k=top_k)
        chunks = self._rerank_chunks(model, query, contexts, top_k=top_k)
        relations = _merge_relations(contexts)
        return RetrievalContext(
            query=query,
            entities=entities,
            chunks=chunks,
            relations=relations,
        )

    def _rerank_entities(
        self,
        model: Any,
        query: str,
        contexts: list[RetrievalContext],
        *,
        top_k: int,
    ) -> list[EntityHit]:
        """Score deduped entities by ``description`` against *query*."""
        unique = self._dedupe(
            (hit for context in contexts for hit in context.entities),
            key=lambda hit: hit.canonical_key,
        )
        if not unique:
            return []
        scores = model.predict([(query, hit.description) for hit in unique])
        rescored = [
            hit.model_copy(update={"score": float(score)})
            for hit, score in zip(unique, scores, strict=True)
        ]
        rescored.sort(key=lambda hit: (-hit.score, hit.canonical_key))
        return rescored[:top_k]

    def _rerank_chunks(
        self,
        model: Any,
        query: str,
        contexts: list[RetrievalContext],
        *,
        top_k: int,
    ) -> list[ChunkHit]:
        """Score deduped chunks by ``text`` against *query*."""
        unique = self._dedupe(
            (hit for context in contexts for hit in context.chunks),
            key=lambda hit: hit.id,
        )
        if not unique:
            return []
        scores = model.predict([(query, hit.text) for hit in unique])
        rescored = [
            hit.model_copy(update={"score": float(score)})
            for hit, score in zip(unique, scores, strict=True)
        ]
        rescored.sort(key=lambda hit: (-hit.score, hit.id))
        return rescored[:top_k]

    @staticmethod
    def _dedupe[H](items: Iterable[H], *, key: Any) -> list[H]:
        """First-seen de-duplication preserving order."""
        seen: set[str] = set()
        unique: list[H] = []
        for item in items:
            item_key = key(item)
            if item_key in seen:
                continue
            seen.add(item_key)
            unique.append(item)
        return unique
