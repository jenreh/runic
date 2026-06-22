"""Unit tests for :class:`~runic.rag.adapters.extraction.PydanticAIExtractor`.

All tests are network-free: a real :class:`OpenAIChatModel` is built with a
dummy key (model construction does not touch the network) and overridden with a
:class:`~pydantic_ai.models.function.FunctionModel` that returns canned
structured output. This deterministically exercises the ADR-006 hybrid
constraint (enum-restricted entity types, free relation types), gleaning, and
robustness to model omissions.
"""

from __future__ import annotations

import enum
import json
from typing import Any

import pytest
from pydantic_ai import Agent
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from runic.rag.adapters.extraction import (
    PydanticAIExtractor,
    _build_output_type,
    _coerce_type,
)
from runic.rag.config import RagSettings
from runic.rag.domain import Chunk, Extraction

# ── Helpers ─────────────────────────────────────────────────────────────────


def _chunk(text: str = "Alice works at ACME in Berlin.") -> Chunk:
    return Chunk(id="c1", text=text, seq=0, source="doc.txt")


def _stub_model() -> OpenAIChatModel:
    """A real chat model built with a dummy key (no network at construction)."""
    return OpenAIChatModel("gpt-4o", provider=OpenAIProvider(api_key="sk-test"))


def _canned(output: dict[str, Any]) -> FunctionModel:
    """A FunctionModel returning *output* as the structured-output tool call."""

    def fn(_messages: list[Any], info: AgentInfo) -> ModelResponse:
        tool_name = info.output_tools[0].name
        return ModelResponse(parts=[ToolCallPart(tool_name=tool_name, args=output)])

    return FunctionModel(fn)


def _extractor(
    settings: RagSettings | None = None,
) -> tuple[PydanticAIExtractor, Agent[None, Any]]:
    """Return an extractor with an injected agent over a stub chat model."""
    agent: Agent[None, Any] = Agent(_stub_model(), output_type=str, system_prompt="x")
    cfg = settings or RagSettings(openai_api_key="sk-test")
    return PydanticAIExtractor(cfg, agent=agent), agent


# ── Output-schema construction (ADR-006 type constraint) ─────────────────────


def test_output_type_constrains_entity_types_to_enum() -> None:
    out = _build_output_type(("Person", "Organization"))
    schema = json.dumps(out.model_json_schema())
    # The constrained vocabulary appears as an enum in the JSON schema.
    assert '"enum"' in schema
    assert "Person" in schema
    assert "Organization" in schema


def test_output_type_empty_vocab_uses_free_string() -> None:
    out = _build_output_type(())
    # Parsing an arbitrary type string succeeds (no enum restriction).
    parsed = out(entities=[{"name": "X", "type": "Anything", "description": ""}])
    # `out` is a dynamically-built pydantic model, so its fields are unknown to
    # the static type checker.
    assert parsed.entities[0].type == "Anything"  # ty: ignore[unresolved-attribute]


def test_output_type_rejects_unknown_entity_type() -> None:
    out = _build_output_type(("Person",))
    with pytest.raises(Exception):  # noqa: B017,PT011 - pydantic ValidationError
        out(entities=[{"name": "X", "type": "Robot", "description": ""}])


def test_coerce_type_handles_enum_and_str() -> None:
    member = enum.Enum("E", {"Person": "Person"}).Person
    assert _coerce_type(member) == "Person"
    assert _coerce_type("Concept") == "Concept"


# ── Core extraction behaviour ────────────────────────────────────────────────


def test_extract_returns_entities_and_relations() -> None:
    extractor, agent = _extractor()
    canned = _canned(
        {
            "entities": [
                {"name": "Alice", "type": "Person", "description": "engineer"},
                {"name": "ACME", "type": "Organization", "description": ""},
            ],
            "relations": [
                {"source": "Alice", "target": "ACME", "rel_type": "WORKS_AT"},
            ],
        }
    )
    with agent.override(model=canned):
        result = extractor.extract(_chunk(), entity_types=["Person", "Organization"])

    assert isinstance(result, Extraction)
    assert {(e.name, e.type) for e in result.entities} == {
        ("Alice", "Person"),
        ("ACME", "Organization"),
    }
    assert len(result.relations) == 1
    rel = result.relations[0]
    assert (rel.source, rel.rel_type, rel.target) == ("Alice", "WORKS_AT", "ACME")


def test_entity_type_is_normalized_to_plain_string() -> None:
    extractor, agent = _extractor()
    canned = _canned(
        {"entities": [{"name": "Alice", "type": "Person", "description": ""}]}
    )
    with agent.override(model=canned):
        result = extractor.extract(_chunk(), entity_types=["Person"])

    # Type comes back as a plain str, never an Enum member (domain VO contract).
    assert result.entities[0].type == "Person"
    assert type(result.entities[0].type) is str


