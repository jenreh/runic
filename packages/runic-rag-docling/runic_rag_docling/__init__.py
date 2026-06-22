"""Optional Docling adapters for the runic.rag Graph-RAG SDK.

This add-on implements the core file-oriented ports
(:class:`runic.rag.ports.DocumentParser`,
:class:`runic.rag.ports.DocumentChunker`) on top of `Docling
<https://github.com/docling-project/docling>`_, in-process (``local``) or against
``docling-serve`` (``server``). The heavy Docling dependency lives only here and
is imported lazily, so the core stays light.

* :class:`DoclingChunker` — fused parse+chunk (``DocumentChunker``).
* :class:`DoclingParser` — Markdown parsing (``DocumentParser``).
* :class:`DoclingSettings` — add-on configuration (``RUNIC_DOCLING_`` env prefix).
* :class:`LocalDoclingConverter` / :class:`ServerDoclingConverter` — converter
  strategy backing the adapters.
* :func:`build_graphrag` — one-liner building the default stack + Docling.
"""

from __future__ import annotations

from ._converters import LocalDoclingConverter, ServerDoclingConverter
from .chunker import DoclingChunker
from .factory import build_graphrag
from .parser import DoclingParser
from .settings import DoclingSettings

__all__ = [
    "DoclingChunker",
    "DoclingParser",
    "DoclingSettings",
    "LocalDoclingConverter",
    "ServerDoclingConverter",
    "build_graphrag",
]
