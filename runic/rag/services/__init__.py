"""runic.rag services — ingestion and retrieval orchestration.

Services compose ports (chunker, extractor, embedder, store, retriever, ...)
into end-to-end pipelines. This module re-exports the public service classes.
"""

from __future__ import annotations

from runic.rag.services.ingestion import IngestionReport, IngestionService
from runic.rag.services.retrieval import RetrievalService

__all__ = [
    "IngestionReport",
    "IngestionService",
    "RetrievalService",
]
