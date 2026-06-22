"""Add-on one-liner that wires the default stack with the Docling chunker.

:func:`build_graphrag` mirrors :meth:`runic.rag.GraphRAG.with_defaults` but
injects a :class:`~runic_rag_docling.chunker.DoclingChunker` as the
``document_chunker`` — so ``ingest_document`` parses and chunks structure-aware
while everything else stays the batteries-included default (concept §9, variant
B). Users who want parse-only behavior wire :class:`DoclingParser` as
``document_parser`` via the explicit ``GraphRAG`` constructor instead.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .chunker import DoclingChunker
from .settings import DoclingSettings

if TYPE_CHECKING:
    from runic.rag import GraphRAG, Ontology, RagSettings


def build_graphrag(
    settings: RagSettings,
    docling_settings: DoclingSettings | None = None,
    *,
    driver: Any = None,
    ontology: Ontology | None = None,
) -> GraphRAG:
    """Build a default :class:`GraphRAG` with Docling as the document chunker.

    *settings* configures the core stack; *docling_settings* configures the
    Docling adapters (defaults to in-process ``local`` mode). *driver* and
    *ontology* are forwarded to :meth:`GraphRAG.with_defaults` unchanged.
    """
    from runic.rag import GraphRAG

    chunker = DoclingChunker(docling_settings or DoclingSettings())
    return GraphRAG.with_defaults(
        driver,
        settings=settings,
        ontology=ontology,
        document_chunker=chunker,
    )
