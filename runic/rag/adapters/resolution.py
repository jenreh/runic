"""Entity resolution adapter (ADR-014): the two-stage resolver.

:class:`TwoStageResolver` implements the :class:`~runic.rag.ports.EntityResolver`
port and decides the canonical identity of an extracted entity in two stages:

1. **Deterministic key.** ``canonical_key`` is ``type + normalized name`` where the
   name (and type) are normalized by Unicode NFKC, casefolding, and whitespace
   collapse. This alone deduplicates exact and trivially-different surface forms
   without any network call.
2. **Vector duplicate detection.** ``find_duplicate`` runs a KNN search over the
   ``Entity.embedding`` vector index *within the same entity type* and merges a
   candidate when its normalized cosine similarity is ``>= resolve_threshold``.
   Hits matching the entity's own canonical key are ignored (a self-match must
   never count as a duplicate).
3. **Optional LLM tiebreak.** When ``settings.llm_tiebreak`` is enabled, a grey
   band ``[tiebreak_low, tiebreak_high)`` is resolved by an injected
   :class:`LlmTiebreaker` (DIP). The tiebreak is off by default; with no
   tiebreaker wired it conservatively declines to merge.

All thresholds come from :class:`~runic.rag.config.RagSettings`. The resolver
performs no I/O itself: the vector search is delegated to the injected
:class:`~runic.rag.ports.GraphStore`, keeping it trivially unit-testable.
"""

from __future__ import annotations

import logging
import unicodedata
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from runic.rag.domain import ExtractedEntity

if TYPE_CHECKING:
    from runic.rag.config import RagSettings
    from runic.rag.ports import VectorSearcher

log = logging.getLogger(__name__)

__all__ = [
    "LlmTiebreaker",
    "TwoStageResolver",
    "normalize_text",
]

# Label/prop of the OGM Entity vector index (see runic.rag.models.Entity).
_ENTITY_LABEL = "Entity"
_EMBEDDING_PROP = "embedding"
# How many neighbours to fetch; a couple extra absorbs the self-match.
_SEARCH_K = 5


def normalize_text(value: str) -> str:
    """Normalize *value* for deterministic keys.

    Applies Unicode NFKC normalization, casefolding (a stronger, locale-agnostic
    lower-casing), and whitespace collapse so that surface variants such as
    ``"  Café "``, ``"CAFÉ"`` and ``"café"`` all map onto one token.
    """
    normalized = unicodedata.normalize("NFKC", value)
    folded = normalized.casefold()
    return " ".join(folded.split())


@runtime_checkable
class LlmTiebreaker(Protocol):
    """Resolves grey-band duplicate decisions with an LLM judgement.

    Implementations decide whether *entity* denotes the same real-world thing as
    the candidate identified by *candidate_key*. Returning the candidate key
    merges; returning ``None`` keeps them distinct.
    """

    def same_entity(self, entity: ExtractedEntity, candidate_key: str) -> str | None:
        """Return *candidate_key* to merge, or ``None`` to keep distinct."""
        ...


class TwoStageResolver:
    """Deterministic-key + vector-similarity entity resolver (ADR-014).

    Parameters
    ----------
    settings:
        Supplies ``resolve_threshold``, ``tiebreak_low``, ``tiebreak_high`` and
        the ``llm_tiebreak`` toggle.
    tiebreaker:
        Optional grey-band judge consulted only when ``llm_tiebreak`` is on.
    """

    def __init__(
        self,
        settings: RagSettings,
        *,
        tiebreaker: LlmTiebreaker | None = None,
    ) -> None:
        self._settings = settings
        self._tiebreaker = tiebreaker

    # ── Stage 1: deterministic canonical key ──────────────────────────────────

    def canonical_key(self, entity: ExtractedEntity) -> str:
        """Return ``"{normalized type}:{normalized name}"`` for *entity*.

        Both the type and the name are normalized (NFKC + casefold + whitespace
        collapse), so the key is stable across surface-form variation and never
        contains leading/trailing or repeated whitespace.
        """
        return f"{normalize_text(entity.type)}:{normalize_text(entity.name)}"

    # ── Stage 2: vector duplicate detection ───────────────────────────────────

    def find_duplicate(
        self,
        entity: ExtractedEntity,
        embedding: list[float],
        store: VectorSearcher,
    ) -> str | None:
        """Return the canonical key of an existing duplicate, or ``None``.

        Searches the entity vector index restricted to *entity*'s type, ignores
        any hit that is the entity's own key, then merges the best remaining hit
        when its score clears ``resolve_threshold``. Scores in the grey band are
        deferred to the optional LLM tiebreaker (when enabled).
        """
        own_key = self.canonical_key(entity)
        hits = store.vector_search(
            label=_ENTITY_LABEL,
            prop=_EMBEDDING_PROP,
            query_vec=embedding,
            k=_SEARCH_K,
            type_filter=entity.type,
        )
        # vector_search returns descending scores; the first non-self hit is the
        # strongest candidate.
        best = next((hit for hit in hits if hit.key != own_key), None)
        if best is None:
            return None

        threshold = self._settings.resolve_threshold
        if best.score >= threshold:
            log.debug(
                "Resolved duplicate %s -> %s (score=%.4f >= %.4f)",
                own_key,
                best.key,
                best.score,
                threshold,
            )
            return best.key

        if self._in_tiebreak_band(best.score):
            return self._tiebreak(entity, best.key, best.score)

        return None

    # ── Internals ──────────────────────────────────────────────────────────────

    def _in_tiebreak_band(self, score: float) -> bool:
        """Whether *score* falls in the grey band ``[low, high)``."""
        return self._settings.tiebreak_low <= score < self._settings.tiebreak_high

    def _tiebreak(
        self, entity: ExtractedEntity, candidate_key: str, score: float
    ) -> str | None:
        """Resolve a grey-band candidate via the LLM tiebreaker, if enabled."""
        if not self._settings.llm_tiebreak:
            log.debug(
                "Grey-band score %.4f for %s; llm_tiebreak off, not merging",
                score,
                candidate_key,
            )
            return None
        if self._tiebreaker is None:
            log.warning(
                "llm_tiebreak enabled but no tiebreaker injected; not merging %s",
                candidate_key,
            )
            return None
        decision = self._tiebreaker.same_entity(entity, candidate_key)
        log.debug(
            "LLM tiebreak for %s (score=%.4f) -> %s",
            candidate_key,
            score,
            decision,
        )
        return decision
