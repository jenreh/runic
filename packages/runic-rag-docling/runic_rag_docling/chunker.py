"""Fused parse+chunk adapter implementing ``runic.rag.DocumentChunker``.

:class:`DoclingChunker` parses an original document **once** into a
``DoclingDocument`` and chunks that structured representation **directly** with
Docling's ``HybridChunker`` — fully structure-aware, with no Markdown re-parse
(ADR-021). Chunk ids reuse the runic.rag default scheme (:func:`make_chunk_id`),
so re-ingesting the same file is idempotent.

Collaborators are injected (DIP): a :class:`_DoclingConverter` and a
``HybridChunker``. When omitted they are built from :class:`DoclingSettings`,
with Docling imported lazily so this module never pulls torch at import time.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from runic.rag import Chunk, RagError

from ._converters import LocalDoclingConverter, ServerDoclingConverter
from ._ids import SUPPORTED_SUFFIXES, make_chunk_id
from .settings import DoclingSettings

if TYPE_CHECKING:
    from pathlib import Path

    from ._converters import _DoclingConverter

log = logging.getLogger(__name__)

__all__ = ["DoclingChunker"]

_HYBRID_INSTALL_HINT = (
    "DoclingChunker requires the 'docling' package for HybridChunker. "
    "Install it with: uv add 'runic-rag-docling[local]'"
)


class DoclingChunker:
    """Structure-aware :class:`~runic.rag.ports.DocumentChunker` via Docling.

    Parses the original document into a ``DoclingDocument`` through the injected
    converter, then walks the ``HybridChunker`` output, contextualizing each raw
    chunk (headings/captions prepended) before wrapping it in a domain
    :class:`~runic.rag.Chunk`. Reading order is preserved and chunk size is
    bounded by ``settings.max_tokens``.
    """

    def __init__(
        self,
        settings: DoclingSettings | None = None,
        *,
        converter: _DoclingConverter | None = None,
        hybrid_chunker: Any | None = None,
    ) -> None:
        self._settings = settings or DoclingSettings()
        self._converter = converter or self._build_converter(self._settings)
        self._hybrid = hybrid_chunker

    @staticmethod
    def _build_converter(settings: DoclingSettings) -> _DoclingConverter:
        """Pick the local or server converter from ``settings.mode``."""
        if settings.mode == "server":
            return ServerDoclingConverter(settings)
        return LocalDoclingConverter(settings)

    def _load_hybrid(self) -> Any:
        """Lazily build the memoized ``HybridChunker`` from settings."""
        if self._hybrid is not None:
            return self._hybrid
        try:
            from docling.chunking import (  # ty: ignore[unresolved-import]
                HybridChunker,
            )
        except ImportError as exc:  # pragma: no cover - exercised via fake patch
            raise RagError(_HYBRID_INSTALL_HINT) from exc
        log.debug(
            "Building HybridChunker (max_tokens=%d, merge_peers=%s)",
            self._settings.max_tokens,
            self._settings.merge_peers,
        )
        self._hybrid = HybridChunker(
            max_tokens=self._settings.max_tokens,
            merge_peers=self._settings.merge_peers,
            tokenizer=self._settings.tokenizer,
        )
        return self._hybrid

    def supports(self, source: str) -> bool:
        """Return whether *source* has a Docling-supported file suffix."""
        return source.lower().endswith(SUPPORTED_SUFFIXES)

    def chunk_document(
        self, path: str | Path, *, source: str | None = None
    ) -> list[Chunk]:
        """Parse *path* once and return its structure-aware ordered chunks."""
        src = source or str(path)
        hybrid = self._load_hybrid()
        # Surface any Docling parse/chunk failure as a typed RagError (the
        # install-hint RagError from _load_hybrid above propagates unchanged);
        # never let a raw provider exception escape the adapter (concept §5.1).
        try:
            doc = self._converter.document_from_path(path)
            chunks: list[Chunk] = []
            for seq, raw in enumerate(hybrid.chunk(doc)):
                body = hybrid.contextualize(raw)
                chunks.append(
                    Chunk(
                        id=make_chunk_id(src, seq, body),
                        text=body,
                        seq=seq,
                        source=src,
                    )
                )
        except RagError:
            raise
        except Exception as exc:
            raise RagError(f"Docling failed to parse or chunk {src}") from exc
        log.debug("Docling chunked %s into %d chunks", src, len(chunks))
        return chunks
