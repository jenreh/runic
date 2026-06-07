Supported Drivers
=================

Runic's ORM is database-agnostic.  Every backend is hidden behind the
:class:`~runic.orm.driver.GraphDriver` /
:class:`~runic.orm.driver.AsyncGraphDriver` Protocol so the rest of the
stack (Session, Repository, QueryBuilder) never talks to the database
directly.

Use :func:`~runic.orm.driver.factory.create_driver` as the recommended
entry-point, or instantiate a driver class directly for advanced cases.

.. code-block:: python

   from runic.orm import create_driver

   driver = create_driver("falkordb", host="localhost", port=6379, graph="myapp")
   driver = create_driver(
       "arcadedb", host="localhost", port=7687,
       database="mydb", username="root", password="secret",
   )

----

Feature matrix
--------------

The table below summarises what is available per backend.

.. list-table::
   :header-rows: 1
   :widths: 35 20 20 25

   * - Feature
     - FalkorDB
     - ArcadeDB
     - Generic Bolt
   * - Protocol
     - Redis (falkordb)
     - Bolt (neo4j driver)
     - Bolt (neo4j driver)
   * - Sync driver
     - ✓
     - ✓
     - ✓
   * - Async driver
     - ✓
     - ✗
     - ✗
   * - Vector KNN queries
     - ✓ — native ``vecf32``
     - ✓ — ``CALL vector.neighbors``
     - dialect-dependent
   * - Fulltext search
     - ✓ — ``db.idx.fulltext.queryNodes``
     - ✗ — raises ``NotImplementedError``
     - dialect-dependent
   * - String interning (``intern()``)
     - ✓
     - ✗
     - dialect-dependent
   * - TypeConverter Cypher wrappers
     - ✓ — e.g. ``vecf32()``, ``toPoint()``
     - ✗ — raw Python values only
     - dialect-dependent
   * - TLS / encrypted connections
     - ✗ — Redis, no TLS in driver
     - ✗ — ``bolt://`` (plaintext) only
     - ✓ — ``bolt+s://`` or ``bolt+ssc://``
   * - Multiple graphs per connection
     - ✓ — ``select_graph("name")``
     - ✗ — one database per driver
     - ✗ — one database per driver
   * - Required Python package
     - ``falkordb``
     - ``neo4j``
     - ``neo4j``

----

FalkorDB
--------

**Supported**

- Sync (:class:`~runic.orm.driver.falkordb.FalkorDBDriver`) and async
  (:class:`~runic.orm.driver.falkordb.AsyncFalkorDBDriver`) execution.
- Full fulltext search via ``CALL db.idx.fulltext.queryNodes()``.
- Vector KNN using ``vecf32(alias.field) <-> vecf32($vec)`` (FalkorDB
  native similarity syntax).
- :func:`~runic.orm.core.descriptors.Field` options ``interned=True``
  (wraps the value in ``intern()`` on write) and custom
  :class:`~runic.orm.core.types.TypeConverter` Cypher functions
  (e.g. ``vecf32``, ``toPoint``).
- Multiple named graphs on the same server via ``graph=`` parameter.

**Not supported / limitations**

- No TLS support — FalkorDB communicates over Redis, which this driver
  does not encrypt.
- :class:`~runic.orm.driver.falkordb.AsyncFalkorDBDriver` requires an
  *async* FalkorDB graph handle; there is no built-in
  ``create_async_falkordb_driver`` factory — you must pass the handle
  yourself.

.. code-block:: python

   from runic.orm import create_driver, Session

   driver = create_driver("falkordb", host="localhost", port=6379, graph="myapp")
   with Session(driver) as session:
       ...

   # Async — build the handle manually
   from falkordb import FalkorDB
   from runic.orm.driver.falkordb import AsyncFalkorDBDriver

   async_handle = FalkorDB(host="localhost", port=6379).select_graph("myapp")
   async_driver = AsyncFalkorDBDriver(async_handle)

----

ArcadeDB
--------

ArcadeDB is accessed over the **Bolt protocol** using the ``neo4j``
Python driver (``encrypted=False``).

**Supported**

- Sync execution via :class:`~runic.orm.driver.bolt.BoltDriver`.
- Vector KNN via ``CALL vector.neighbors('<type>[<field>]', $vec, $k)
  YIELD node, distance``.
- Standard ``MATCH``/``MERGE``/``DELETE`` Cypher queries.

**Not supported / limitations**

- **No async driver.** There is no async Bolt driver in runic at this time.
- **No fulltext search.** Calling
  :meth:`~runic.orm.query.builder.QueryBuilder.fulltext` raises
  ``NotImplementedError``.  Use the ArcadeDB HTTP API directly for
  fulltext if needed.
- **No TypeConverter Cypher wrappers.** ArcadeDB stores raw Python values
  as-is; ``vecf32()`` and ``intern()`` are not applied.
- **Plaintext Bolt only.** ``create_arcadedb_driver`` forces
  ``bolt://`` (no TLS).  To use TLS, instantiate
  :class:`~runic.orm.driver.bolt.BoltDriver` directly with a
  ``bolt+s://`` URI.
- No ``id()``-cast — ArcadeDB does not require ``toInteger()`` on
  generated-ID lookups.

.. code-block:: python

   from runic.orm import create_driver, Session

   driver = create_driver(
       "arcadedb",
       host="localhost",
       port=7687,
       database="mydb",
       username="root",
       password="playwithdata",
   )
   with Session(driver) as session:
       ...

----

Generic Bolt (custom backends)
------------------------------

:class:`~runic.orm.driver.bolt.BoltDriver` can connect to **any
Bolt-compatible graph database** (Neo4j, MemGraph, …) by supplying a
custom :class:`~runic.orm.driver.GraphDialect`.

.. code-block:: python

   from runic.orm.driver.bolt import BoltDriver
   from myapp.dialects import Neo4jDialect

   driver = BoltDriver.from_params(
       host="localhost",
       port=7687,
       database="neo4j",
       username="neo4j",
       password="secret",
       dialect=Neo4jDialect(),
       encrypted=True,          # switches to bolt+s://
   )

**TLS note** — the ``encrypted`` flag is a convenience wrapper: it
rewrites ``bolt://`` → ``bolt+s://`` (or vice-versa).  You can bypass it
by passing a URI directly to the ``BoltDriver`` constructor.
