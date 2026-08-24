"""Configuration for runic.rag via pydantic-settings.

All ``RUNIC_RAG_*`` environment variables map onto :class:`RagSettings`
field names (env_prefix ``RUNIC_RAG_``). ``OPENAI_API_KEY`` and
``OLLAMA_BASE_URL`` are read UNPREFIXED so they match the conventions of the
underlying OpenAI / Ollama clients (the ``RUNIC_RAG_``-prefixed form and direct
keyword init are also accepted via ``populate_by_name``). Defaults mirror
``.env.example`` exactly.
"""

from __future__ import annotations

import logging
from typing import Literal

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

log = logging.getLogger(__name__)

__all__ = [
    "RagSettings",
    "load_settings",
]


class RagSettings(BaseSettings):
    """Strongly-typed runtime configuration for the Graph-RAG SDK.

    Field names mirror the ``RUNIC_RAG_*`` variables in ``.env.example``.
    ``openai_api_key`` reads the unprefixed ``OPENAI_API_KEY``; ``ollama_base_url``
    reads the unprefixed ``OLLAMA_BASE_URL``.
    """

    model_config = SettingsConfigDict(
        env_prefix="RUNIC_RAG_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
    )

    # ── LLM provider ────────────────────────────────────────────────────────
    llm_provider: Literal["openai", "ollama"] = "openai"
    llm_model: str = "gpt-5.4-nano"

    # ── Embeddings ──────────────────────────────────────────────────────────
    embedding_provider: Literal["openai", "ollama"] = "openai"
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 1536
    # Max texts per embed_batch request during ingestion (<=0 → one request).
    embed_batch_size: int = 128

    # ── Provider credentials / endpoints ────────────────────────────────────
    openai_api_key: str | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    openai_base_url: str | None = None
    ollama_base_url: str | None = Field(
        default=None, validation_alias="OLLAMA_BASE_URL"
    )

    # ── Graph backend ───────────────────────────────────────────────────────
    # Any Cypher backend runic supports. FalkorDB + Neo4j use native vector/
    # fulltext procs; Memgraph/ArcadeDB/AGE/Neptune use the portable
    # brute-force path.
    backend: Literal[
        "falkordb",
        "neo4j",
        "memgraph",
        "arcadedb",
        "age",
        "neptune",
        "neptune_analytics",
    ] = "falkordb"
    falkordb_host: str = "localhost"
    falkordb_port: int = 6379
    falkordb_graph: str = "runic_rag"
    neo4j_uri: str | None = None
    neo4j_username: str | None = None
    neo4j_password: str | None = None
    neo4j_database: str = "neo4j"
    # Memgraph (Bolt; Neo4j protocol family)
    memgraph_uri: str | None = None
    memgraph_username: str | None = None
    memgraph_password: str | None = None
    memgraph_database: str = "memgraph"
    # ArcadeDB (Bolt)
    arcadedb_host: str = "localhost"
    arcadedb_port: int = 2424
    arcadedb_database: str = "runic_rag"
    arcadedb_username: str = "root"
    arcadedb_password: str | None = None
    # Apache AGE (PostgreSQL + AGE extension)
    age_host: str = "localhost"
    age_port: int = 5432
    age_database: str = "postgres"
    age_graph: str = "runic_rag"
    age_username: str = "postgres"
    age_password: str | None = None
    # Amazon Neptune Database (Bolt; SigV4 IAM auth via botocore)
    neptune_endpoint: str | None = None
    neptune_port: int = 8182
    neptune_region: str | None = None
    neptune_use_iam_auth: bool = True
    neptune_graph: str = "runic_rag"
    # Amazon Neptune Analytics (HTTPS via the neptune-graph boto3 client)
    neptune_analytics_graph_id: str | None = None
    neptune_analytics_region: str | None = None

    # ── Chunking ────────────────────────────────────────────────────────────
    chunk_size: int = 1200
    chunk_overlap: int = 200

    # ── Entity resolution ───────────────────────────────────────────────────
    resolve_threshold: float = 0.92
    tiebreak_low: float = 0.82
    tiebreak_high: float = 0.92
    llm_tiebreak: bool = False

    # ── Concurrency & rate limiting ─────────────────────────────────────────
    concurrency: int = 8
    requests_per_minute: int = 0

    # ── Cost control (0 means unlimited) ────────────────────────────────────
    max_llm_calls: int = 0
    max_tokens: int = 0
    gleaning_passes: int = 0
    cache_dir: str = ".cache/runic-rag"

    # ── Retrieval ───────────────────────────────────────────────────────────
    max_hops: int = 2
    top_k: int = 10


def load_settings() -> RagSettings:
    """Load ``.env`` (if present) then return validated :class:`RagSettings`.

    ``dotenv.load_dotenv()`` is called first so values placed in a local
    ``.env`` are visible both to pydantic-settings and to any library that
    reads ``os.environ`` directly (e.g. the OpenAI client).
    """
    load_dotenv()
    settings = RagSettings()
    log.debug(
        "Loaded RagSettings: backend=%s llm_provider=%s embedding_dim=%d",
        settings.backend,
        settings.llm_provider,
        settings.embedding_dim,
    )
    return settings
