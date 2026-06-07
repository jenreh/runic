"""Repository: typed reads and custom Cypher helpers for one entity type."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from runic.orm.repository.cypher import _SCALAR_TYPES, map_cypher_result
from runic.orm.repository.protocol import RepositoryProtocol

if TYPE_CHECKING:
    from runic.orm.session.session import Session

log = logging.getLogger(__name__)


class Repository[T](RepositoryProtocol[T]):
    """Typed reads and explicit Cypher helpers for one entity type.

    Mutations (``add``, ``delete``) and single-PK lookup (``get``) belong to
    the :class:`Session`.  All reads here register returned entities in the
    session identity map.

    Example::

        with Session(graph) as session:
            repo = Repository(session, Person)
            all_people = repo.find_all()
            page = repo.find_all(skip=0, limit=25)
    """

    def __init__(self, session: Session, entity_class: type[T]) -> None:
        self._session = session
        self._cls = entity_class

    # ------------------------------------------------------------------
    # Standard reads
    # ------------------------------------------------------------------

    def find_all(
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
            result = self._session.execute(cypher, params)
            return self._decode_rows_with_fetch(result, fetch_meta)

        cypher, params = self._session.mapper.build_find_all_query(
            self._cls, skip=skip, limit=limit
        )
        result = self._session.execute(cypher, params)
        return self._decode_rows(result)

    def find_all_by_ids(
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
            result = self._session.execute(cypher, params)
            return self._decode_rows_with_fetch(result, fetch_meta)

        cypher, params = self._session.mapper.build_find_all_by_ids_query(
            self._cls, pks
        )
        result = self._session.execute(cypher, params)
        return self._decode_rows(result)

    def count(self) -> int:
        """Return the total number of entities of this type."""
        cypher, params = self._session.mapper.build_count_query(self._cls)
        result = self._session.execute(cypher, params)
        if result.rows:
            return int(result.rows[0][0])
        return 0

    def exists(self, pk: Any) -> bool:
        """Return ``True`` if an entity with *pk* exists in the graph."""
        cypher, params = self._session.mapper.build_exists_query(self._cls, pk)
        result = self._session.execute(cypher, params)
        if result.rows:
            return int(result.rows[0][0]) > 0
        return False

    # ------------------------------------------------------------------
    # Custom Cypher helpers
    # ------------------------------------------------------------------

    def query(self) -> Any:
        """Return a :class:`~runic.orm.query.builder.QueryBuilder` for this repository's entity type.

        Shorthand for ``select(self._cls)`` bound to the current session.  Prefer
        the ``select()`` + session execution pattern for new code::

            repo = Repository(session, User)

            # Preferred (select + session execution):
            users = session.scalars(select(User).where(User.active == True))

            # Also available via repo (bound builder):
            users = repo.query().where(User.active == True).all()

        Returns
        -------
        QueryBuilder[T]
        """
        from runic.orm.query.builder import QueryBuilder

        return QueryBuilder(self._session, self._cls)

    def cypher(
        self,
        query: str,
        params: dict[str, Any] | None = None,
        *,
        returns: type | None = None,
        write: bool = False,
    ) -> list[Any]:
        """Execute *query* and return a typed list.

        ``returns`` controls decoding: ``int``, ``str``, ``bool`` → scalar;
        ``dict`` → column-keyed dicts; any ``Node`` subclass → decoded entities
        registered in the session identity map; ``None`` → empty list.
        """
        result = self._session.execute(query, params or {}, write=write)
        register_fn = (
            self._session.register_or_get
            if returns is not None
            and returns not in _SCALAR_TYPES
            and returns is not dict
            else None
        )
        return map_cypher_result(result, returns, self._session.mapper, register_fn)

    def cypher_one(
        self,
        query: str,
        params: dict[str, Any] | None = None,
        *,
        returns: type | None = None,
        write: bool = False,
    ) -> Any | None:
        """Execute *query* and return the first mapped value, or ``None``."""
        items = self.cypher(query, params, returns=returns, write=write)
        return items[0] if items else None

    def cypher_raw(
        self,
        query: str,
        params: dict[str, Any] | None = None,
        *,
        write: bool = False,
    ) -> Any:
        """Execute *query* and return the raw ``QueryResult`` without entity mapping."""
        return self._session.execute(query, params or {}, write=write)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _decode_rows(self, result: Any) -> list[T]:
        """Decode plain MATCH rows (single node per row) and register in identity map."""
        entities: list[T] = []
        for row in result.rows:
            decoded = self._session.mapper.decode_node(row[0], self._cls)
            registered = self._session.register_or_get(decoded)
            entities.append(registered)
        return entities

    def _decode_rows_with_fetch(
        self,
        result: Any,
        fetch_meta: list[tuple[str, Any]],
    ) -> list[T]:
        """Decode rows that include eager-loaded relationship columns."""
        entities: list[T] = []
        for row in result.rows:
            decoded = self._session.mapper.decode_node(row[0], self._cls)
            registered = self._session.register_or_get(decoded)
            related = self._session.rel_loader.decode_eager_columns(
                row, registered, fetch_meta
            )
            for rel_entity in related:
                self._session.register_or_get(rel_entity)
            entities.append(registered)
        return entities
