Session & Unit of Work
======================

The :class:`~runic.ogm.session.session.Session` (and its async twin
:class:`~runic.ogm.session.async_session.AsyncSession`) is the unit-of-work
manager for Cypher-based graph databases.  It owns all mutations, manages
the identity map, and controls the flush/commit lifecycle.

.. seealso::

   `examples/orm/01_simple_crud.py <https://github.com/jenreh/runic/blob/main/examples/orm/01_simple_crud.py>`_
      Session lifecycle, mutations, flush, commit, and rollback in a single runnable file.

   `examples/orm/04_pagination_and_custom_queries.py <https://github.com/jenreh/runic/blob/main/examples/orm/04_pagination_and_custom_queries.py>`_
      ``session.execute()`` for raw write queries; custom repository methods; offset pagination.

Opening a session
-----------------

``Session`` accepts a :class:`~runic.ogm.driver.GraphDriver` (or
:class:`~runic.ogm.driver.AsyncGraphDriver` for the async variant).
Use the helpers in ``runic.ogm.driver`` to build one:

.. code-block:: python

   from runic.ogm import Session, create_driver

   # FalkorDB
   driver = create_driver("falkordb", host="localhost", port=6379, graph="myapp")
   with Session(driver) as session:
       ...   # commit on success, rollback on exception

   # ArcadeDB (via Bolt)
   driver = create_driver(
       "arcadedb",
       host="localhost", port=7687, database="mydb",
       username="root", password="playwithdata",
   )
   with Session(driver) as session:
       ...

Mutations
---------

All writes go through the Session, never the Repository.

.. code-block:: python

   from runic.ogm import Session

   with Session(driver) as session:
       # add: transient → pending; CREATE on flush
       session.add(entity)
       session.add_all([e1, e2])

       # update: set any field → _dirty = True; MERGE SET on flush
       entity.name = "New Name"

       # delete: persistent → deleted; DETACH DELETE on flush
       session.delete(entity)

       session.commit()    # flush + clear pending/deleted sets

Single-entity lookup
--------------------

``session.get()`` checks the identity map first, then queries the graph.
Returns ``None`` if not found.

.. code-block:: python

   person = session.get(Person, "alice")
   person_with_rels = session.get(Person, "alice", fetch=["company"])

Flush and commit
----------------

.. code-block:: python

   session.flush()     # execute writes; does not clear identity map
   session.commit()    # flush + clear pending/deleted sets

Transaction model
~~~~~~~~~~~~~~~~~

Each ``flush()`` sends each pending entity as its own query.  Entities
with ``generated=True`` IDs must be flushed individually so the returned
ID can be assigned before the next write.

``rollback()`` discards the **un-flushed** pending/deleted sets only.  Once
``flush()`` has executed queries, those writes are permanent.

Rollback
--------

.. code-block:: python

   session = Session(driver)
   try:
       session.add(Person(id="bob", name="Bob", email="bob@example.com"))
       session.rollback()   # discard pending; nothing written to graph
   finally:
       session.close()

The context manager calls ``rollback()`` automatically on exception.

Expire and refresh
------------------

.. code-block:: python

   session.expire(entity)   # clear cached attrs; reloaded on next access
   session.refresh(entity)  # immediate re-query from graph

Expunge
-------

.. code-block:: python

   session.expunge(entity)   # remove from session → detached; no DB action
   session.expunge_all()

Composable statement execution
------------------------------

:func:`~runic.ogm.query.select` creates a
:class:`~runic.ogm.query.builder.QueryBuilder` that is **not bound to a
session**.  Build the statement freely — including conditional filters — then
pass it to one of the session execution methods:

.. code-block:: python

   from runic.ogm import select

   stmt = select(Person).where(Person.active == True)
   if min_age > 0:
       stmt = stmt.where(Person.age >= min_age)

   # All five execution methods accept a QueryBuilder
   people: list[Person]  = session.scalars(stmt)
   person: Person | None = session.scalar(stmt)
   n:      int           = session.count(stmt)
   rows:   list[dict]    = session.all_rows(stmt)

   # Async sessions accept the same stmt
   people = await async_session.scalars(stmt)

The same ``stmt`` object is **reusable** — execute it multiple times, against
different sessions if needed.  Each execution restores the session binding to
``None`` afterwards.

