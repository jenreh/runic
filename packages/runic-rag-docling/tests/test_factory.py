"""Unit tests for :func:`runic_rag_docling.factory.build_graphrag`.

Docling-free: ``GraphRAG.with_defaults`` is patched to capture its kwargs, so the
test pins the *wiring contract* (a :class:`DoclingChunker` is injected as the
``document_chunker``, and driver/ontology are forwarded) without standing up a
real driver, the LLM stack, or docling.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import runic.rag
from runic.rag import Ontology, RagSettings

from runic_rag_docling import DoclingSettings, build_graphrag
from runic_rag_docling.chunker import DoclingChunker

if TYPE_CHECKING:
    import pytest


def test_build_graphrag_injects_docling_chunker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The one-liner forwards a DoclingChunker plus driver/ontology to defaults."""
    captured: dict[str, Any] = {}
    sentinel = object()

    def fake_with_defaults(driver: Any = None, **kwargs: Any) -> object:
        captured["driver"] = driver
        captured.update(kwargs)
        return sentinel

    monkeypatch.setattr(runic.rag.GraphRAG, "with_defaults", fake_with_defaults)

    settings = RagSettings(falkordb_graph="docling_demo")
    driver = object()
    ontology = Ontology.default()

    result = build_graphrag(
        settings,
        DoclingSettings(mode="local"),
        driver=driver,
        ontology=ontology,
    )

    assert result is sentinel
    assert captured["driver"] is driver
    assert captured["settings"] is settings
    assert captured["ontology"] is ontology
    assert isinstance(captured["document_chunker"], DoclingChunker)


def test_build_graphrag_defaults_docling_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Omitting docling settings still injects a DoclingChunker (local default)."""
    captured: dict[str, Any] = {}

    def fake_with_defaults(driver: Any = None, **kwargs: Any) -> object:
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(runic.rag.GraphRAG, "with_defaults", fake_with_defaults)

    build_graphrag(RagSettings(falkordb_graph="docling_demo"))

    assert isinstance(captured["document_chunker"], DoclingChunker)
