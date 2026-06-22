"""Exception hierarchy for the runic.rag Graph-RAG SDK."""

from __future__ import annotations

__all__ = [
    "BudgetExceededError",
    "ConfigError",
    "RagError",
]


class RagError(Exception):
    """Base class for all runic.rag errors."""


class BudgetExceededError(RagError):
    """Raised when a cost budget (LLM calls or tokens) is exceeded."""


class ConfigError(RagError):
    """Raised when configuration is missing or invalid."""