.. list-table::
   :header-rows: 1
   :widths: 40 60

   * - Method
     - Returns
   * - ``scalars(stmt)``
     - ``list[T]`` — decoded node entities; ``T`` inferred from ``QueryBuilder[T]``
   * - ``scalar(stmt)``
     - ``T | None`` — first entity, or ``None`` if the result set is empty
   * - ``count(stmt)``
     - ``int`` — total matching nodes
   * - ``all_rows(stmt)``
     - ``list[dict[str, Any]]`` — raw column-value dicts
   * - ``all_with_edges(stmt)``
     - ``list[tuple[Any, ...]]`` — tuples of ``(node, edge, node)``

.. tip::

   ``session.query(Person).where(...).all()`` is still fully supported.
   Prefer ``select()`` when you need to compose the query across multiple
   code paths before executing.

Raw Cypher
----------

For the common cases prefer the :doc:`query builder <query_builder>`.
``session.execute()`` is the escape hatch for write mutations and Cypher
features not covered by the builder.

.. code-block:: python

   from runic.ogm import select

   # Prefer select() + session.scalars() for reads
   stmt = (
       select(Person)
       .where(Person.id == "alice")
       .alias("p")
       .traverse(Person.knows).alias("f")
   )
   friends: list[Person] = session.scalars(stmt)

   # Write mutations (SET, REMOVE, …) require session.execute(write=True)
   session.execute(
       "MATCH (t:Trip {status: $old}) SET t.status = $new",
       {"old": "draft", "new": "archived"},
       write=True,
   )

Session API summary
-------------------

.. list-table::
   :header-rows: 1
   :widths: 40 60

   * - Method
     - Description
   * - ``add(entity)``
     - Transient/detached → pending
   * - ``add_all([entities])``
     - Batch ``add``
   * - ``delete(entity)``
     - Persistent → deleted; ``DETACH DELETE`` on flush
   * - ``get(EntityClass, pk, fetch=[])``
     - Identity map check → graph query; ``None`` if not found
   * - ``flush()``
     - Execute pending/dirty/deleted sets; clear ``_dirty``
   * - ``commit()``
     - ``flush()`` + clear pending/deleted sets
   * - ``rollback()``
     - Discard un-flushed pending/deleted sets; expire persistent entities
   * - ``expire(entity)``
     - Invalidate attribute cache; reloaded on next access
   * - ``refresh(entity)``
     - Immediate re-query from graph
   * - ``expunge(entity)``
     - Remove from session (→ detached); no graph action
   * - ``expunge_all()``
     - Expunge all tracked entities
   * - ``scalars(stmt)``
     - Execute a :func:`~runic.ogm.query.select` statement; return ``list[T]``
   * - ``scalar(stmt)``
     - Execute a statement; return first ``T`` or ``None``
   * - ``count(stmt)``
     - Execute a statement; return row count as ``int``
   * - ``all_rows(stmt)``
     - Execute a statement; return ``list[dict[str, Any]]``
   * - ``all_with_edges(stmt)``
     - Execute a statement; return ``list[tuple[Any, ...]]``
   * - ``execute(cypher, params, write)``
     - Raw Cypher; returns :class:`~runic.ogm.driver.GraphResult` (``.rows``, ``.columns``)
   * - ``close()``
     - ``expunge_all()`` + release connection

Async parity
------------

:class:`~runic.ogm.session.async_session.AsyncSession` mirrors all of the
above with ``async``/``await``:

.. code-block:: python

   async with AsyncSession(AsyncFalkorDBDriver(graph)) as session:
       repo = AsyncRepository(session, Trip)
       trips = await repo.find_all()
       for trip in trips:
           trip.status = "archived"
       await session.commit()

.. note::

   Lazy loading is **not** available in ``AsyncSession`` — ``__get__``
   cannot ``await``.  Use ``fetch=[...]`` on every read.

Connection management
---------------------

:class:`~runic.ogm.session.connection_pool.ConnectionManager` and
:class:`~runic.ogm.session.connection_pool.AsyncConnectionManager` wrap a
FalkorDB graph handle for reuse across sessions:

.. code-block:: python

   from runic.ogm import ConnectionManager

   manager = ConnectionManager(graph)
   with manager.session() as session:
       ...
