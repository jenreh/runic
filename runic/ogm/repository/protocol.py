"""Repository protocols — shared interface for Repository and AsyncRepository."""

from __future__ import annotations

from typing import Any, Protocol


class RepositoryProtocol[T](Protocol):  # pragma: no cover
    """Structural contract for the synchronous Repository."""

    def find_all(
        self,
        fetch: list[str] | None = None,
        skip: int = 0,
        limit: int | None = None,
    ) -> list[T]: ...

    def find_all_by_ids(
        self, pks: list[Any], fetch: list[str] | None = None
    ) -> list[T]: ...

    def count(self) -> int: ...

    def exists(self, pk: Any) -> bool: ...

    def cypher(
        self,
        query: str,
        params: dict[str, Any] | None = None,
        *,
        returns: type | None = None,
        write: bool = False,
    ) -> list[Any]: ...

    def cypher_one(
        self,
        query: str,
        params: dict[str, Any] | None = None,
        *,
        returns: type | None = None,
        write: bool = False,
    ) -> Any | None: ...

    def cypher_raw(
        self,
        query: str,
        params: dict[str, Any] | None = None,
        *,
        write: bool = False,
    ) -> Any: ...


class AsyncRepositoryProtocol[T](Protocol):  # pragma: no cover
    """Structural contract for the asynchronous AsyncRepository."""

    async def find_all(
        self,
        fetch: list[str] | None = None,
        skip: int = 0,
        limit: int | None = None,
    ) -> list[T]: ...

    async def find_all_by_ids(
        self, pks: list[Any], fetch: list[str] | None = None
    ) -> list[T]: ...

    async def count(self) -> int: ...

    async def exists(self, pk: Any) -> bool: ...

    async def cypher(
        self,
        query: str,
        params: dict[str, Any] | None = None,
        *,
        returns: type | None = None,
        write: bool = False,
    ) -> list[Any]: ...

    async def cypher_one(
        self,
        query: str,
        params: dict[str, Any] | None = None,
        *,
        returns: type | None = None,
        write: bool = False,
    ) -> Any | None: ...

    async def cypher_raw(
        self,
        query: str,
        params: dict[str, Any] | None = None,
        *,
        write: bool = False,
    ) -> Any: ...
