Session & Unit of Work
======================

The :class:`~runic.orm.session.session.Session` (and its async twin
:class:`~runic.orm.session.async_session.AsyncSession`) is the unit-of-work
manager for Cypher-based graph databases.  It owns all mutations, manages
the identity map, and controls the flush/commit lifecycle.

.. seealso::

   `examples/orm/01_simple_crud.py <https://github.com/jenreh/runic/blob/main/examples/orm/01_simple_crud.py>`_
      Session lifecycle, mutations, flush, commit, and rollback in a single runnable file.

   `examples/orm/04_pagination_and_custom_queries.py <https://github.com/jenreh/runic/blob/main/examples/orm/04_pagination_and_custom_queries.py>`_
      ``session.execute()`` for raw write queries; custom repository methods; offset pagination.

Opening a session
-----------------

``Session`` accepts a :class:`~runic.orm.driver.GraphDriver` (or
:class:`~runic.orm.driver.AsyncGraphDriver` for the async variant).
Use the helpers in ``runic.orm.driver`` to build one:

.. code-block:: python

   from runic.orm import Session, create_driver

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

   from runic.orm import Session

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

Raw Cypher
----------

``session.execute()`` runs a Cypher query and returns a raw
``QueryResult``.  No entity mapping is applied.

.. code-block:: python

   result = session.execute(
       "MATCH (p:Person)-[:KNOWS]->(f:Person) WHERE p.id = $id RETURN f.name",
       {"id": "alice"},
   )
   for row in result.rows:
       print(row[0])

   # Write queries require write=True
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
   * - ``execute(cypher, params, write)``
     - Raw Cypher; returns :class:`~runic.orm.driver.GraphResult` (``.rows``, ``.columns``)
   * - ``close()``
     - ``expunge_all()`` + release connection

Async parity
------------

:class:`~runic.orm.session.async_session.AsyncSession` mirrors all of the
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

:class:`~runic.orm.session.connection_pool.ConnectionManager` and
:class:`~runic.orm.session.connection_pool.AsyncConnectionManager` wrap a
FalkorDB graph handle for reuse across sessions:

.. code-block:: python

   from runic.orm import ConnectionManager

   manager = ConnectionManager(graph)
   with manager.session() as session:
       ...
