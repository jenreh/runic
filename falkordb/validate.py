from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from falkordb.client import connect_to_graph
from falkordb.config import FalkorDBSettings
from falkordb.schema.constraints import REQUIRED_CONSTRAINTS, ConstraintSpec


class SchemaValidationError(RuntimeError):
    """Raised when a required FalkorDB constraint is missing."""


def assert_constraint_exists(
    graph: Any,
    label: str,
    property_names: str | tuple[str, ...],
) -> None:
    expected_properties = (
        (property_names,) if isinstance(property_names, str) else property_names
    )
    constraints = graph.list_constraints()
    found = any(
        getattr(constraint, "label", None) == label
        and tuple(getattr(constraint, "properties", ())) == expected_properties
        for constraint in constraints
    )

    if not found:
        rendered_properties = ", ".join(expected_properties)
        msg = f"Missing {label}({rendered_properties}) constraint"
        raise SchemaValidationError(msg)


def validate_required_constraints(
    graph: Any,
    required_constraints: Iterable[ConstraintSpec] = REQUIRED_CONSTRAINTS,
) -> None:
    for constraint in required_constraints:
        assert_constraint_exists(graph, constraint.label, constraint.properties)


def main(
    settings: FalkorDBSettings | None = None,
    graph_factory: Any = None,
) -> None:
    graph = connect_to_graph(settings or FalkorDBSettings.from_env(), graph_factory)
    validate_required_constraints(graph)


if __name__ == "__main__":
    main()
