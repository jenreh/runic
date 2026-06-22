"""LLM-backed entity/relation extraction adapter (ADR-006 hybrid constraint).

:class:`PydanticAIExtractor` implements the :class:`~runic.rag.ports.Extractor`
port using a pydantic-ai :class:`~pydantic_ai.Agent`. It enforces the *hybrid*
extraction contract:

* Entity ``type`` is **constrained** to the ontology vocabulary supplied per
  call. A dynamic :class:`enum.Enum` restricts the structured-output schema so
  the model can only emit known types.
* Relation ``rel_type`` is a **free** string (LLM-proposed), defaulting to
  ``"RELATES_TO"`` when the model omits it.

The agent is built once from :class:`~runic.rag.config.RagSettings` via
:func:`runic.rag.adapters._llm.build_agent`; a fresh per-call structured output
type is supplied to :meth:`~pydantic_ai.Agent.run_sync` so a single agent can
serve any ontology. ``gleaning_passes`` (default 0) triggers extra extraction
rounds whose results are merged, improving recall on dense chunks.
"""

from __future__ import annotations

import enum
import logging
from functools import lru_cache
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from runic.rag.config import RagSettings
from runic.rag.domain import (
    Chunk,
    ExtractedEntity,
    ExtractedRelation,
    Extraction,
)

if TYPE_CHECKING:
    from pydantic_ai import Agent

log = logging.getLogger(__name__)

__all__ = ["PydanticAIExtractor"]

_DEFAULT_REL_TYPE = "RELATES_TO"

_SYSTEM_PROMPT = (
    "You are a meticulous information-extraction engine for a knowledge graph. "
    "Read the provided text chunk and extract the entities it mentions and the "
    "directed relations between them.\n"
    "Rules:\n"
    "- Only assign an entity `type` from the allowed set; pick the closest fit.\n"
    "- Use the exact surface name of each entity as it appears in the text.\n"
    "- For relations, set `source` and `target` to entity names you also list "
    "in `entities`, and choose a concise UPPER_SNAKE_CASE `rel_type` verb "
    "phrase (e.g. WORKS_AT, FOUNDED, LOCATED_IN).\n"
    "- Prefer precision: omit anything not supported by the text. If there are "
    "no entities or relations, return empty lists."
)

_GLEAN_PROMPT = (
    "Re-read the SAME text chunk and extract ONLY entities and relations you "
    "missed before. Do not repeat anything already returned. Return empty "
    "lists if nothing new is found."
)


class _RelationModel(BaseModel):
    """Structured-output relation (rel_type is a free LLM-proposed string)."""

    source: str
    target: str
    rel_type: str = Field(default=_DEFAULT_REL_TYPE)
    description: str = Field(default="")
    confidence: float = Field(default=1.0)


def _entity_type_enum(entity_types: tuple[str, ...]) -> type[enum.Enum]:
    """Build a string-valued :class:`enum.Enum` over the ontology vocabulary.

    The enum *member values* are the type names, so pydantic serialises and
    validates against the exact strings while the JSON schema advertises them
    as the only permitted choices (the ADR-006 type constraint).
    """
    return enum.Enum(  # type: ignore[return-value]
        "EntityTypeEnum",
        {name: name for name in entity_types},
        type=str,
    )


def _build_output_type(entity_types: tuple[str, ...]) -> type[BaseModel]:
    """Create the per-vocabulary structured-output model for the agent.

    When *entity_types* is empty the ``type`` field degrades to a free string
    so extraction still succeeds without an ontology; otherwise it is a dynamic
    enum constrained to the supplied vocabulary.
    """
    type_field: tuple[Any, Any]
    if entity_types:
        type_enum = _entity_type_enum(entity_types)
        type_field = (type_enum, ...)
    else:
        type_field = (str, ...)

    entity_model = _make_entity_model(type_field)
    # Build ``list[entity_model]`` at runtime; a direct subscript in a type
    # position would be rejected by the static type checker (dynamic class).
    entity_list = list.__class_getitem__(entity_model)
    relation_list = list.__class_getitem__(_RelationModel)

    namespace: dict[str, Any] = {
        "__annotations__": {
            "entities": entity_list,
            "relations": relation_list,
        },
        "entities": Field(default_factory=list),
        "relations": Field(default_factory=list),
        "__doc__": "Structured extraction output for one chunk.",
    }
    return type("ExtractionOutput", (BaseModel,), namespace)


def _make_entity_model(type_field: tuple[Any, Any]) -> type[BaseModel]:
    """Build the per-call entity model with the given ``type`` field spec."""
    annotation, default = type_field
    namespace: dict[str, Any] = {
        "__annotations__": {
            "name": str,
            "type": annotation,
            "description": str,
        },
        "name": Field(...),
        "type": Field(default) if default is ... else Field(default=default),
        "description": Field(default=""),
        "__doc__": "A single extracted entity (type constrained by ontology).",
    }
    return type("ExtractionEntity", (BaseModel,), namespace)


