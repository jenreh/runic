"""runic.rag — Graph-RAG SDK built on runic.ogm and runic.migrate.

This package layers entity/relation extraction, embedding, graph storage, and
hybrid (vector + fulltext + graph-expansion) retrieval on top of the runic
graph OGM. The public surface is the :class:`GraphRAG` facade plus the domain
value objects, configuration, ontology, OGM models, default adapters, and ports
needed to extend or test the pipeline.
"""

from __future__ import annotations

from runic.rag.adapters import (
    CrossEncoderReranker,
    FulltextRetriever,
    HighLevelRetriever,
    LocalRetriever,
    OllamaEmbedder,
    OpenAIEmbedder,
    ParagraphChunker,
    PydanticAIExtractor,
    PydanticAISynthesizer,
    RRFReranker,
    TwoStageResolver,
    VectorRetriever,
)
from runic.rag.config import RagSettings, load_settings
from runic.rag.domain import (
    Answer,
    Chunk,
    ChunkHit,
    Citation,
    EntityHit,
    ExtractedEntity,
    ExtractedRelation,
    Extraction,
    RelationHit,
    RetrievalContext,
    ScoredKey,
)
from runic.rag.exceptions import BudgetExceededError, ConfigError, RagError
from runic.rag.facade import GraphRAG
from runic.rag.models import (
    Concept,
    Entity,
    Event,
    Location,
    Organization,
    Person,
    Product,
    RelationEdge,
)
from runic.rag.models import Chunk as ChunkNode
from runic.rag.ontology import Ontology
from runic.rag.ports import (
    Chunker,
    DocumentChunker,
    DocumentParser,
    Embedder,
    EntityResolver,
    Extractor,
    GraphStore,
    Reranker,
    Retriever,
    Synthesizer,
    Writer,
)
from runic.rag.store import GraphStore as GraphStoreAdapter

__all__ = [  # noqa: RUF022
    # Facade
    "GraphRAG",
    # Configuration
    "RagSettings",
    "load_settings",
    # Ontology
    "Ontology",
    # Domain value objects
    "Answer",
    "Chunk",
    "ChunkHit",
    "Citation",
    "EntityHit",
    "ExtractedEntity",
    "ExtractedRelation",
    "Extraction",
    "RelationHit",
    "RetrievalContext",
    "ScoredKey",
    # Exceptions
    "BudgetExceededError",
    "ConfigError",
    "RagError",
    # OGM models
    "ChunkNode",
    "Concept",
    "Entity",
    "Event",
    "Location",
    "Organization",
    "Person",
    "Product",
    "RelationEdge",
    # Default adapters
    "CrossEncoderReranker",
    "FulltextRetriever",
    "HighLevelRetriever",
    "LocalRetriever",
    "OllamaEmbedder",
    "OpenAIEmbedder",
    "ParagraphChunker",
    "PydanticAIExtractor",
    "PydanticAISynthesizer",
    "RRFReranker",
    "TwoStageResolver",
    "VectorRetriever",
    # Ports + store
    "Chunker",
    "DocumentChunker",
    "DocumentParser",
    "Embedder",
    "EntityResolver",
    "Extractor",
    "GraphStore",
    "GraphStoreAdapter",
    "Reranker",
    "Retriever",
    "Synthesizer",
    "Writer",
]
