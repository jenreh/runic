"""Ingestion service — the Command side of the runic.rag CQRS-light split.

:class:`IngestionService` orchestrates the write pipeline (concept ADR-003):

1. **Chunk** the source text via the injected :class:`~runic.rag.ports.Chunker`.
2. **Extract** entities/relations from each chunk *in parallel* (ADR-016) with
   :func:`runic.rag.concurrency.parallel_map` (bounded by ``settings.concurrency``),
   then **embed** all chunk texts in a single batched
   :meth:`~runic.rag.ports.Embedder.embed_batch` pass (``settings.embed_batch_size``
   texts per request) rather than one request per chunk — the resolved entity texts
   in stage 3 are batched the same way. Every LLM/embedder request is rate-limited
   (:class:`~runic.rag.concurrency.RateLimiter`), counted against an optional
   :class:`~runic.rag.concurrency.BudgetGuard`, and memoised in a
   :class:`~runic.rag.concurrency.ContentCache` keyed by content hash so
   re-ingesting unchanged text skips the LLM/embedder entirely (cache hits never
   enter a batch).
3. **Resolve** every extracted entity to a canonical key (deterministic key plus
   vector dedup against the store) so surface variants collapse onto one node.
4. **Write** single-threaded inside ONE :meth:`GraphStore.writer` unit of work
   (ADR-004/015): chunk nodes (with embeddings), entity upserts (with
   embeddings), ``RELATES_TO`` edges, and ``MENTIONS`` provenance. Every write is
   a MERGE, so re-ingesting the same text produces no duplicates (idempotent).

The service owns no backend knowledge; all collaborators are injected ports.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from itertools import batched
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

from runic.ogm import Vector
from runic.rag.concurrency import (
    BudgetGuard,
    ContentCache,
    RateLimiter,
    estimate_tokens,
    parallel_map,
)
from runic.rag.domain import Chunk, ExtractedEntity, Extraction
from runic.rag.models import Chunk as ChunkNode
from runic.rag.ontology import Ontology

if TYPE_CHECKING:
    from pathlib import Path

    from runic.rag.config import RagSettings
    from runic.rag.ports import (
        Chunker,
        Embedder,
        EntityResolver,
        Extractor,
        GraphStore,
        Writer,
    )

log = logging.getLogger(__name__)

__all__ = ["IngestionReport", "IngestionService"]


class IngestionReport(BaseModel):
    """Counts of graph elements produced by one :meth:`IngestionService.ingest`.

    The numbers reflect what was *written* this run: ``chunks`` persisted,
    distinct ``entities`` upserted (after resolution), ``relations`` edges
    created, and ``mentions`` provenance edges linking chunks to entities.
    """

    model_config = ConfigDict(frozen=True)

    chunks: int = 0
    entities: int = 0
    relations: int = 0
    mentions: int = 0


@dataclass(frozen=True)
class _ChunkWork:
    """The extraction + embedding outcome for a single chunk."""

    chunk: Chunk
    extraction: Extraction
    embedding: list[float]


class IngestionService:
    """Command-side pipeline turning raw text into graph writes.

    Parameters
    ----------
    store:
        Backend-isolating :class:`~runic.rag.ports.GraphStore`.
    chunker, extractor, embedder, resolver:
        The injected ports composing the pipeline (DIP).
    settings:
        Runtime configuration (concurrency, rate/cost budgets, cache dir,
        ontology-independent knobs).
    budget_guard:
        Optional shared :class:`~runic.rag.concurrency.BudgetGuard`. When omitted
        one is derived from ``settings.max_llm_calls`` / ``settings.max_tokens``.
    ontology:
        The entity-type vocabulary handed to the extractor. Defaults to the
        generic built-in ontology.
    """

    def __init__(
        self,
        store: GraphStore,
        chunker: Chunker,
        extractor: Extractor,
        embedder: Embedder,
        resolver: EntityResolver,
        settings: RagSettings,
        *,
        budget_guard: BudgetGuard | None = None,
        ontology: Ontology | None = None,
    ) -> None:
        self._store = store
        self._chunker = chunker
        self._extractor = extractor
        self._embedder = embedder
        self._resolver = resolver
        self._settings = settings
        self._ontology = ontology or Ontology.default()
        self._budget = budget_guard or BudgetGuard(
            max_llm_calls=settings.max_llm_calls,
            max_tokens=settings.max_tokens,
        )
        self._rate_limiter = RateLimiter(settings.requests_per_minute)
        self._cache = ContentCache(settings.cache_dir)
        self._entity_types = self._ontology.entity_types()

    # ── Public API ────────────────────────────────────────────────────────────

    def ingest(self, text: str, *, source: str) -> IngestionReport:
        """Ingest *text* tagged with *source*; return the write counts.

        Idempotent: re-ingesting identical text MERGEs onto the same nodes/edges,
        so counts stay stable and no duplicates are created.
        """
        chunks = self._chunker.split(text, source=source)
        if not chunks:
            log.debug("No chunks produced for source %s; nothing to ingest", source)
            return IngestionReport()

        # Extraction is the per-chunk LLM call → parallelise it; embedding is then
        # done for ALL chunk texts in one batched pass (ADR-016) instead of one
        # request per chunk.
        extractions = parallel_map(
            self._extract_cached,
            chunks,
            max_workers=self._settings.concurrency,
        )
        chunk_embeddings = self._embed_texts([chunk.text for chunk in chunks])
        works = [
            _ChunkWork(
                chunk=chunk,
                extraction=extraction,
                embedding=chunk_embeddings[chunk.text],
            )
            for chunk, extraction in zip(chunks, extractions, strict=True)
        ]
        report = self._write(works)
        log.info(
            "Ingested source %s: %d chunks, %d entities, %d relations, %d mentions",
            source,
            report.chunks,
            report.entities,
            report.relations,
            report.mentions,
        )
        return report

    def ingest_document(self, path: str | Path) -> IngestionReport:
        """Load a document at *path* (text/markdown/PDF) and ingest it.

        Thin convenience wrapper over :meth:`ingest` using
        :mod:`runic.rag.adapters.documents` for extraction; ``source`` is the
        string form of *path*.
        """
        from runic.rag.adapters import documents

        spec = str(path)
        lowered = spec.lower()
        if lowered.endswith(".pdf"):
            content = documents.load_pdf(path)
        elif lowered.endswith((".md", ".markdown")):
            content = documents.load_markdown(path)
        else:
            content = documents.load_text(path)
        return self.ingest(content, source=spec)

    # ── Stage 2: parallel extract, then batched embed (cached/budgeted/limited) ─

    def _extract_cached(self, chunk: Chunk) -> Extraction:
        """Return the extraction for *chunk*, using the content cache."""
        cache_content = f"extract|{'|'.join(self._entity_types)}|{chunk.text}"
        cached = self._cache.get(cache_content)
        if cached is not None:
            return Extraction.model_validate(cached)

        self._rate_limiter.acquire()
        self._budget.check()
        extraction = self._extractor.extract(chunk, entity_types=self._entity_types)
        # One model call per pass (initial + each gleaning pass); record real
        # usage only after success so a failed call costs nothing (tokens are a
        # tiktoken estimate of the per-pass input).
        calls = 1 + max(0, self._settings.gleaning_passes)
        self._budget.record(llm_calls=calls, tokens=calls * estimate_tokens(chunk.text))
        self._cache.set(cache_content, extraction.model_dump(mode="json"))
        return extraction

    def _embed_texts(self, texts: list[str]) -> dict[str, list[float]]:
        """Embed *texts* in batches; return a ``{text: vector}`` lookup.

        Distinct texts are resolved once. Cache hits are served from the
        :class:`~runic.rag.concurrency.ContentCache` and never re-embedded; the
        remaining texts are split into ``settings.embed_batch_size`` groups, each
        sent as ONE :meth:`Embedder.embed_batch` request that counts as a single
        :class:`~runic.rag.concurrency.RateLimiter`/:class:`BudgetGuard` unit,
        then cached. An all-cached input issues no request at all.
        """
        by_text: dict[str, list[float]] = {}
        pending: list[str] = []
        seen: set[str] = set()
        for text in texts:
            if text in seen:
                continue
            seen.add(text)
            cached = self._cache.get(self._embed_cache_key(text))
            if cached is not None:
                by_text[text] = [float(value) for value in cached]
            else:
                pending.append(text)

        size = self._settings.embed_batch_size
        step = size if size > 0 else len(pending)
        # strict=False: the final group is intentionally short when len(pending)
        # is not a multiple of the batch size.
        for group in batched(pending, max(1, step), strict=False):
            self._rate_limiter.acquire()
            self._budget.check()
            batch = list(group)
            vectors = self._embedder.embed_batch(batch)
            self._budget.record(
                llm_calls=1, tokens=sum(estimate_tokens(t) for t in batch)
            )
            for text, vector in zip(batch, vectors, strict=True):
                self._cache.set(self._embed_cache_key(text), vector)
                by_text[text] = vector
        return by_text

    def _embed_cache_key(self, text: str) -> str:
        """The ContentCache key for the embedding of *text* (model-scoped)."""
        return f"embed|{self._settings.embedding_model}|{text}"

    # ── Stage 3+4: resolve canonical keys, then write one unit of work ──────────

    def _write(self, works: list[_ChunkWork]) -> IngestionReport:
        """Resolve entities and persist everything in one writer UoW."""
        entities = self._collect_entities(works)
        entity_embeddings = self._embed_entities(entities)
        key_by_name = self._resolve_keys(entities, entity_embeddings)

        # Track DISTINCT graph elements written so the report matches what the
        # idempotent MERGEs actually create (re-ingest -> identical counts).
        written_entities: set[str] = set()
        written_relations: set[tuple[str, str, str]] = set()
        written_mentions: set[tuple[str, str]] = set()

        with self._store.writer() as writer:
            for work in works:
                self._write_chunk(writer, work)
                written_entities |= self._write_entities(
                    writer, work, key_by_name, entity_embeddings
                )
                self._write_mentions(writer, work, key_by_name, written_mentions)
                self._write_relations(writer, work, key_by_name, written_relations)

        return IngestionReport(
            chunks=len(works),
            entities=len(written_entities),
            relations=len(written_relations),
            mentions=len(written_mentions),
        )

    @staticmethod
    def _collect_entities(works: list[_ChunkWork]) -> dict[str, ExtractedEntity]:
        """Deduplicate extracted entities across all chunks by surface name."""
        entities: dict[str, ExtractedEntity] = {}
        for work in works:
            for entity in work.extraction.entities:
                entities.setdefault(entity.name, entity)
        return entities

    def _resolve_keys(
        self,
        entities: dict[str, ExtractedEntity],
        entity_embeddings: dict[str, list[float]],
    ) -> dict[str, str]:
        """Map each entity name to its canonical key (deterministic + dedup).

        Uses the embeddings precomputed by :meth:`_embed_entities` (one batched
        pass) for vector dedup, so this loop issues no per-entity embed call.
        """
        keys: dict[str, str] = {}
        for name, entity in entities.items():
            base_key = self._resolver.canonical_key(entity)
            duplicate = self._resolver.find_duplicate(
                entity, entity_embeddings[name], self._store
            )
            keys[name] = duplicate or base_key
        return keys

    def _embed_entities(
        self, entities: dict[str, ExtractedEntity]
    ) -> dict[str, list[float]]:
        """Embed every entity's descriptive text in ONE batched pass, by name.

        All entity texts for the document are embedded together (see
        :meth:`_embed_texts`) and distributed back to each entity name, so a
        document with K distinct entities issues ``ceil(K / embed_batch_size)``
        requests instead of K.
        """
        text_by_name = {
            name: self._entity_text(entity) for name, entity in entities.items()
        }
        vector_by_text = self._embed_texts(list(text_by_name.values()))
        return {name: vector_by_text[text] for name, text in text_by_name.items()}

    @staticmethod
    def _entity_text(entity: ExtractedEntity) -> str:
        """Build the text embedded to represent *entity* for dedup/search."""
        if entity.description:
            return f"{entity.name}: {entity.description}"
        return entity.name

    def _write_chunk(self, writer: Writer, work: _ChunkWork) -> None:
        """MERGE the chunk node (with its embedding) for *work*."""
        node = ChunkNode(
            id=work.chunk.id,
            text=work.chunk.text,
            source=work.chunk.source,
            seq=work.chunk.seq,
            embedding=Vector(work.embedding),
        )
        writer.add_chunk(node)

    def _write_entities(
        self,
        writer: Writer,
        work: _ChunkWork,
        key_by_name: dict[str, str],
        entity_embeddings: dict[str, list[float]],
    ) -> set[str]:
        """Upsert this chunk's entities; return the set of canonical keys."""
        written: set[str] = set()
        for entity in work.extraction.entities:
            key = key_by_name[entity.name]
            writer.upsert_entity(
                key,
                entity.name,
                entity.type,
                entity.description,
                entity_embeddings.get(entity.name),
            )
            written.add(key)
        return written

    def _write_mentions(
        self,
        writer: Writer,
        work: _ChunkWork,
        key_by_name: dict[str, str],
        written: set[tuple[str, str]],
    ) -> None:
        """Link the chunk to each entity it mentions (idempotent MERGE).

        Records each distinct ``(chunk_id, entity_key)`` in *written* so the run
        report counts the provenance edges actually present in the graph.
        """
        for entity in work.extraction.entities:
            edge = (work.chunk.id, key_by_name[entity.name])
            if edge in written:
                continue
            writer.mention(edge[0], edge[1])
            written.add(edge)

    def _write_relations(
        self,
        writer: Writer,
        work: _ChunkWork,
        key_by_name: dict[str, str],
        written: set[tuple[str, str, str]],
    ) -> None:
        """Create RELATES_TO edges for this chunk (idempotent MERGE).

        Relations whose endpoints were not extracted as entities in this run are
        skipped (their keys are unknown, so no valid edge can be merged). Each
        distinct ``(src_key, rel_type, dst_key)`` is recorded in *written* so the
        report counts the edges actually present in the graph.
        """
        for relation in work.extraction.relations:
            src_key = key_by_name.get(relation.source)
            dst_key = key_by_name.get(relation.target)
            if src_key is None or dst_key is None:
                log.debug(
                    "Skipping relation %s -[%s]-> %s: endpoint not extracted",
                    relation.source,
                    relation.rel_type,
                    relation.target,
                )
                continue
            edge = (src_key, relation.rel_type, dst_key)
            if edge in written:
                continue
            writer.relate(
                src_key,
                relation.rel_type,
                dst_key,
                relation.description,
                relation.confidence,
                work.chunk.id,
            )
            written.add(edge)
