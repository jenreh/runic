from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RangeIndex:
    label: str
    prop: str
    rel: bool = False


@dataclass(frozen=True)
class FulltextIndex:
    label: str
    props: tuple[str, ...]
    language: str | None = None
    stopwords: tuple[str, ...] | None = None

    def __init__(
        self,
        label: str,
        props: list[str] | tuple[str, ...],
        language: str | None = None,
        stopwords: list[str] | tuple[str, ...] | None = None,
    ) -> None:
        object.__setattr__(self, "label", label)
        object.__setattr__(self, "props", tuple(props))
        object.__setattr__(self, "language", language)
        object.__setattr__(
            self, "stopwords", tuple(stopwords) if stopwords is not None else None
        )


@dataclass(frozen=True)
class VectorIndex:
    label: str
    prop: str
    dimension: int
    similarity: str
    m: int = 16
    ef_construction: int = 200
    ef_runtime: int = 10


@dataclass(frozen=True)
class UniqueConstraint:
    entity: str  # "NODE" | "RELATIONSHIP"
    label: str
    props: tuple[str, ...]

    def __init__(
        self, entity: str, label: str, props: list[str] | tuple[str, ...]
    ) -> None:
        object.__setattr__(self, "entity", entity)
        object.__setattr__(self, "label", label)
        object.__setattr__(self, "props", tuple(props))


@dataclass(frozen=True)
class MandatoryConstraint:
    entity: str  # "NODE" | "RELATIONSHIP"
    label: str
    props: tuple[str, ...]

    def __init__(
        self, entity: str, label: str, props: list[str] | tuple[str, ...]
    ) -> None:
        object.__setattr__(self, "entity", entity)
        object.__setattr__(self, "label", label)
        object.__setattr__(self, "props", tuple(props))


@dataclass
class SchemaManifest:
    range_indexes: list[RangeIndex] = field(default_factory=list)
    fulltext_indexes: list[FulltextIndex] = field(default_factory=list)
    vector_indexes: list[VectorIndex] = field(default_factory=list)
    constraints: list[UniqueConstraint | MandatoryConstraint] = field(
        default_factory=list
    )
