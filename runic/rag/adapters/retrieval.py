"""Retriever adapters for runic.rag (concept §10).

Each class implements the :class:`~runic.rag.ports.Retriever` protocol and is
assembled by constructor injection from a :class:`~runic.rag.ports.GraphStore`,
an :class:`~runic.rag.ports.Embedder`, and :class:`~runic.rag.config.RagSettings`.
None of them talk to a backend or network directly — every graph access goes
through the injected store, so they are trivially unit-testable with a fake.

The four strategies, in increasing breadth:

* :class:`VectorRetriever` — semantic seed: embed the query and KNN-search the
  ``Entity`` vector index, then attach the chunks those entities are mentioned in.
* :class:`FulltextRetriever` — lexical seed: fulltext-match the query against the
  ``Entity`` name/description index, then attach mentioning chunks.
* :class:`LocalRetriever` (concept Phase 1) — a vector seed expanded over the
  entity neighbourhood up to ``settings.max_hops``, pulling in neighbour
  entities, the relations traversed, and the chunks for the whole set.
* :class:`HighLevelRetriever` (concept Phase 2, LightRAG-style) — an LLM agent
  extracts thematic keywords from the query; each keyword fulltext-matches
  entities whose neighbourhood is then expanded into a thematic subgraph.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from runic.rag.adapters import _llm
from runic.rag.concurrency import estimate_tokens
from runic.rag.domain import EntityHit, RetrievalContext

if TYPE_CHECKING:
    from pydantic_ai import Agent

    from runic.rag.concurrency import BudgetGuard
    from runic.rag.config import RagSettings
    from runic.rag.domain import ScoredKey
    from runic.rag.ports import Embedder, GraphStore

log = logging.getLogger(__name__)

__all__ = [
    "FulltextRetriever",
    "HighLevelRetriever",
    "LocalRetriever",
    "ThemeKeywords",
    "VectorRetriever",
]

_ENTITY_LABEL = "Entity"
_EMBEDDING_PROP = "embedding"
_NAME_PROP = "name"

_KEYWORD_SYSTEM_PROMPT = (
    "You extract the high-level themes and topics implied by a user's question "
    "about a knowledge graph. Return a short list of concise keyword phrases "
    "(entities, concepts, or topics) that capture what the question is about. "
    "Do not answer the question; only surface the themes to search for."
)


class ThemeKeywords(BaseModel):
    """Structured output schema for :class:`HighLevelRetriever`'s LLM agent."""

    keywords: list[str] = Field(default_factory=list)


def _score_map(scored: list[ScoredKey]) -> dict[str, float]:
    """Map canonical keys to their best (highest) retrieval score."""
    best: dict[str, float] = {}
    for item in scored:
        current = best.get(item.key)
        if current is None or item.score > current:
            best[item.key] = item.score
    return best


def _apply_scores(hits: list[EntityHit], scores: dict[str, float]) -> list[EntityHit]:
    """Rebuild *hits* with retrieval *scores*, ordered by score descending.

    ``GraphStore.get_entities`` hydrates with a placeholder score of ``1.0``;
    this overlays the real seed scores so callers see meaningful ranking.
    """
    rescored = [
        hit.model_copy(update={"score": scores.get(hit.canonical_key, hit.score)})
        for hit in hits
    ]
    rescored.sort(key=lambda hit: hit.score, reverse=True)
    return rescored


class VectorRetriever:
    """Semantic retrieval over the ``Entity`` vector index.

    Embeds the query, KNN-searches entity embeddings, hydrates the matched
    entities with their seed scores, and attaches the chunks they are mentioned
    in (bounded by ``top_k``).
    """

    def __init__(
        self,
        store: GraphStore,
        embedder: Embedder,
        settings: RagSettings,
    ) -> None:
        self._store = store
        self._embedder = embedder
        self._settings = settings

    def retrieve(self, query: str, *, top_k: int) -> RetrievalContext:
        """Return the vector-seeded retrieval context for *query*."""
        query_vec = self._embedder.embed(query)
        scored = self._store.vector_search(
            label=_ENTITY_LABEL,
            prop=_EMBEDDING_PROP,
            query_vec=query_vec,
            k=top_k,
        )
        scores = _score_map(scored)
        keys = list(scores.keys())
        entities = _apply_scores(self._store.get_entities(keys), scores)
        chunks = self._store.chunks_for_entities(keys, limit=top_k)
        log.debug(
            "VectorRetriever: query hit %d entities, %d chunks",
            len(entities),
            len(chunks),
        )
        return RetrievalContext(query=query, entities=entities, chunks=chunks)


class FulltextRetriever:
    """Lexical retrieval over the ``Entity`` fulltext index.

    Fulltext-matches the query against entity name/description, hydrates the
    matched entities with their seed scores, and attaches mentioning chunks.
    Lexical only — it needs no embedder (ISP).
    """

    def __init__(
        self,
        store: GraphStore,
        settings: RagSettings,
    ) -> None:
        self._store = store
        self._settings = settings

    def retrieve(self, query: str, *, top_k: int) -> RetrievalContext:
        """Return the fulltext-seeded retrieval context for *query*."""
        scored = self._store.fulltext_search(
            label=_ENTITY_LABEL,
            prop=_NAME_PROP,
            query=query,
            k=top_k,
        )
        scores = _score_map(scored)
        keys = list(scores.keys())
        entities = _apply_scores(self._store.get_entities(keys), scores)
        chunks = self._store.chunks_for_entities(keys, limit=top_k)
        log.debug(
            "FulltextRetriever: query hit %d entities, %d chunks",
            len(entities),
            len(chunks),
        )
        return RetrievalContext(query=query, entities=entities, chunks=chunks)


