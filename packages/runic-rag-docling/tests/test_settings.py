"""Unit tests for :class:`runic_rag_docling.settings.DoclingSettings`.

Covers the documented defaults (concept §6) and the ``RUNIC_DOCLING_*`` env
overrides. Tests are hermetic: the defaults case disables ``.env`` loading and
clears any inherited ``RUNIC_DOCLING_*`` vars so a developer's shell can't skew
the assertions.
"""

from __future__ import annotations

import pytest

from runic_rag_docling import DoclingSettings

_ENV_KEYS = (
    "RUNIC_DOCLING_MODE",
    "RUNIC_DOCLING_SERVER_URL",
    "RUNIC_DOCLING_API_KEY",
    "RUNIC_DOCLING_MAX_TOKENS",
    "RUNIC_DOCLING_TOKENIZER",
    "RUNIC_DOCLING_MERGE_PEERS",
    "RUNIC_DOCLING_OCR",
    "RUNIC_DOCLING_TIMEOUT",
)


def test_defaults_match_spec(monkeypatch: pytest.MonkeyPatch) -> None:
    """Out of the box, settings select local mode with the documented values."""
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    # ``_env_file`` is a pydantic-settings init kwarg; ty doesn't model it.
    settings = DoclingSettings(_env_file=None)  # ty: ignore[unknown-argument]

    assert settings.mode == "local"
    assert settings.server_url is None
    assert settings.api_key is None
    assert settings.max_tokens == 512
    assert settings.tokenizer is None
    assert settings.merge_peers is True
    assert settings.ocr is False
    assert settings.timeout == 120.0


def test_env_overrides_apply(monkeypatch: pytest.MonkeyPatch) -> None:
    """``RUNIC_DOCLING_*`` env vars override the defaults, with coercion."""
    monkeypatch.setenv("RUNIC_DOCLING_MODE", "server")
    monkeypatch.setenv("RUNIC_DOCLING_SERVER_URL", "http://localhost:5001")
    monkeypatch.setenv("RUNIC_DOCLING_API_KEY", "k-123")
    monkeypatch.setenv("RUNIC_DOCLING_MAX_TOKENS", "256")
    monkeypatch.setenv("RUNIC_DOCLING_OCR", "true")

    settings = DoclingSettings()

    assert settings.mode == "server"
    assert settings.server_url == "http://localhost:5001"
    assert settings.api_key == "k-123"
    assert settings.max_tokens == 256
    assert settings.ocr is True


def test_explicit_kwargs_beat_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Explicit constructor kwargs win over the environment (least surprise)."""
    monkeypatch.setenv("RUNIC_DOCLING_MODE", "server")

    settings = DoclingSettings(mode="local")

    assert settings.mode == "local"


def test_unrelated_env_keys_are_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    """A shared ``.env`` carrying non-prefixed keys must not break construction."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-irrelevant")
    monkeypatch.setenv("RUNIC_RAG_FALKORDB_GRAPH", "demo")

    # ``extra="ignore"`` means these simply don't appear on the model.
    settings = DoclingSettings(_env_file=None)  # ty: ignore[unknown-argument]

    assert not hasattr(settings, "openai_api_key")
    assert settings.mode == "local"