def test_rel_type_is_free_string_passthrough() -> None:
    extractor, agent = _extractor()
    canned = _canned(
        {
            "entities": [
                {"name": "Alice", "type": "Person", "description": ""},
                {"name": "Bob", "type": "Person", "description": ""},
            ],
            "relations": [
                {
                    "source": "Alice",
                    "target": "Bob",
                    "rel_type": "MENTORS",
                    "description": "since 2020",
                    "confidence": 0.7,
                },
            ],
        }
    )
    with agent.override(model=canned):
        result = extractor.extract(_chunk(), entity_types=["Person"])

    rel = result.relations[0]
    # Free vocabulary: an arbitrary rel_type survives untouched.
    assert rel.rel_type == "MENTORS"
    assert rel.description == "since 2020"
    assert rel.confidence == pytest.approx(0.7)


def test_rel_type_falls_back_when_omitted() -> None:
    extractor, agent = _extractor()
    # rel_type absent -> schema default "RELATES_TO".
    canned = _canned(
        {
            "entities": [
                {"name": "A", "type": "Person", "description": ""},
                {"name": "B", "type": "Person", "description": ""},
            ],
            "relations": [{"source": "A", "target": "B"}],
        }
    )
    with agent.override(model=canned):
        result = extractor.extract(_chunk(), entity_types=["Person"])

    assert result.relations[0].rel_type == "RELATES_TO"


def test_missing_relations_yields_empty_list() -> None:
    extractor, agent = _extractor()
    # No "relations" key at all -> robust empty list.
    canned = _canned(
        {"entities": [{"name": "Solo", "type": "Person", "description": ""}]}
    )
    with agent.override(model=canned):
        result = extractor.extract(_chunk(), entity_types=["Person"])

    assert result.relations == []
    assert len(result.entities) == 1


def test_empty_extraction_when_model_returns_nothing() -> None:
    extractor, agent = _extractor()
    canned = _canned({"entities": [], "relations": []})
    with agent.override(model=canned):
        result = extractor.extract(_chunk(), entity_types=["Person"])

    assert result.entities == []
    assert result.relations == []


def test_blank_entity_names_are_dropped() -> None:
    extractor, agent = _extractor()
    canned = _canned(
        {
            "entities": [
                {"name": "   ", "type": "Person", "description": ""},
                {"name": "Real", "type": "Person", "description": ""},
            ],
            "relations": [{"source": "", "target": "X", "rel_type": "R"}],
        }
    )
    with agent.override(model=canned):
        result = extractor.extract(_chunk(), entity_types=["Person"])

    assert [e.name for e in result.entities] == ["Real"]
    assert result.relations == []  # relation with blank source dropped


def test_empty_entity_types_allows_free_type() -> None:
    extractor, agent = _extractor()
    canned = _canned(
        {"entities": [{"name": "Quux", "type": "Gadget", "description": ""}]}
    )
    with agent.override(model=canned):
        result = extractor.extract(_chunk(), entity_types=[])

    assert (result.entities[0].name, result.entities[0].type) == ("Quux", "Gadget")


# ── Gleaning ─────────────────────────────────────────────────────────────────


def test_gleaning_runs_extra_passes_and_merges() -> None:
    settings = RagSettings(openai_api_key="sk-test", gleaning_passes=1)
    extractor, agent = _extractor(settings)
    calls = {"n": 0}

    def fn(_messages: list[Any], info: AgentInfo) -> ModelResponse:
        calls["n"] += 1
        tool_name = info.output_tools[0].name
        if calls["n"] == 1:
            args: dict[str, Any] = {
                "entities": [{"name": "Alice", "type": "Person", "description": ""}],
                "relations": [],
            }
        else:
            # Second pass repeats Alice (dedup) and adds Carol.
            args = {
                "entities": [
                    {"name": "Alice", "type": "Person", "description": ""},
                    {"name": "Carol", "type": "Person", "description": ""},
                ],
                "relations": [],
            }
        return ModelResponse(parts=[ToolCallPart(tool_name=tool_name, args=args)])

    with agent.override(model=FunctionModel(fn)):
        result = extractor.extract(_chunk(), entity_types=["Person"])

    assert calls["n"] == 2  # one base pass + one gleaning pass
    assert sorted(e.name for e in result.entities) == ["Alice", "Carol"]


def test_no_gleaning_by_default_runs_single_pass() -> None:
    extractor, agent = _extractor()  # gleaning_passes defaults to 0
    calls = {"n": 0}

    def fn(_messages: list[Any], info: AgentInfo) -> ModelResponse:
        calls["n"] += 1
        tool_name = info.output_tools[0].name
        return ModelResponse(
            parts=[ToolCallPart(tool_name=tool_name, args={"entities": []})]
        )

    with agent.override(model=FunctionModel(fn)):
        extractor.extract(_chunk(), entity_types=["Person"])

    assert calls["n"] == 1


# ── Lazy agent construction ──────────────────────────────────────────────────


def test_agent_is_built_lazily_from_settings() -> None:
    settings = RagSettings(openai_api_key="sk-test")
    extractor = PydanticAIExtractor(settings)  # no agent injected
    assert extractor._agent is None
    built = extractor.agent
    assert isinstance(built, Agent)
    # Cached on subsequent access.
    assert extractor.agent is built
