from __future__ import annotations

from typing import Any


def assert_constraint_exists(graph: Any, label: str, property_name: str) -> None:
    constraints = graph.list_constraints()
    expected = (label, property_name)
    found = any(
        getattr(constraint, "label", None) == expected[0]
        and getattr(constraint, "properties", None) == [expected[1]]
        for constraint in constraints
    )

    if not found:
        msg = f"Missing {label}({property_name}) constraint"
        raise RuntimeError(msg)
