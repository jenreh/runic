"""Parse-only adapter implementing ``runic.rag.DocumentParser``.

:class:`DoclingParser` turns an original document into normalized Markdown via
the injected converter and leaves chunking to the core ``Chunker`` (e.g.
``ParagraphChunker``). It is for users who want Docling's structure-aware parsing
but keep the built-in text chunker; for full structure-aware chunks use
:class:`~runic_rag_docling.chunker.DoclingChunker` instead.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from runic.rag import RagError

from ._converters import LocalDoclingConverter, ServerDoclingConverter
from ._ids import SUPPORTED_SUFFIXES
from .settings import DoclingSettings

if TYPE_CHECKING:
    from pathlib import Path

    from ._converters import _DoclingConverter

log = logging.getLogger(__name__)

__all__ = ["DoclingParser"]


class DoclingParser:
    """Markdown-producing :class:`~runic.rag.ports.DocumentParser` via Docling.

    Delegates to the injected converter's ``markdown_from_path``; the converter
    is built from ``settings.mode`` when not supplied (DIP — inject a fake in
    tests). The resulting Markdown then feeds the core ``Chunker``.
    """

    def __init__(
        self,
        settings: DoclingSettings | None = None,
        *,
        converter: _DoclingConverter | None = None,
    ) -> None:
        self._settings = settings or DoclingSettings()
        self._converter = converter or self._build_converter(self._settings)

    @staticmethod
    def _build_converter(settings: DoclingSettings) -> _DoclingConverter:
        """Pick the local or server converter from ``settings.mode``."""
        if settings.mode == "server":
            return ServerDoclingConverter(settings)
        return LocalDoclingConverter(settings)

    def supports(self, source: str) -> bool:
        """Return whether *source* has a Docling-supported file suffix."""
        return source.lower().endswith(SUPPORTED_SUFFIXES)

    def parse(self, path: str | Path) -> str:
        """Return the normalized Markdown for the document at *path*."""
        try:
            markdown = self._converter.markdown_from_path(path)
        except RagError:
            raise
        except Exception as exc:
            raise RagError(f"Docling failed to parse {path}") from exc
        log.debug("Docling parsed %s into %d markdown chars", path, len(markdown))
        return markdown
