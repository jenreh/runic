from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Protocol


class QueryResultProtocol(Protocol):
    result_set: list[tuple[Any, ...]]


class GraphProtocol(Protocol):
    def ro_query(
        self,
        query: str,
        params: dict[str, Any] | None = None,
    ) -> QueryResultProtocol: ...

    def query(
        self,
        query: str,
        params: dict[str, Any] | None = None,
    ) -> Any: ...

    def list_indexes(self) -> list[Any]: ...

    def list_constraints(self) -> list[Any]: ...

    def create_node_range_index(self, label: str, property_name: str) -> Any: ...

    def create_node_unique_constraint(self, label: str, property_name: str) -> Any: ...

    def create_node_fulltext_index(self, label: str, *property_names: str) -> Any: ...


class Migration(ABC):
    version: str
    description: str

    @abstractmethod
    def up(self, graph: GraphProtocol) -> None:
        """Apply migration."""

    def down(self, graph: GraphProtocol) -> None:
        msg = "Rollback not supported for production migrations."
        raise NotImplementedError(msg)