class LocalRetriever:
    """Neighbourhood retrieval seeded by a vector search (concept Phase 1).

    Seeds with a KNN vector search, expands the entity neighbourhood up to
    ``settings.max_hops`` to include neighbour entities and the relations
    traversed, then attaches the chunks for the full entity set. Seed entities
    keep their vector scores; expanded neighbours inherit the store's default.
    """

    def __init__(
        self,
        store: GraphStore,
        embedder: Embedder,
        settings: RagSettings,
    ) -> None:
        self._store = store
        self._embedder = embedder
        self._settings = settings

    def retrieve(self, query: str, *, top_k: int) -> RetrievalContext:
        """Return the neighbourhood-expanded retrieval context for *query*."""
        query_vec = self._embedder.embed(query)
        seeds = self._store.vector_search(
            label=_ENTITY_LABEL,
            prop=_EMBEDDING_PROP,
            query_vec=query_vec,
            k=top_k,
        )
        seed_scores = _score_map(seeds)
        seed_keys = list(seed_scores.keys())
        if not seed_keys:
            return RetrievalContext(query=query)

        entities, relations = self._store.expand(
            seed_keys, max_hops=self._settings.max_hops
        )
        entities = _apply_scores(entities, seed_scores)

        all_keys = [hit.canonical_key for hit in entities]
        chunks = self._store.chunks_for_entities(all_keys, limit=top_k)
        log.debug(
            "LocalRetriever: %d seeds -> %d entities, %d relations, %d chunks",
            len(seed_keys),
            len(entities),
            len(relations),
            len(chunks),
        )
        return RetrievalContext(
            query=query,
            entities=entities,
            chunks=chunks,
            relations=relations,
        )


class HighLevelRetriever:
    """Thematic retrieval via LLM-extracted keywords (concept Phase 2).

    An LLM agent extracts theme keywords from the query; each keyword
    fulltext-matches entities, whose neighbourhoods are expanded (up to
    ``settings.max_hops``) into a thematic subgraph. Falls back to the raw
    query as a single keyword when the agent yields nothing. It is lexical +
    LLM only — no embedder needed (ISP).

    Parameters
    ----------
    store, settings:
        The graph store and runtime configuration.
    budget:
        Optional cost guard; the keyword-extraction call is checked before and
        recorded after, so the query path is budgeted like ingestion.
    agent:
        Optional pre-built agent (constructor injection for tests). When
        omitted, one is built lazily on first use — so constructing the
        retriever never requires LLM credentials.
    """

    def __init__(
        self,
        store: GraphStore,
        settings: RagSettings,
        *,
        budget: BudgetGuard | None = None,
        agent: Agent[None, ThemeKeywords] | None = None,
    ) -> None:
        self._store = store
        self._settings = settings
        self._budget = budget
        self._agent = agent

    @property
    def agent(self) -> Agent[None, ThemeKeywords]:
        """Return the keyword agent, building it lazily on first access."""
        if self._agent is None:
            self._agent = _llm.build_agent(
                self._settings,
                output_type=ThemeKeywords,
                system_prompt=_KEYWORD_SYSTEM_PROMPT,
            )
        return self._agent

    def retrieve(self, query: str, *, top_k: int) -> RetrievalContext:
        """Return the thematic-subgraph retrieval context for *query*."""
        keywords = self._extract_keywords(query)
        seed_scores = self._match_keywords(keywords, top_k)
        seed_keys = list(seed_scores.keys())
        if not seed_keys:
            return RetrievalContext(query=query)

        entities, relations = self._store.expand(
            seed_keys, max_hops=self._settings.max_hops
        )
        entities = _apply_scores(entities, seed_scores)

        all_keys = [hit.canonical_key for hit in entities]
        chunks = self._store.chunks_for_entities(all_keys, limit=top_k)
        log.debug(
            "HighLevelRetriever: %d keywords -> %d entities, %d relations",
            len(keywords),
            len(entities),
            len(relations),
        )
        return RetrievalContext(
            query=query,
            entities=entities,
            chunks=chunks,
            relations=relations,
        )

    def _extract_keywords(self, query: str) -> list[str]:
        """Run the agent to surface theme keywords; fall back to the query."""
        if self._budget is not None:
            self._budget.check()
        result = self.agent.run_sync(query)
        if self._budget is not None:
            self._budget.record(llm_calls=1, tokens=estimate_tokens(query))
        keywords = [kw.strip() for kw in result.output.keywords if kw.strip()]
        return keywords or [query]

    def _match_keywords(self, keywords: list[str], top_k: int) -> dict[str, float]:
        """Fulltext-match each keyword to entities, keeping the best score."""
        scores: dict[str, float] = {}
        for keyword in keywords:
            hits = self._store.fulltext_search(
                label=_ENTITY_LABEL,
                prop=_NAME_PROP,
                query=keyword,
                k=top_k,
            )
            for hit in hits:
                current = scores.get(hit.key)
                if current is None or hit.score > current:
                    scores[hit.key] = hit.score
        return scores
