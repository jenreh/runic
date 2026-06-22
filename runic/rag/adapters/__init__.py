"""runic.rag adapters — concrete implementations of the runic.rag ports.

Adapters wrap external concerns (LLMs, embedding providers, graph dialects,
document loaders) behind the Protocols defined in :mod:`runic.rag.ports`. This
module re-exports the public adapter classes so callers and the facade can wire
them from one place.
"""

from __future__ import annotations

from runic.rag.adapters import documents
from runic.rag.adapters._llm import build_agent, build_chat_model
from runic.rag.adapters.chunking import ParagraphChunker
from runic.rag.adapters.embedding import OllamaEmbedder, OpenAIEmbedder
from runic.rag.adapters.extraction import PydanticAIExtractor
from runic.rag.adapters.reranking import CrossEncoderReranker, RRFReranker
from runic.rag.adapters.resolution import (
    LlmTiebreaker,
    TwoStageResolver,
    normalize_text,
)
from runic.rag.adapters.retrieval import (
    FulltextRetriever,
    HighLevelRetriever,
    LocalRetriever,
    ThemeKeywords,
    VectorRetriever,
)
from runic.rag.adapters.synthesis import PydanticAISynthesizer

__all__ = [
    "CrossEncoderReranker",
    "FulltextRetriever",
    "HighLevelRetriever",
    "LlmTiebreaker",
    "LocalRetriever",
    "OllamaEmbedder",
    "OpenAIEmbedder",
    "ParagraphChunker",
    "PydanticAIExtractor",
    "PydanticAISynthesizer",
    "RRFReranker",
    "ThemeKeywords",
    "TwoStageResolver",
    "VectorRetriever",
    "build_agent",
    "build_chat_model",
    "documents",
    "normalize_text",
]
