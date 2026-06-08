Async Guide
===========

``runic.ogm`` ships an async-native session —
:class:`~runic.ogm.session.async_session.AsyncSession` — that is a direct
parallel of :class:`~runic.ogm.session.session.Session`.  Use it wherever you
need ``async``/``await`` throughout your application stack.

.. important::

   **Only FalkorDB has an async driver.**  All other backends
   (ArcadeDB, Neo4j, Memgraph, Apache AGE) are sync-only.  See the
   :doc:`drivers` page for the full feature matrix.

----

Opening an async session
-------------------------

:class:`~runic.ogm.session.async_session.AsyncSession` accepts an
:class:`~runic.ogm.driver.AsyncGraphDriver`.  For FalkorDB, build one from an
async FalkorDB graph handle:

.. code-block:: python

   import asyncio
   from falkordb import FalkorDB
   from runic.ogm import AsyncSession
   from runic.ogm.driver.falkordb import AsyncFalkorDBDriver

   async def main() -> None:
       db = FalkorDB(host="localhost", port=6379)
       graph = db.select_graph("myapp")
       driver = AsyncFalkorDBDriver(graph)

       async with AsyncSession(driver) as session:
           ...   # commit on success, rollback on exception

   asyncio.run(main())

.. note::

   There is no ``create_async_falkordb_driver`` factory.  Build the handle
   directly and pass it to ``AsyncFalkorDBDriver``.

----

Which methods are coroutines
-----------------------------

``add()``, ``add_all()``, and ``delete()`` stage mutations in memory and are
**synchronous**.  Every method that touches the database is a coroutine:

.. list-table::
   :header-rows: 1
   :widths: 40 20 40

   * - Method
     - Type
     - Notes
   * - ``add(entity)``
     - sync
     - Stages an insert; no I/O
   * - ``add_all([entities])``
     - sync
     - Stages a batch insert; no I/O
   * - ``delete(entity)``
     - sync
     - Stages a deletion; no I/O
   * - ``await session.commit()``
     - coroutine
     - Flush + clear tracking
   * - ``await session.flush()``
     - coroutine
     - Write pending changes; keep tracking
   * - ``await session.rollback()``
     - coroutine
     - Discard un-flushed pending/deleted sets
   * - ``await session.get(Cls, pk, fetch=[])``
     - coroutine
     - Identity-map check → graph query
   * - ``await session.scalars(stmt)``
     - coroutine
     - Execute statement; return ``list[T]``
   * - ``await session.scalar(stmt)``
     - coroutine
     - Execute statement; return ``T | None``
   * - ``await session.count(stmt)``
     - coroutine
     - Execute statement; return ``int``
   * - ``await session.all_rows(stmt)``
     - coroutine
     - Execute statement; return ``list[dict]``
   * - ``await session.all_with_edges(stmt)``
     - coroutine
     - Execute statement; return ``list[tuple]``
   * - ``await session.execute(cypher, params)``
     - coroutine
     - Raw Cypher
   * - ``await session.refresh(entity)``
     - coroutine
     - Re-query entity from graph
   * - ``await session.relate(src, rel, tgt)``
     - coroutine
     - Create an edge (MERGE semantics)
   * - ``await session.unrelate(src, rel, tgt)``
     - coroutine
     - Delete an edge
   * - ``await session.close()``
     - coroutine
     - Expunge all + release connection

----

No lazy loading
----------------

:class:`~runic.ogm.session.async_session.AsyncSession` cannot perform lazy
loading — the ``__get__`` descriptor is synchronous and cannot ``await`` a
query.  Accessing a relationship attribute that hasn't been loaded raises
:exc:`~runic.ogm.exceptions.LazyLoadError`.

**Always** design every read to supply the data you need up front:

.. code-block:: python

   async with AsyncSession(driver) as session:
       # BAD — accessing .articles will raise LazyLoadError
       user = await session.get(User, "alice")
       print(user.articles)       # LazyLoadError

       # GOOD — eager-fetch with fetch=
       user = await session.get(User, "alice", fetch=["articles"])
       for article in user.articles:    # already loaded
           print(article.title)

       # GOOD — traversal query for a collection
       from runic.ogm import select
       stmt = (
           select(User).where(User.id == "alice").alias("u")
           .traverse(User.articles).alias("a")
           .return_target()
       )
       articles = await session.scalars(stmt)

