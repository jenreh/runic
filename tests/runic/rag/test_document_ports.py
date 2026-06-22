"""Tests for the file-oriented ingestion ports (``DocumentParser`` /
``DocumentChunker``) and their dispatch in
:meth:`runic.rag.services.ingestion.IngestionService.ingest_document`.

All tests are pure-unit (no DB, no network, no Docling): a fake store records
writes, and fake document ports stand in for an add-on. They assert that
``ingest_document`` routes to the injected ports when they ``supports`` the
path and otherwise falls back to the unchanged built-in loaders.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from runic.rag.adapters.chunking import (
    _ID_TEXT_PREFIX,
    ParagraphChunker,
    _chunk_id,
)
from runic.rag.adapters.resolution import TwoStageResolver
from runic.rag.domain import Chunk
from runic.rag.ports import DocumentChunker, DocumentParser
from runic.rag.services.ingestion import IngestionReport, IngestionService
from tests.runic.rag.fakes import FakeEmbedder, FakeExtractor

if TYPE_CHECKING:
    from runic.rag.config import RagSettings
    from runic.rag.ports import Chunker, Extractor, GraphStore


# ── Fakes for the file-oriented ports ───────────────────────────────────────────


class FakeDocumentChunker:
    """Fake :class:`DocumentChunker`: matches by suffix, returns canned chunks.

    ``chunk_document`` re-tags the canned chunks with the requested *source* and
    the default content-addressed id so the resulting :class:`Chunk` objects are
    valid pipeline input.
    """

    def __init__(self, suffix: str, texts: list[str]) -> None:
        self._suffix = suffix
        self._texts = texts
        self.calls = 0

    def supports(self, source: str) -> bool:
        return source.lower().endswith(self._suffix)

    def chunk_document(
        self, path: str | Path, *, source: str | None = None
    ) -> list[Chunk]:
        self.calls += 1
        src = source or str(path)
        return [
            Chunk(id=_chunk_id(src, seq, text), text=text, seq=seq, source=src)
            for seq, text in enumerate(self._texts)
        ]


class FakeDocumentParser:
    """Fake :class:`DocumentParser`: matches by suffix, returns canned text."""

    def __init__(self, suffix: str, text: str) -> None:
        self._suffix = suffix
        self._text = text
        self.calls = 0

    def supports(self, source: str) -> bool:
        return source.lower().endswith(self._suffix)

    def parse(self, path: str | Path) -> str:  # noqa: ARG002 - canned text
        self.calls += 1
        return self._text


# ── Pipeline doubles (mirroring tests.runic.rag.test_ingestion) ──────────────────


class _RecordingWriter:
    """In-memory writer recording every staged chunk/entity."""

    def __init__(self) -> None:
        self.chunks: dict[str, object] = {}
        self.entities: dict[str, tuple[str, str, str]] = {}

    def add_chunk(self, chunk_node: object) -> None:
        self.chunks[cast("Any", chunk_node).id] = chunk_node

    def upsert_entity(
        self,
        key: str,
        name: str,
        type: str,  # noqa: A002 - mirrors port signature
        description: str,
        embedding: list[float] | None,  # noqa: ARG002 - unused here
    ) -> None:
        self.entities[key] = (name, type, description)

    def relate(
        self,
        src_key: str,
        rel_type: str,
        dst_key: str,
        description: str,
        confidence: float,
        source_chunk: str,
    ) -> None:  # pragma: no cover - no relations in these fakes
        return None

    def mention(self, chunk_id: str, entity_key: str) -> None:
        return None


class _FakeStore:
    """Minimal GraphStore double: vector_search returns nothing (no dedup)."""

    def __init__(self) -> None:
        self.writer_recorder = _RecordingWriter()

    def bootstrap_schema(self) -> None:  # pragma: no cover - unused here
        return None

    def writer(self) -> _FakeStore:
        return self

    def __enter__(self) -> _RecordingWriter:
        return self.writer_recorder

    def __exit__(self, *exc: object) -> None:
        return None

    def vector_search(self, **_kwargs: object) -> list[Any]:
        return []


class _SentinelChunker:
    """Text chunker that fails if used; proves the builtin path was NOT taken.

    ``ingest_document`` must route document files to the document ports or the
    built-in loaders, never to the raw-text :class:`~runic.rag.ports.Chunker`
    with a *path string* as text — so any call here is a bug.
    """

    def split(
        self, text: str, *, source: str
    ) -> list[Chunk]:  # pragma: no cover - must not run
        raise AssertionError("text Chunker.split must not be called for documents")


def _service(
    settings: RagSettings,
    store: _FakeStore,
    *,
    chunker: object,
    document_parser: DocumentParser | None = None,
    document_chunker: DocumentChunker | None = None,
) -> IngestionService:
    """Build an IngestionService over the fake store with canned ports."""
    return IngestionService(
        store=cast("GraphStore", store),
        chunker=cast("Chunker", chunker),
        extractor=cast("Extractor", FakeExtractor({})),
        embedder=FakeEmbedder(settings.embedding_dim),
        resolver=TwoStageResolver(settings),
        settings=settings,
        document_parser=document_parser,
        document_chunker=document_chunker,
    )


# ── Port isinstance smoke checks ─────────────────────────────────────────────────


def test_fakes_satisfy_document_ports() -> None:
    """The fakes structurally satisfy the runtime-checkable ports."""
    assert isinstance(FakeDocumentChunker(".pdf", ["x"]), DocumentChunker)
    assert isinstance(FakeDocumentParser(".pdf", "x"), DocumentParser)


# ── ingest_document dispatch ─────────────────────────────────────────────────────


def test_ingest_document_routes_to_document_chunker(
    rag_settings: RagSettings, tmp_path: Path
) -> None:
    """A supporting DocumentChunker parses+chunks the file; its chunks are written."""
    settings = rag_settings.model_copy(update={"cache_dir": str(tmp_path)})
    store = _FakeStore()
    doc_chunker = FakeDocumentChunker(".pdf", ["alpha body", "beta body"])
    service = _service(
        settings,
        store,
        chunker=_SentinelChunker(),
        document_chunker=doc_chunker,
    )

    report = service.ingest_document("whitepaper.pdf")

    assert isinstance(report, IngestionReport)
    assert report.chunks == 2
    assert doc_chunker.calls == 1
    # The canned chunk ids (source-tagged with the path) are what got written.
    expected_ids = {
        _chunk_id("whitepaper.pdf", seq, text)
        for seq, text in enumerate(["alpha body", "beta body"])
    }
    assert set(store.writer_recorder.chunks) == expected_ids


def test_ingest_document_routes_to_document_parser(
    rag_settings: RagSettings, tmp_path: Path
) -> None:
    """When only a parser supports the path, its text feeds the regular chunker."""
    settings = rag_settings.model_copy(update={"cache_dir": str(tmp_path)})
    store = _FakeStore()
    parser = FakeDocumentParser(".pdf", "parsed document text")
    # A DocumentChunker that does NOT support .pdf must be skipped.
    doc_chunker = FakeDocumentChunker(".docx", ["never"])
    service = _service(
        settings,
        store,
        chunker=ParagraphChunker(settings),
        document_parser=parser,
        document_chunker=doc_chunker,
    )

    report = service.ingest_document("report.pdf")

    assert report.chunks == 1
    assert parser.calls == 1
    assert doc_chunker.calls == 0
    # The single chunk holds the parser's text, tagged with the path source.
    (chunk_node,) = store.writer_recorder.chunks.values()
    assert cast("Any", chunk_node).text == "parsed document text"
    assert cast("Any", chunk_node).source == "report.pdf"


def test_ingest_document_falls_back_to_builtin(
    rag_settings: RagSettings, tmp_path: Path
) -> None:
    """Neither port supports the suffix → the built-in text loader is used."""
    settings = rag_settings.model_copy(update={"cache_dir": str(tmp_path)})
    store = _FakeStore()
    parser = FakeDocumentParser(".pdf", "unused")
    doc_chunker = FakeDocumentChunker(".pdf", ["unused"])
    service = _service(
        settings,
        store,
        chunker=ParagraphChunker(settings),
        document_parser=parser,
        document_chunker=doc_chunker,
    )
    txt = tmp_path / "note.txt"
    txt.write_text("plain text body", encoding="utf-8")

    report = service.ingest_document(txt)

    assert report.chunks == 1
    # Neither document port was consulted for the unsupported .txt suffix.
    assert parser.calls == 0
    assert doc_chunker.calls == 0
    (chunk_node,) = store.writer_recorder.chunks.values()
    assert cast("Any", chunk_node).text == "plain text body"
    assert cast("Any", chunk_node).source == str(txt)


def test_ingest_document_chunker_takes_precedence_over_parser(
    rag_settings: RagSettings, tmp_path: Path
) -> None:
    """When both ports support the path, the fused DocumentChunker wins."""
    settings = rag_settings.model_copy(update={"cache_dir": str(tmp_path)})
    store = _FakeStore()
    parser = FakeDocumentParser(".pdf", "parser text")
    doc_chunker = FakeDocumentChunker(".pdf", ["chunker body"])
    service = _service(
        settings,
        store,
        chunker=_SentinelChunker(),
        document_parser=parser,
        document_chunker=doc_chunker,
    )

    report = service.ingest_document("both.pdf")

    assert report.chunks == 1
    assert doc_chunker.calls == 1
    assert parser.calls == 0


# ── _ingest_chunks empty guard ──────────────────────────────────────────────────


def test_ingest_chunks_empty_guard_touches_nothing(
    rag_settings: RagSettings, tmp_path: Path
) -> None:
    """An empty chunk list returns a zero report without any store interaction."""
    settings = rag_settings.model_copy(update={"cache_dir": str(tmp_path)})
    store = _FakeStore()
    service = _service(settings, store, chunker=_SentinelChunker())

    report = service._ingest_chunks([], source="empty")

    assert report == IngestionReport()
    assert store.writer_recorder.chunks == {}
    assert store.writer_recorder.entities == {}


def test_chunk_id_prefix_constant_is_64() -> None:
    """Pin the shared id formula the add-on must mirror (source|seq|text[:64])."""
    assert _ID_TEXT_PREFIX == 64
    text = "z" * 200
    assert _chunk_id("s", 3, text) == _chunk_id("s", 3, text[:64])
