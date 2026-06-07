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

   # FalkorDB
   driver = create_driver("falkordb", host="localhost", port=6379, graph="myapp")
   # ArcadeDB (via Bolt)
   driver = create_driver(
       "arcadedb", host="localhost", port=7687,
       database="mydb", username="root", password="secret",
   )
   # Neo4j
   driver = create_driver(
       "neo4j", host="localhost", port=7687,
       database="neo4j", username="neo4j", password="secret",
   )
   # Memgraph
   driver = create_driver(
       "memgraph", host="localhost", port=7687,
       database="memgraph", username="", password="",
   )
   # Apache AGE (PostgreSQL graph extension)
   driver = create_driver(
       "age", host="localhost", port=5432,
       database="postgres", graph="my_graph",
       username="postgres", password="secret",
   )

----

Feature matrix
--------------

.. list-table::
   :header-rows: 1
   :widths: 30 14 14 14 14 14

   * - Feature
     - FalkorDB
     - ArcadeDB
     - Neo4j
     - Memgraph
     - Apache AGE
   * - Protocol / client
     - Redis (falkordb)
     - Bolt (neo4j)
     - Bolt (neo4j)
     - Bolt (neo4j)
     - SQL (psycopg3)
   * - Sync driver
     - ✓
     - ✓
     - ✓
     - ✓
     - ✓
   * - Async driver
     - ✓
     - ✗
     - ✗
     - ✗
     - ✗
   * - Vector KNN queries
     - ✓ — native ``vecf32``
     - ✓ — ``CALL vector.neighbors``
     - ✓ — ``CALL db.index.vector.queryNodes``
     - ✓ — ``CALL vector_search.search``
     - ✗ — use pgvector
   * - Fulltext search
     - ✓ — ``db.idx.fulltext.queryNodes``
     - ✗ — not supported by ArcadeDB ORM driver
     - ✓ — ``CALL db.index.fulltext.queryNodes``
     - ✓ — ``CALL text_search.search_all``
     - ✗ — use PostgreSQL FTS
   * - String interning (``intern()``)
     - ✓
     - ✗
     - ✗
     - ✗
     - ✗
   * - TypeConverter Cypher wrappers
     - ✓ — ``vecf32()``, ``toPoint()``
     - ✗
     - ✗
     - ✗
     - ✗
   * - TLS / encrypted connections
     - ✗ — Redis, no TLS
     - ✗ — ``bolt://`` only
     - ✓ — ``bolt+s://``
     - ✓ — ``bolt+s://``
     - ✓ — via PostgreSQL SSL
   * - Multiple graphs per connection
     - ✓ — ``select_graph()``
     - ✗
     - ✗
     - ✗
     - ✓ — one graph per driver
   * - ACID transactions
     - ✗ — each query is atomic
     - ✓ — ``begin`` / ``commit`` / ``rollback``
     - ✓ — ``begin`` / ``commit`` / ``rollback``
     - ✓ — ``begin`` / ``commit`` / ``rollback``
     - ✓ — psycopg3 implicit ``BEGIN``
   * - Migrate adapter (``create_adapter``)
     - ✓ — ``FalkorDBAdapter``
     - ✓ — ``ArcadeDBAdapter``
     - ✓ — ``Neo4jAdapter``
     - ✓ — ``MemgraphAdapter``
     - ✓ — ``AGEAdapter``
   * - IndexManager DDL
     - ✓ — range / fulltext / vector / unique
     - ✓ — range / fulltext / unique (vector via HTTP API)
     - ✓ — range / fulltext / vector / unique (``IF NOT EXISTS``)
     - ✓ — range / text / vector / unique
     - ✗ — log.warning only (PostgreSQL-level DDL required)
   * - Required Python package
     - ``falkordb``
     - ``neo4j``
     - ``neo4j``
     - ``neo4j``
     - ``psycopg[binary]``

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

- No TLS — FalkorDB communicates over Redis, which this driver does not
  encrypt.
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