----

Async CRUD
-----------

.. code-block:: python

   from runic.ogm import AsyncSession, select
   from runic.ogm.driver.falkordb import AsyncFalkorDBDriver

   async with AsyncSession(driver) as session:
       # Create
       session.add(User(id="alice", name="Alice", email="alice@example.com"))
       await session.commit()

       # Read — always use fetch= for related data
       user = await session.get(User, "alice", fetch=["articles"])

       # Update
       user.name = "Alice Smith"
       await session.commit()

       # Delete
       session.delete(user)
       await session.commit()

----

Async querying
---------------

Composable statements work identically in async — only the execution step is
awaited:

.. code-block:: python

   from runic.ogm import select

   stmt = (
       select(Article)
       .where(Article.published == True)
       .order_by(Article.published_at, desc=True)
       .limit(20)
   )

   articles = await session.scalars(stmt)
   total    = await session.count(stmt)

For projections and aggregations, use ``all_rows()`` instead of ``scalars()``:

.. code-block:: python

   from runic.ogm.query import count

   stmt = (
       select(User)
       .aggregate(count("*").as_("total"), group_by="n.city")
   )
   rows = await session.all_rows(stmt)
   # [{"n.city": "Berlin", "total": 3}, ...]

----

Async repositories
-------------------

:class:`~runic.ogm.repository.AsyncRepository` wraps an
:class:`~runic.ogm.session.async_session.AsyncSession`:

.. code-block:: python

   from runic.ogm import AsyncRepository

   async with AsyncSession(driver) as session:
       repo = AsyncRepository(session, User)
       users = await repo.find_all(skip=0, limit=20)
       count = await repo.count()
       exists = await repo.exists("alice")

Subclass for domain queries:

.. code-block:: python

   class UserRepository(AsyncRepository[User]):
       async def active_in_region(self, region: str) -> list[User]:
           return await (
               self.query()
               .where((User.active == True) & (User.region == region))
               .order_by(User.name)
               .all()
           )

----

Connection management (async)
------------------------------

:class:`~runic.ogm.session.connection_pool.AsyncConnectionManager` wraps a
FalkorDB graph handle for reuse across sessions:

.. code-block:: python

   from runic.ogm import AsyncConnectionManager

   manager = AsyncConnectionManager(async_graph_handle)
   async with manager.session() as session:
       ...

Create the manager once at application startup; share it across request
handlers rather than creating a new driver per request.

----

Testing async code
-------------------

Use embedded FalkorDB (``redislite``) with ``pytest-asyncio``:

.. code-block:: python

   # conftest.py
   import pytest
   import pytest_asyncio
   from redislite import FalkorDB
   from runic.ogm.driver.falkordb import AsyncFalkorDBDriver

   @pytest_asyncio.fixture
   async def async_driver():
       db = FalkorDB(protocol=2)
       graph = db.select_graph("test_async")
       driver = AsyncFalkorDBDriver(graph)
       yield driver

   # test_myfeature.py
   import pytest

   @pytest.mark.asyncio
   async def test_create_user(async_driver):
       from runic.ogm import AsyncSession
       async with AsyncSession(async_driver) as session:
           session.add(User(id="u1", name="Alice", email="a@example.com"))
           await session.commit()
           user = await session.get(User, "u1")
           assert user is not None

.. seealso::

   :doc:`testing` — embedded FalkorDB setup for sync tests; gotchas around
   unique graph names.

----

Summary of async gotchas
--------------------------

- **Lazy loading raises** :exc:`~runic.ogm.exceptions.LazyLoadError` — always
  use ``fetch=[]`` or a traversal query.
- **Detached entity access** also raises :exc:`~runic.ogm.exceptions.DetachedEntityError`
  after the session closes.  Load related data *before* closing.
- ``add()`` / ``add_all()`` / ``delete()`` are sync — call them without
  ``await``.
- All query builder methods called via ``session.query()`` return async
  builders — ``await qb.all()``.
- ``fulltext_search()`` and ``vector_search()`` return async builders too.

.. seealso::

   :doc:`session` — full sync session reference and API summary
