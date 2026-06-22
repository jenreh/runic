"""Configuration for the Docling add-on (concept §6).

:class:`DoclingSettings` is the add-on's own pydantic-settings model, fully
independent of the core :class:`runic.rag.RagSettings`. It is read from the
environment with the ``RUNIC_DOCLING_`` prefix (and an optional ``.env``). The
Docling adapters accept either a ``DoclingSettings`` instance or explicit kwargs.
"""

from __future__ import annotations

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class DoclingSettings(BaseSettings):
    """Runtime configuration for the Docling adapters.

    Fields mirror the two operating modes (concept §7): ``local`` runs Docling
    in-process; ``server`` talks to ``docling-serve`` over HTTP. The chunking
    fields (``max_tokens``, ``tokenizer``, ``merge_peers``) feed the
    ``HybridChunker``; ``ocr`` toggles local PDF OCR (off by default); ``timeout``
    bounds server HTTP calls.
    """

    # ``extra="ignore"`` mirrors the core ``RagSettings`` precedent: a shared
    # ``.env`` typically also carries non-``RUNIC_DOCLING_`` keys (OPENAI_API_KEY,
    # RUNIC_RAG_*); without it pydantic's default ``forbid`` makes
    # ``DoclingSettings()`` raise at construction whenever such an ``.env`` exists.
    model_config = SettingsConfigDict(
        env_prefix="RUNIC_DOCLING_", env_file=".env", extra="ignore"
    )

    mode: Literal["local", "server"] = "local"
    server_url: str | None = None
    api_key: str | None = None
    max_tokens: int = 512
    tokenizer: str | None = None
    merge_peers: bool = True
    ocr: bool = False
    timeout: float = 120.0
