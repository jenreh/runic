"""Unit tests for RagSettings and load_settings (no network, no .env on disk)."""

from __future__ import annotations

import pytest

from runic.rag.config import RagSettings, load_settings


@pytest.fixture(autouse=True)
def _clear_rag_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove any RUNIC_RAG_* / OPENAI / OLLAMA vars and ignore on-disk .env."""
    import os

    for key in list(os.environ):
        if key.startswith("RUNIC_RAG_") or key in {"OPENAI_API_KEY", "OLLAMA_BASE_URL"}:
            monkeypatch.delenv(key, raising=False)
    # Avoid reading a developer's local .env file.
    monkeypatch.setattr(
        "runic.rag.config.RagSettings.model_config",
        {**RagSettings.model_config, "env_file": None},
    )


def test_defaults_mirror_env_example() -> None:
    settings = RagSettings()
    assert settings.llm_provider == "openai"
    assert settings.llm_model == "gpt-5.4-nano"
    assert settings.embedding_provider == "openai"
    assert settings.embedding_model == "text-embedding-3-small"
    assert settings.embedding_dim == 1536
    assert settings.embed_batch_size == 128
    assert settings.backend == "falkordb"
    assert settings.falkordb_host == "localhost"
    assert settings.falkordb_port == 6379
    assert settings.falkordb_graph == "runic_rag"
    assert settings.neo4j_database == "neo4j"
    assert settings.chunk_size == 1200
    assert settings.chunk_overlap == 200
    assert settings.resolve_threshold == pytest.approx(0.92)
    assert settings.tiebreak_low == pytest.approx(0.82)
    assert settings.tiebreak_high == pytest.approx(0.92)
    assert settings.llm_tiebreak is False
    assert settings.concurrency == 8
    assert settings.requests_per_minute == 0
    assert settings.max_llm_calls == 0
    assert settings.max_tokens == 0
    assert settings.gleaning_passes == 0
    assert settings.cache_dir == ".cache/runic-rag"
    assert settings.max_hops == 2
    assert settings.top_k == 10


def test_defaults_for_optional_credentials() -> None:
    settings = RagSettings()
    assert settings.openai_api_key is None
    assert settings.openai_base_url is None
    assert settings.ollama_base_url is None
    assert settings.neo4j_uri is None


def test_prefixed_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RUNIC_RAG_LLM_MODEL", "custom-model")
    monkeypatch.setenv("RUNIC_RAG_EMBEDDING_DIM", "32")
    monkeypatch.setenv("RUNIC_RAG_BACKEND", "neo4j")
    settings = RagSettings()
    assert settings.llm_model == "custom-model"
    assert settings.embedding_dim == 32
    assert settings.backend == "neo4j"


def test_openai_api_key_reads_unprefixed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
    settings = RagSettings()
    assert settings.openai_api_key == "sk-from-env"


def test_openai_api_key_reads_prefixed(monkeypatch: pytest.MonkeyPatch) -> None:
    # populate_by_name=True also accepts the RUNIC_RAG_-prefixed field name.
    monkeypatch.setenv("RUNIC_RAG_OPENAI_API_KEY", "sk-prefixed")
    settings = RagSettings()
    assert settings.openai_api_key == "sk-prefixed"


def test_openai_api_key_accepts_kwarg() -> None:
    # populate_by_name=True lets the field be set by name, not only its alias.
    settings = RagSettings(openai_api_key="sk-kwarg")
    assert settings.openai_api_key == "sk-kwarg"


def test_ollama_base_url_reads_unprefixed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    settings = RagSettings()
    assert settings.ollama_base_url == "http://localhost:11434/v1"


def test_extra_env_vars_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RUNIC_RAG_TOTALLY_UNKNOWN", "x")
    # Should not raise despite the unknown variable.
    RagSettings()


def test_load_settings_returns_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("runic.rag.config.load_dotenv", lambda *a, **k: False)
    settings = load_settings()
    assert isinstance(settings, RagSettings)
    assert settings.backend == "falkordb"
