from __future__ import annotations

from dataclasses import dataclass

from falkordb.schema.labels import INTEREST, LOCATION, TRIP, USER


@dataclass(frozen=True, slots=True)
class ConstraintSpec:
    label: str
    properties: tuple[str, ...]


REQUIRED_CONSTRAINTS: tuple[ConstraintSpec, ...] = (
    ConstraintSpec(USER, ("auth_user_id",)),
    ConstraintSpec(TRIP, ("id",)),
    ConstraintSpec(LOCATION, ("id",)),
    ConstraintSpec(INTEREST, ("id",)),
)