- **No async driver.**
- **No fulltext search** via the ORM query builder.  The migrate adapter
  issues ``CREATE FULLTEXT INDEX ON \`{label}\` (prop)`` DDL where
  supported; ArcadeDB may accept or reject it depending on configuration.
- **No TypeConverter Cypher wrappers.** Raw Python values stored as-is.
- **Plaintext Bolt only.** ``create_arcadedb_driver`` forces ``bolt://``.
- **No vector index DDL.** ``create_vector_index()`` logs a warning and
  directs you to the ArcadeDB HTTP management API.

.. code-block:: python

   from runic.orm import create_driver, Session

   driver = create_driver(
       "arcadedb",
       host="localhost", port=7687,
       database="mydb", username="root", password="playwithdata",
   )
   with Session(driver) as session:
       ...

----

Neo4j
-----

Neo4j is accessed over the **Bolt protocol** using the ``neo4j`` Python
driver.

**Supported**

- Sync execution via :class:`~runic.orm.driver.bolt.BoltDriver`.
- Fulltext search via ``CALL db.index.fulltext.queryNodes()``.  The
  query uses an index named after the label (e.g. ``Person``).
- Vector KNN via ``CALL db.index.vector.queryNodes()``.  A vector index
  named ``{label}_{prop}`` (e.g. ``Article_embedding``) must exist.
- TLS via ``bolt+s://`` (set ``encrypted=True``, the default).
- **Migrate adapter** (``create_adapter("neo4j", ...)``) — issues full
  DDL for all index/constraint types via ``IF NOT EXISTS`` for
  idempotency.
- **IndexManager** — pass a ``Neo4jAdapter`` to
  :class:`~runic.orm.schema.IndexManager` to create indexes from your
  entity definitions:

  .. code-block:: python

     from runic.migrate.adapters import create_adapter
     from runic.orm.schema.index_manager import IndexManager

     adapter = create_adapter("neo4j", database="neo4j", password="secret")
     manager = IndexManager(adapter)
     manager.create_indexes(Person)   # issues CREATE INDEX / CONSTRAINT DDL

**Index naming convention** (Neo4j 5.x)

.. code-block:: text

   fulltext:  CREATE FULLTEXT INDEX {label}  IF NOT EXISTS FOR (n:{label}) ON EACH [n.prop1, n.prop2]
   range:     CREATE INDEX {label}_{prop}    IF NOT EXISTS FOR (n:{label}) ON (n.{prop})
   vector:    CREATE VECTOR INDEX {label}_{prop}  IF NOT EXISTS FOR (n:{label}) ON (n.{prop})
   unique:    CREATE CONSTRAINT {label}_{prop}_unique  IF NOT EXISTS FOR (n:{label}) REQUIRE n.{prop} IS UNIQUE

**Not supported / limitations**

- **No async driver.**
- **No TypeConverter Cypher wrappers.**
- Vector index dimension is not stored in ``Field()`` metadata; pass
  ``dimension`` when calling ``create_vector_index()`` directly, or
  pre-create vector indexes via Cypher DDL.

.. code-block:: python

   from runic.orm import create_driver, Session

   driver = create_driver(
       "neo4j",
       host="localhost", port=7687,
       database="neo4j", username="neo4j", password="secret",
       encrypted=True,
   )
   with Session(driver) as session:
       ...

----

Memgraph
--------

Memgraph is accessed over the **Bolt protocol** using the ``neo4j``
Python driver, with Memgraph-specific ``text_search`` and
``vector_search`` MAGE module procedures.

**Supported**

- Sync execution via :class:`~runic.orm.driver.bolt.BoltDriver`.
- Fulltext search via ``CALL text_search.search_all()``.  Uses a
  whole-label text index named after the label (``CREATE TEXT INDEX
  {label} ON :{label}``).
- Vector KNN via ``CALL vector_search.search()``.  A vector index named
  ``{label}_{prop}`` must exist.
- TLS available (set ``encrypted=True``).
- **Migrate adapter** (``create_adapter("memgraph", ...)``) — issues
  DDL for range, text, vector, and unique constraint creation.
- **IndexManager** — pass a ``MemgraphAdapter`` to
  :class:`~runic.orm.schema.IndexManager`:

  .. code-block:: python

     from runic.migrate.adapters import create_adapter
     from runic.orm.schema.index_manager import IndexManager

     adapter = create_adapter("memgraph", database="memgraph")
     manager = IndexManager(adapter)
     manager.create_indexes(Post)    # issues CREATE INDEX / CONSTRAINT DDL

**Index naming convention** (Memgraph)

.. code-block:: text

   text index: CREATE TEXT INDEX {label} ON :{label}         (whole-label; one per label)
   range:      CREATE INDEX ON :{label}({prop})               (idempotent)
   vector:     CREATE VECTOR INDEX {label}_{prop} ON :{label}({prop}) WITH CONFIG {...}
   unique:     CREATE CONSTRAINT ON (n:{label}) ASSERT n.{prop} IS UNIQUE

.. note::

   Memgraph text indexes cover the **entire label** — a single text index
   per label is created regardless of how many ``index_type="FULLTEXT"``
   fields are declared.  Full-text queries search all string properties on
   the node.  Requires the MAGE ``text_search`` module.

**Not supported / limitations**

- **No async driver.**
- **No TypeConverter Cypher wrappers.**
- Vector index dimension is not stored in ``Field()`` metadata; pass
  ``dimension`` when calling ``create_vector_index()`` directly, or
  pre-create vector indexes via Cypher DDL.

.. code-block:: python

   from runic.orm import create_driver, Session

   driver = create_driver(
       "memgraph",
       host="localhost", port=7687,
       database="memgraph", username="", password="",
   )
   with Session(driver) as session:
       ...

----

Apache AGE
----------

`Apache AGE <https://age.apache.org/>`_ is a **PostgreSQL extension** that
adds openCypher graph query support to an existing PostgreSQL database.
Cypher queries are executed via the ``cypher()`` SQL function wrapped in a
``SELECT`` statement::

    SELECT * FROM cypher('graph_name', $$ CYPHER $$ [, params::agtype])
        AS (col0 agtype, ...);