@lru_cache(maxsize=64)
def _cached_output_type(entity_types: tuple[str, ...]) -> type[BaseModel]:
    """Memoised :func:`_build_output_type` keyed by the type vocabulary."""
    return _build_output_type(entity_types)


def _coerce_type(raw: Any) -> str:
    """Normalise an entity ``type`` (enum member or string) to its string."""
    if isinstance(raw, enum.Enum):
        return str(raw.value)
    return str(raw)


class PydanticAIExtractor:
    """Extractor backed by a pydantic-ai agent with hybrid type constraints.

    Parameters
    ----------
    settings:
        Runtime configuration; ``llm_model``/provider drive the agent and
        ``gleaning_passes`` controls extra recall-boosting rounds.
    agent:
        Optional pre-built agent (constructor injection for tests). When
        omitted, one is built lazily via :func:`._llm.build_agent`.
    """

    def __init__(
        self,
        settings: RagSettings,
        *,
        agent: Agent[None, Any] | None = None,
    ) -> None:
        self._settings = settings
        self._agent = agent

    @property
    def agent(self) -> Agent[None, Any]:
        """Return the underlying agent, building it on first access."""
        if self._agent is None:
            from runic.rag.adapters._llm import build_agent

            self._agent = build_agent(
                self._settings,
                output_type=str,
                system_prompt=_SYSTEM_PROMPT,
            )
        return self._agent

    def extract(self, chunk: Chunk, *, entity_types: list[str]) -> Extraction:
        """Extract entities and relations from *chunk* (ports.Extractor).

        Entity types are constrained to *entity_types*; ``rel_type`` stays free.
        Honours ``settings.gleaning_passes`` by merging extra extraction rounds.
        """
        vocab = tuple(dict.fromkeys(entity_types))  # dedupe, keep order
        output_type = _cached_output_type(vocab)

        entities: dict[tuple[str, str], ExtractedEntity] = {}
        relations: dict[tuple[str, str, str], ExtractedRelation] = {}

        prompt = self._user_prompt(chunk)
        history = self._run_pass(prompt, output_type, entities, relations)

        passes = max(0, self._settings.gleaning_passes)
        for index in range(passes):
            log.debug("Gleaning pass %d/%d for chunk %s", index + 1, passes, chunk.id)
            history = self._run_pass(
                _GLEAN_PROMPT,
                output_type,
                entities,
                relations,
                message_history=history,
            )

        result = Extraction(
            entities=list(entities.values()),
            relations=list(relations.values()),
        )
        log.debug(
            "Extracted %d entities, %d relations from chunk %s",
            len(result.entities),
            len(result.relations),
            chunk.id,
        )
        return result

    # ── Internals ───────────────────────────────────────────────────────────

    def _run_pass(
        self,
        prompt: str,
        output_type: type[BaseModel],
        entities: dict[tuple[str, str], ExtractedEntity],
        relations: dict[tuple[str, str, str], ExtractedRelation],
        *,
        message_history: list[Any] | None = None,
    ) -> list[Any]:
        """Run one agent pass, merge results in-place, return message history."""
        run = self.agent.run_sync(
            prompt,
            output_type=output_type,
            message_history=message_history,
        )
        self._merge(run.output, entities, relations)
        return run.all_messages()

    @staticmethod
    def _user_prompt(chunk: Chunk) -> str:
        """Compose the user prompt embedding the chunk text and provenance."""
        return f"Source: {chunk.source}\n\nText:\n{chunk.text}"

    @staticmethod
    def _merge(
        output: Any,
        entities: dict[tuple[str, str], ExtractedEntity],
        relations: dict[tuple[str, str, str], ExtractedRelation],
    ) -> None:
        """Fold one structured output into the accumulators (dedup by identity).

        Robust to model omissions: ``entities``/``relations`` default to empty
        and per-item attribute access tolerates absent optional fields.
        """
        for raw in getattr(output, "entities", None) or []:
            name = str(getattr(raw, "name", "")).strip()
            if not name:
                continue
            type_name = _coerce_type(getattr(raw, "type", ""))
            key = (name, type_name)
            if key not in entities:
                entities[key] = ExtractedEntity(
                    name=name,
                    type=type_name,
                    description=str(getattr(raw, "description", "") or ""),
                )

        for raw in getattr(output, "relations", None) or []:
            source = str(getattr(raw, "source", "")).strip()
            target = str(getattr(raw, "target", "")).strip()
            if not source or not target:
                continue
            rel_type = str(getattr(raw, "rel_type", "") or _DEFAULT_REL_TYPE)
            key = (source, target, rel_type)
            if key not in relations:
                relations[key] = ExtractedRelation(
                    source=source,
                    target=target,
                    rel_type=rel_type,
                    description=str(getattr(raw, "description", "") or ""),
                    confidence=float(getattr(raw, "confidence", 1.0) or 1.0),
                )
