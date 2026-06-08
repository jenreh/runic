"""AsyncRepository: async parity of Repository for AsyncSession."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from runic.ogm.repository._base import _RepositoryBase
from runic.ogm.repository.cypher import _SCALAR_TYPES, map_cypher_result
from runic.ogm.repository.protocol import AsyncRepositoryProtocol

if TYPE_CHECKING:
    from runic.ogm.session.async_session import AsyncSession

log = logging.getLogger(__name__)


class AsyncRepository[T](_RepositoryBase[T], AsyncRepositoryProtocol[T]):
    """Async typed reads and explicit Cypher helpers for one entity type.

    Mirrors :class:`Repository` with ``async`` methods.  Shared construction and
    row decoding live in
    :class:`~runic.ogm.repository._base._RepositoryBase`.

    Example::

        async with AsyncSession(graph) as session:
            repo = AsyncRepository(session, Trip)
            trips = await repo.find_all()
    """

    def __init__(self, session: AsyncSession, entity_class: type[T]) -> None:
        super().__init__(session, entity_class)

    # ------------------------------------------------------------------
    # Standard reads
    # ------------------------------------------------------------------

    async def find_all(
        self,
        fetch: list[str] | None = None,
        skip: int = 0,
        limit: int | None = None,
    ) -> list[T]:
        """Return all entities of this type, with optional eager relationship loading.

        Use *skip* and *limit* for offset-based pagination (aligns with
        ``select(...).skip(n).limit(n)`` syntax).  Combining *fetch* with
        *skip*/*limit* is not supported — use the QueryBuilder for that.
        """
        if fetch and (skip > 0 or limit is not None):
            raise ValueError(
                "fetch= cannot be combined with skip=/limit=; use QueryBuilder instead."
            )
        if fetch:
            cypher, params, fetch_meta = (
                self._session.rel_loader.build_find_all_with_fetch_query(
                    self._cls, fetch
                )
            )
            result = await self._session.execute(cypher, params)
            return self._decode_rows_with_fetch(result, fetch_meta)

        cypher, params = self._session.mapper.build_find_all_query(
            self._cls, skip=skip, limit=limit
        )
        result = await self._session.execute(cypher, params)
        return self._decode_rows(result)

    async def find_all_by_ids(
        self, pks: list[Any], fetch: list[str] | None = None
    ) -> list[T]:
        """Return entities whose primary keys are in *pks*."""
        if not pks:
            return []

        if fetch:
            cypher, params, fetch_meta = (
                self._session.rel_loader.build_find_all_by_ids_with_fetch_query(
                    self._cls, pks, fetch
                )
            )
            result = await self._session.execute(cypher, params)
            return self._decode_rows_with_fetch(result, fetch_meta)

        cypher, params = self._session.mapper.build_find_all_by_ids_query(
            self._cls, pks
        )
        result = await self._session.execute(cypher, params)
        return self._decode_rows(result)

    async def count(self) -> int:
        """Return the total number of entities of this type."""
        cypher, params = self._session.mapper.build_count_query(self._cls)
        result = await self._session.execute(cypher, params)
        if result.rows:
            return int(result.rows[0][0])
        return 0

    async def exists(self, pk: Any) -> bool:
        """Return ``True`` if an entity with *pk* exists in the graph."""
        cypher, params = self._session.mapper.build_exists_query(self._cls, pk)
        result = await self._session.execute(cypher, params)
        if result.rows:
            return int(result.rows[0][0]) > 0
        return False

    def query(self) -> Any:
        """Return an :class:`~runic.ogm.query.builder.AsyncQueryBuilder` for this repository's entity type.

        Async counterpart of :meth:`~runic.ogm.repository.repository.Repository.query`.
        Use ``await`` on the terminal methods::

            repo = AsyncRepository(session, User)
            users = await repo.query().where(User.active == True).all()
        """
        from runic.ogm.query.specialised import AsyncQueryBuilder

        return AsyncQueryBuilder(self._session, self._cls)

    # ------------------------------------------------------------------
    # Custom Cypher helpers
    # ------------------------------------------------------------------

    async def cypher(
        self,
        query: str,
        params: dict[str, Any] | None = None,
        *,
        returns: type | None = None,
        write: bool = False,
    ) -> list[Any]:
        """Execute *query* and return a typed list."""
        result = await self._session.execute(query, params or {}, write=write)
        register_fn = (
            self._session.register_or_get
            if returns is not None
            and returns not in _SCALAR_TYPES
            and returns is not dict
            else None
        )
        return map_cypher_result(result, returns, self._session.mapper, register_fn)

    async def cypher_one(
        self,
        query: str,
        params: dict[str, Any] | None = None,
        *,
        returns: type | None = None,
        write: bool = False,
    ) -> Any | None:
        """Execute *query* and return the first mapped value, or ``None``."""
        items = await self.cypher(query, params, returns=returns, write=write)
        return items[0] if items else None

    async def cypher_raw(
        self,
        query: str,
        params: dict[str, Any] | None = None,
        *,
        write: bool = False,
    ) -> Any:
        """Execute *query* and return the raw ``QueryResult``."""
        return await self._session.execute(query, params or {}, write=write)