The runic driver uses **psycopg3** (``psycopg[binary]``) for the
PostgreSQL connection and handles the ``cypher()`` wrapping automatically.
Parameters are serialised as an agtype JSON map and passed as the third
argument to ``cypher()``, making them available inside the Cypher query as
``$param_name`` — identical to how runic's QueryBuilder emits ``$p0``,
``$p1``, etc.

**Supported**

- Sync execution via :class:`~runic.orm.driver.age.AGEDriver`.
- Automatic agtype decoding — vertices and edges are returned as
  :class:`~runic.orm.driver.age.AGENode` /
  :class:`~runic.orm.driver.age.AGEEdge` wrappers.
- Standard ``MATCH``/``MERGE``/``DELETE`` Cypher queries.
- Automatic graph creation on first connect (if the graph does not exist).
- TLS — supported via PostgreSQL SSL (pass SSL keyword arguments directly
  to ``psycopg.connect`` by instantiating
  :class:`~runic.orm.driver.age.AGEDriver` manually).

**Not supported / limitations**

- **No async driver.**  Async support requires an async psycopg3 connection
  which is not yet wired up.
- **No fulltext search** in Cypher.  Use PostgreSQL ``tsvector``/``tsquery``
  full-text search directly on the underlying tables.
- **No vector KNN** in Cypher.  Use `pgvector
  <https://github.com/pgvector/pgvector>`_ on the underlying tables.
- **No TypeConverter Cypher wrappers** (no ``vecf32()``, ``intern()``).
- **No index DDL** in runic's migration adapter.  AGE does not expose
  Cypher-level index creation; create PostgreSQL indexes on the underlying
  ``ag_label`` tables directly.

.. code-block:: python

   from runic.orm import create_driver, Session

   driver = create_driver(
       "age",
       host="localhost",
       port=5432,
       database="postgres",
       graph="my_graph",
       username="postgres",
       password="secret",
   )
   with Session(driver) as session:
       ...

**Prerequisites** — the ``age`` extension must be installed in PostgreSQL:

.. code-block:: sql

   -- run once as superuser
   CREATE EXTENSION IF NOT EXISTS age;

The runic driver runs ``LOAD 'age'`` and sets
``search_path = ag_catalog, "$user", public`` automatically on every new
connection.

----

Generic Bolt (custom backends)
------------------------------

:class:`~runic.orm.driver.bolt.BoltDriver` can connect to **any
Bolt-compatible graph database** by supplying a custom
:class:`~runic.orm.driver.GraphDialect`.

.. code-block:: python

   from runic.orm.driver.bolt import BoltDriver
   from myapp.dialects import MyDialect

   driver = BoltDriver.from_params(
       host="localhost",
       port=7687,
       database="neo4j",
       username="neo4j",
       password="secret",
       dialect=MyDialect(),
       encrypted=True,          # switches to bolt+s://
   )

**TLS note** — the ``encrypted`` flag is a convenience wrapper: it
rewrites ``bolt://`` → ``bolt+s://`` (or vice-versa).  You can bypass it
by passing a URI directly to the ``BoltDriver`` constructor.
