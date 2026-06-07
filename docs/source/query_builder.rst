Query Builder
=============

The query builder lets you construct Cypher queries from your ORM model
declarations using a fluent Python API — without writing raw Cypher strings for
the common cases.  This page explains *how* the builder works, *what Cypher it
emits*, and *when* to use each feature so you can read the result confidently
and know when to reach for something else.

----

How the query builder works
----------------------------

:func:`~runic.orm.query.select` returns a
:class:`~runic.orm.query.builder.QueryBuilder` that accumulates clauses as you
chain method calls.  Nothing is sent to the database until you pass the
statement to a session execution method (``session.scalars()``,
``session.scalar()``, ``session.count()``, etc.).

At that point the session:

1. **Generates a Cypher string and a parameter dict** from the accumulated
   clauses.
2. **Sends the query to the driver** via the session's connection.
3. **Decodes each result row** using the ORM mapper — the same code path used
   by ``session.get()`` and ``repo.find_all()``.
4. **Registers returned entities in the session's identity map**, so change
   tracking works on them exactly as if you had loaded them any other way.

Because the builder goes through the same mapper and identity map, you can mix
builder queries and direct ``session.get()`` calls freely within the same
session.

To see the Cypher the builder *would* emit without executing it, call
:meth:`~runic.orm.query.builder.QueryBuilder.build` — this works on an unbound
statement (no session required)::

    from runic.orm import select

    cypher: str
    params: dict[str, Any]
    cypher, params = select(User).where(User.active == True).build()
    print(cypher)
    # MATCH (n:User) WHERE (n.active = $p0) RETURN n
    print(params)
    # {'p0': True}

Use ``.build()`` freely while learning the builder or debugging unexpected
results.

.. seealso::

   `examples/orm/07_query_builder_basics.py <https://github.com/jenreh/runic/blob/main/examples/orm/07_query_builder_basics.py>`_
      Covers every foundational feature: comparisons, string predicates, null
      checks, membership, boolean composition, ordering, pagination, projection,
      and all terminal methods.

----

Entry points
------------

There are four starting points for a query.  All four return a
:class:`~runic.orm.query.builder.QueryBuilder` whose chaining and terminal
methods behave identically.

.. list-table::
   :header-rows: 1
   :widths: 42 58

   * - Call
     - When to use
   * - ``select(NodeCls)``
     - **Preferred.** Session-independent statement; execute via
       ``session.scalars(stmt)`` etc.  Enables dynamic query composition.
   * - ``session.query(NodeCls)``
     - Session-bound query; terminal methods (``all()``, ``count()``, …) execute
       immediately.  Equivalent to ``session.scalars(select(NodeCls)...)``.
   * - ``repo.query()``
     - Equivalent to ``session.query(T)``; useful when the repository type is
       already in scope.
   * - ``session.fulltext_search(Cls, query=...)``
     - Full-text search queries — wraps a backend-specific ``CALL`` procedure.
       See `Full-text search`_.
   * - ``session.vector_search(Cls, field=..., vector=..., k=...)``
     - Approximate nearest-neighbour vector queries.
       See `Vector KNN search`_.

----

Composable statements
---------------------

:func:`~runic.orm.query.select` creates a :class:`~runic.orm.query.builder.QueryBuilder`
that is **not bound to a session**, making it easy to build dynamic queries from
UI filters, request parameters, or any conditional logic — then hand the
finished statement to a session for execution.

.. code-block:: python

   from runic.orm import select

   # Build without touching the database
   stmt = select(User).where(User.active == True)

   if min_age > 0:
       stmt = stmt.where(User.age >= min_age)
   if name_filter:
       stmt = stmt.where(User.name.contains(name_filter))

   stmt = stmt.order_by(User.name).limit(page_size)

   # Execute once you have a session
   users: list[User]  = session.scalars(stmt)
   user:  User | None = session.scalar(stmt)
   n:     int         = session.count(stmt)
   rows:  list[dict]  = session.all_rows(stmt)

   # Async sessions work with the same stmt
   users = await async_session.scalars(stmt)

The same ``stmt`` object is **reusable** — execute it multiple times, against
different sessions if needed.  Each call to ``session.scalars()`` etc. restores
the statement's binding to ``None`` after execution.

Calling terminal methods directly on an unbound statement raises a clear
:exc:`RuntimeError`::

    stmt = select(User)
    stmt.all()   # RuntimeError: not bound to a session — use session.scalars(stmt)

.. tip::

   ``session.query(User).where(...).all()`` is still fully supported and
   equivalent to ``session.scalars(select(User).where(...))``.  Prefer
   ``select()`` when you need to compose the query across multiple code paths.

----

Filtering
---------

Predicates are built by applying Python comparison operators to **class-level
field accesses**.  The operator overloads on
:class:`~runic.orm.core.descriptors.FieldDescriptor` return lightweight
:class:`~runic.orm.query.expressions.FilterExpr` objects that the builder
serialises into parameterised Cypher ``WHERE`` clauses.

Two important points before you start:

* **No Python evaluation happens.** ``User.age > 18`` does not evaluate to a
  Python boolean; it returns a :class:`~runic.orm.query.expressions.FilterExpr`
  object.  This means you cannot use it inside a Python ``if`` statement — only
  inside ``.where()``.
* **Parameters are always bound.** The builder never interpolates values
  directly into the Cypher string.  Every value becomes a ``$pN`` parameter,
  which prevents Cypher injection and enables query-plan caching.

Comparison operators
~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    # Equality / inequality
    User.name == "Alice"          # WHERE n.name = $p0
    User.status != "banned"       # WHERE n.status <> $p0

    # None comparisons map to IS NULL / IS NOT NULL
    User.deleted_at == None       # WHERE n.deleted_at IS NULL
    User.email != None            # WHERE n.email IS NOT NULL

    # Numeric comparison
    User.age > 18                 # WHERE n.age > $p0
    User.score >= 4.5             # WHERE n.score >= $p0
    User.age < 65                 # WHERE n.age < $p0
    User.credit <= 0              # WHERE n.credit <= $p0

String predicates
~~~~~~~~~~~~~~~~~

String predicates map directly to Cypher string operators:

.. code-block:: python

    User.name.contains("ali")          # WHERE n.name CONTAINS $p0
    User.email.startswith("admin@")    # WHERE n.email STARTS WITH $p0
    User.url.endswith(".org")          # WHERE n.url ENDS WITH $p0
    User.bio.matches(r".*graph.*")     # WHERE n.bio =~ $p0  (regex)

.. note::

   Cypher regular expressions follow the Java ``java.util.regex`` syntax.
   Anchoring (``^``, ``$``) and case-insensitive flags (``(?i)``) are
   supported; look-aheads are not.

Null checks
~~~~~~~~~~~

The ``== None`` / ``!= None`` shorthand works, but explicit null-check methods
are clearer in code review::

    User.deleted_at.is_null()          # WHERE n.deleted_at IS NULL
    User.email.is_not_null()           # WHERE n.email IS NOT NULL

List membership
~~~~~~~~~~~~~~~

.. code-block:: python

    # IN list
    User.role.in_(["admin", "mod"])    # WHERE n.role IN $p0

    # NOT IN list
    Post.tag.not_in_(["spam"])         # WHERE NOT n.tag IN $p0

The list is passed as a single bound parameter, not expanded inline.

Boolean composition
~~~~~~~~~~~~~~~~~~~

Use the bitwise operators ``&`` (AND), ``|`` (OR), and ``~`` (NOT) to compose
predicates.  These are *not* Python ``and`` / ``or`` / ``not`` — those would
short-circuit and discard the filter objects:

.. code-block:: python

    # AND — both conditions must match
    select(User).where((User.age > 18) & (User.active == True))
    # WHERE (n.age > $p0) AND (n.active = $p1)

    # OR — either condition can match
    select(User).where((User.role == "admin") | (User.role == "mod"))
    # WHERE (n.role = $p0) OR (n.role = $p1)

    # NOT — negate a predicate
    select(User).where(~(User.banned == True))
    # WHERE NOT (n.banned = $p0)

**Multiple ``.where()`` calls are always joined by AND.**  The following two
statements are equivalent:

.. code-block:: python

    select(User).where((User.age > 18) & (User.active == True))

    select(User).where(User.age > 18).where(User.active == True)

Use chained ``.where()`` calls when your predicates are produced independently
(e.g. optional filters in a search function) and ``&`` / ``|`` when you need
explicit OR or complex nesting.

----

Ordering, pagination, and DISTINCT
------------------------------------

These clauses work exactly as their Cypher counterparts suggest:

.. code-block:: python

    stmt = (
        select(User)
        .order_by(User.created_at, desc=True)   # ORDER BY n.created_at DESC
        .skip(40)                                # SKIP 40
        .limit(20)                               # LIMIT 20
    )
    users: list[User] = session.scalars(stmt)

``skip`` and ``limit`` together implement offset-based pagination.  For
cursor-based or keyset pagination, filter on an indexed field instead::

    stmt = (
        select(User)
        .where(User.created_at < last_seen_ts)
        .order_by(User.created_at, desc=True)
        .limit(20)
    )
    users: list[User] = session.scalars(stmt)

Use ``.distinct()`` to deduplicate the ``RETURN`` clause:

.. code-block:: python

    # Unique countries across all users — project() + all_rows() for scalar columns
    rows: list[dict] = session.all_rows(select(User).distinct().project(User.country))
    countries: list[str] = [r["n.country"] for r in rows]
    # RETURN DISTINCT n.country

----

Projection — returning scalar values
--------------------------------------

By default, the query returns fully decoded node instances.  Use
:meth:`~runic.orm.query.builder.QueryBuilder.project` when you only need a
subset of properties — this avoids loading full node objects and reduces the
data transferred from the database.

.. code-block:: python

    # Single field → flat list via session.all_rows() then extract
    rows = session.all_rows(select(User).project(User.email))
    emails: list[str] = [r["n.email"] for r in rows]
    # RETURN n.email  →  ["alice@example.com", "bob@example.com", ...]

    # Multiple fields → list of dicts via session.all_rows()
    rows: list[dict[str, Any]] = session.all_rows(select(User).project(User.name, User.age))
    # RETURN n.name, n.age  →  [{"n.name": "Alice", "n.age": 30}, ...]

When to use projection vs full node loading:

* Use **full node loading** (``all()``, ``one()``) when you need tracked objects
  with full change-tracking, relationship loading, or type-converted fields.
* Use **projection** when you are reading a single denormalised view for display
  or export and do not need to mutate or traverse the result.

----

Aggregation
-----------

The query builder ships aggregation helpers that map to Cypher's built-in
aggregate functions.  Import them from :mod:`runic.orm.query`:

.. code-block:: python

    from runic.orm.query import count, avg, sum_, min_, max_, collect

Use :meth:`~runic.orm.query.builder.QueryBuilder.aggregate` to add one or more
aggregation expressions to the ``RETURN`` clause.  The ``.as_("name")`` call
sets the Cypher alias for that column, which you use to retrieve the value from
the result dict returned by ``.all_rows()``.

Simple aggregation (no grouping)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

When there is no ``group_by``, the query collapses to a single row:

.. code-block:: python

    # Total number of users
    rows = session.all_rows(select(User).aggregate(count().as_("total")))
    total: int = rows[0]["total"]
    # MATCH (n:User) RETURN count(*) AS total

    # Average score
    rows = session.all_rows(select(User).aggregate(avg(User.score).as_("avg")))
    avg_score: float = rows[0]["avg"]
    # MATCH (n:User) RETURN avg(n.score) AS avg

    # Convenience shortcut — count via session.count()
    n: int = session.count(select(User).where(User.active == True))
    # MATCH (n:User) WHERE n.active = $p0 RETURN count(*)

Grouped aggregation
~~~~~~~~~~~~~~~~~~~

Pass ``group_by=`` to partition results.  The named alias must match an alias
previously set with ``.alias()``::

    stmt = (
        select(User).alias("u")
        .traverse(User.posts).alias("p")
        .aggregate(count("*").as_("post_count"), group_by="u")
    )
    rows: list[dict[str, Any]] = session.all_rows(stmt)
    # OPTIONAL MATCH (u:User)-[:AUTHORED]->(p:Post)
    # RETURN u, count(*) AS post_count

    for row in rows:
        user: User = row["u"]
        post_count: int = row["post_count"]
        print(user.name, "has", post_count, "posts")

Collecting values into a list
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``collect`` maps to Cypher's ``collect()`` aggregate, which gathers values
across rows into a list::

    stmt = (
        select(User).alias("u")
        .traverse(User.tags).alias("t")
        .aggregate(collect("t").as_("tags"), group_by="u")
    )
    rows: list[dict[str, Any]] = session.all_rows(stmt)
    # RETURN u, collect(t) AS tags

.. seealso::

   `examples/orm/10_query_builder_aggregation.py <https://github.com/jenreh/runic/blob/main/examples/orm/10_query_builder_aggregation.py>`_
      ``count``, ``avg``, ``sum_``, ``min_``, ``max_``, ``collect``; grouped
      aggregation with ``group_by``; ``.scalar()`` and ``.all_rows()``.

----

Traversals
----------

The traversal API lets you follow relationship patterns declared on your models
using :func:`~runic.orm.core.descriptors.Relation` fields — without writing
``MATCH (a)-[:TYPE]->(b)`` by hand.

Understanding OPTIONAL MATCH vs MATCH
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

By default, ``.traverse()`` generates an ``OPTIONAL MATCH`` clause.  This is a
**left join**: nodes that have no matching relationship are still returned, with
``None`` for the related node.

Pass ``optional=False`` to get an inner join (``MATCH``), which excludes root
nodes that have no matching relationship:

.. code-block:: text

    OPTIONAL MATCH (u)-[:FRIENDS]->(f)    # all users, friends may be None
    MATCH (u)-[:WORKS_FOR]->(c)           # only users with a company

Choose based on whether missing relationships are valid data or an error.

Single-hop traversal
~~~~~~~~~~~~~~~~~~~~

:meth:`~runic.orm.query.builder.QueryBuilder.traverse` takes a
:func:`~runic.orm.core.descriptors.Relation` field reference.  Call
``.alias()`` on the returned step to name the target node variable and continue
the builder chain:

.. code-block:: python

    # Find all friends of a specific user, aged over 25
    stmt = (
        select(User).alias("u")
        .where(User.id == user_id)
        .traverse(User.friends).alias("f")
        .where(User.age > 25, on="f")   # predicate scoped to "f", not "u"
        .return_target("f")
    )
    friends: list[User] = session.scalars(stmt)
    # MATCH (u:User) WHERE u.id = $p0
    # OPTIONAL MATCH (u)-[:FRIENDS]->(f:User)
    # WHERE f.age > $p1
    # RETURN f

The ``on=`` argument on ``.where()`` scopes a predicate to a specific alias.
Without it, predicates are applied to the root node.

Multi-hop traversal
~~~~~~~~~~~~~~~~~~~

Chain multiple ``.traverse()`` calls to follow a path through several
relationships.  Each step names a new alias::

    stmt = (
        select(User).alias("u")
        .traverse(User.friends).alias("f")
        .traverse(User.authored_posts).alias("p")
        .where(Post.title.contains("graph"), on="p")
        .return_target("p")
    )
    posts_by_friends: list[Post] = session.scalars(stmt)
    # MATCH (u:User)
    # OPTIONAL MATCH (u)-[:FRIENDS]->(f:User)
    # OPTIONAL MATCH (f)-[:AUTHORED]->(p:Post)
    # WHERE p.title CONTAINS $p0
    # RETURN p

Variable-length paths
~~~~~~~~~~~~~~~~~~~~~

Use :meth:`~runic.orm.query.builder.QueryBuilder.repeat` when you need to
traverse an unknown number of hops — equivalent to Cypher's ``*min..max``
quantifier.  This is useful for hierarchies (org charts, category trees,
dependency graphs):

.. code-block:: python

    # Find all managers in the chain above an employee (1 to 5 hops)
    stmt = (
        select(Employee).alias("e")
        .where(Employee.id == emp_id)
        .repeat(Employee.reports_to, min_hops=1, max_hops=5).alias("anc")
    )
    ancestors: list[Employee] = session.scalars(stmt)
    # MATCH (e:Employee) WHERE e.id = $p0
    # MATCH (e)-[:REPORTS_TO*1..5]->(anc:Employee)
    # RETURN anc

    # No upper bound — all reachable nodes
    stmt = select(Station).repeat(Station.connected_to, min_hops=1).alias("s2")
    all_reachable: list[Station] = session.scalars(stmt)
    # MATCH (n:Station)-[:CONNECTED_TO*1..]->(s2:Station) RETURN s2

.. warning::

   Variable-length paths with no upper bound (``*1..``) can be extremely
   expensive on dense graphs.  Always set ``max_hops`` unless you are certain
   the graph has bounded depth.

.. seealso::

   `examples/orm/08_query_builder_traversal.py <https://github.com/jenreh/runic/blob/main/examples/orm/08_query_builder_traversal.py>`_
      Single-hop and multi-hop traversal, ``optional=False`` inner-join,
      ``repeat()``, ``return_target()``, ``with_()``, and alias-scoped
      ``where(on=)``.

----

Aliases
-------

Every node variable in a generated Cypher query has a name.  The root node
defaults to ``n``; traversal targets default to a generated name.  Use
``.alias()`` to assign readable names — this is important when:

* You need to scope a ``.where()`` to a specific node (via ``on=``).
* You need to reference a node in a ``.with_()`` clause.
* You read the generated Cypher via ``.build()`` and want it to be legible.

.. code-block:: python

    select(User).alias("u").where(User.name == "Alice", on="u")
    # MATCH (u:User) WHERE u.name = $p0 RETURN u

----

Edge properties
---------------

By default, relationship patterns are anonymous: ``(a)-[:TYPE]->(b)``.  This is
sufficient for most traversals.  When you need to **filter on edge properties**
or **return edge data alongside the nodes**, pass ``edge_alias=`` to
``.traverse()`` to name the relationship variable:

.. code-block:: python

    class Rated(Edge, type="RATED"):
        score: float = Field()

    class User(Node, labels=["User"]):
        rated: list[Movie] = Relation(
            relationship="RATED",
            direction="OUTGOING",
            target="Movie",
            edge_model=Rated,
        )

    stmt = (
        select(User).alias("u")
        .traverse(User.rated, edge_alias="r").alias("m")
        .where(Rated.score > 4.0, on="r")       # filter on edge property
        .return_nodes("u", "m").return_edge("r")
    )
    rows: list[tuple[User, Rated, Movie]] = session.all_with_edges(stmt)
    # OPTIONAL MATCH (u:User)-[r:RATED]->(m:Movie)
    # WHERE r.score > $p0
    # RETURN u, r, m

    for user, edge, movie in rows:
        user: User
        edge: Rated
        movie: Movie
        print(f"{user.name} rated {movie.title}: {edge.score}/5")

Note that ``return_nodes()`` and ``return_edge()`` explicitly select which
variables appear in ``RETURN``.  ``all_with_edges()`` then unpacks the result
rows into typed tuples.

.. note::

   The existing lazy/eager loading paths (``session.get(..., fetch=[...])``)
   continue to use anonymous relationship patterns.  Named edge variables are
   only emitted by the query builder when ``edge_alias=`` is given.

.. seealso::

   `examples/orm/09_query_builder_edges.py <https://github.com/jenreh/runic/blob/main/examples/orm/09_query_builder_edges.py>`_
      ``traverse(edge_alias=)``, ``return_nodes()`` + ``return_edge()``,
      ``all_with_edges()``, and filtering on edge properties.

----

WITH clause — multi-stage pipelining
--------------------------------------

Cypher's ``WITH`` clause ends one query stage and begins the next, carrying
forward only the named variables.  This is useful when you need to filter an
intermediate result before continuing a traversal — for example, taking the top
N users by score before expanding their relationships:

.. code-block:: python

    stmt = (
        select(User).alias("u")
        .where(User.active == True)
        .order_by(User.score, desc=True)
        .limit(10)
        .with_("u")                       # WITH u  — only u carries forward
        .traverse(User.authored_posts).alias("p")
        .return_target("p")
    )
    top_authors: list[Post] = session.scalars(stmt)
    # MATCH (u:User) WHERE u.active = $p0
    # ORDER BY u.score DESC LIMIT 10
    # WITH u
    # OPTIONAL MATCH (u)-[:AUTHORED]->(p:Post)
    # RETURN p

Without ``WITH``, ``LIMIT`` applies to the final result, not to the
intermediate set of users.  The stage boundary created by ``WITH`` ensures the
limit is applied before the traversal.

----

Terminal methods
----------------

Terminal methods execute the query and return results.  Calling any of them
closes the builder chain.

.. list-table::
   :header-rows: 1
   :widths: 24 76

   * - Method
     - Returns
   * - ``.all()``
     - ``list[T]`` — fully decoded, session-tracked node instances
   * - ``.one()``
     - ``T | None`` — first result (adds ``LIMIT 1``); ``None`` if empty
   * - ``.all_with_edges()``
     - ``list[tuple]`` — ``(NodeA, Edge, NodeB)`` tuples (requires ``return_nodes`` + ``return_edge``)
   * - ``.all_rows()``
     - ``list[dict]`` — raw column-keyed dicts; used with ``project()`` and ``aggregate()``
   * - ``.count()``
     - ``int`` — adds ``count(*)`` to ``RETURN``; no node decoding
   * - ``.scalar()``
     - ``Any`` — first column of the first row; convenient for single-value aggregates
   * - ``.scalars()``
     - ``list[Any]`` — first column of every row; convenient with ``project()``
   * - ``.build()``
     - ``(str, dict)`` — the Cypher string and parameter dict; does **not** execute the query

**Choosing the right terminal method:**

* Default to ``.all()`` when you need trackable entities.
* Use ``.one()`` for lookups where you expect zero or one result.
* Use ``.count()`` or ``.scalar()`` for aggregates to avoid decoding overhead.
* Use ``.all_rows()`` for multi-column projections and aggregations.
* Use ``.build()`` to inspect, log, or test the generated Cypher.

----

Full-text search
----------------

Full-text search uses a backend-specific ``CALL`` procedure instead of a
``MATCH`` clause.  The entry point is
:meth:`~runic.orm.session.session.Session.fulltext_search`, which returns a
specialised builder that has the same chaining and terminal methods as
:class:`~runic.orm.query.builder.QueryBuilder`.

The backend procedure invoked depends on which driver you are using:

.. list-table::
   :header-rows: 1
   :widths: 20 80

   * - Backend
     - Procedure
   * - FalkorDB
     - ``CALL db.idx.fulltext.queryNodes('Label', $query) YIELD node AS n``
   * - Neo4j
     - ``CALL db.index.fulltext.queryNodes('Label', $query) YIELD node AS n``
   * - Memgraph
     - ``CALL text_search.search_all('label', $query) YIELD node``
   * - ArcadeDB
     - Not supported
   * - Apache AGE
     - Not supported; use PostgreSQL ``tsvector``/``tsquery`` via raw SQL

A fulltext index on the target label must exist before querying.  Create it
declaratively via :class:`~runic.migrate.schema.SchemaManager` or a
migration ``op``:

.. code-block:: python

    class Post(Node, labels=["Post"]):
        title: str = Field(index_type="FULLTEXT")
        body: str = Field(index_type="FULLTEXT")

    posts: list[Post] = (
        session.fulltext_search(Post, query="graph databases")
        .where(Post.published == True)
        .order_by(Post.created_at, desc=True)
        .limit(20)
        .all()
    )

The generated Cypher for FalkorDB:

.. code-block:: none

    CALL db.idx.fulltext.queryNodes('Post', $__fts_query) YIELD node AS n
    WHERE n.published = $p0
    RETURN n
    ORDER BY n.created_at DESC
    LIMIT 20

Additional ``.where()``, ``.order_by()``, and ``.limit()`` clauses are appended
after the ``CALL`` block and apply to the nodes yielded by the procedure.

.. seealso::

   `examples/orm/11_query_builder_search.py <https://github.com/jenreh/runic/blob/main/examples/orm/11_query_builder_search.py>`_
      Full-text and vector search combined with ``where()``, ``order_by()``,
      ``limit()``, index creation via ``IndexManager``, and ``build()`` to
      inspect generated Cypher.

----

Vector KNN search
-----------------

Vector KNN search finds the ``k`` nearest nodes to a query vector, using
approximate nearest-neighbour index procedures.  Like full-text search, the
underlying procedure is backend-specific:

.. list-table::
   :header-rows: 1
   :widths: 20 80

   * - Backend
     - Procedure
   * - FalkorDB
     - ``vecf32(n.field) <-> vecf32($vec)`` inline distance expression
   * - Neo4j
     - ``CALL db.index.vector.queryNodes('label_field', $k, $vec) YIELD node, score``
   * - Memgraph
     - ``CALL vector_search.search('label_field', $k, $vec) YIELD node, distance``
   * - ArcadeDB
     - ``CALL vector.neighbors('Type[field]', $vec, $k) YIELD node, distance``
   * - Apache AGE
     - Not supported; use ``pgvector`` via raw SQL

A vector index on the target field must exist.  Runic's
:class:`~runic.migrate.schema.IndexManager` can create it, or you can
use a migration op.

.. code-block:: python

    class Document(Node, labels=["Document"]):
        id: str = Field(primary_key=True)
        embedding: Vector = Field(index_type="VECTOR")

    similar: list[Document] = (
        session.vector_search(
            Document,
            field=Document.embedding,
            vector=query_embedding,   # list[float]
            k=10,
        )
        .where(Document.active == True)
        .all()
    )

The generated Cypher for FalkorDB:

.. code-block:: none

    MATCH (n:Document)
    WHERE n.active = $p0
    RETURN n, vecf32(n.embedding) <-> vecf32($__knn_vec) AS __score
    ORDER BY __score ASC
    LIMIT 10

Results are ordered by ascending distance (closest first).  You can override
the ordering with ``.order_by()`` after the call — but be aware that this
changes the ``ORDER BY`` clause, which may return non-nearest results.

.. note::

   Vector index creation requires a ``dimension`` parameter not stored in
   ``Field()`` metadata.  Pass it explicitly when calling
   ``IndexManager.create_vector_index()``, or pre-create the index via a
   migration op or direct DDL.

----

Async usage
-----------

:class:`~runic.orm.session.async_session.AsyncSession` returns an
:class:`~runic.orm.query.builder.AsyncQueryBuilder` from ``.query()``.  The
chaining methods (``where``, ``order_by``, ``traverse``, etc.) are identical;
only the terminal methods are ``async`` and must be awaited:

.. code-block:: python

    from runic.orm import select

    stmt = select(User).where(User.active == True).order_by(User.name).limit(50)
    stmt_friends = (
        select(User).alias("u")
        .traverse(User.friends).alias("f")
        .where(User.age > 25, on="f")
    )

    async with AsyncSession(driver) as session:
        users: list[User] = await session.scalars(stmt)
        friends: list[User] = await session.scalars(stmt_friends)

.. note::

   Lazy relationship loading (accessing a ``Relation`` field outside a query)
   is not supported in async context.  Use ``fetch=[...]`` on
   ``session.get()`` or model the relationship as a ``.traverse()`` in the
   query builder instead.

----

Understanding and debugging generated Cypher
--------------------------------------------

The ``.build()`` terminal method returns the query as a ``(cypher, params)``
tuple without executing it.  Use it to:

* Understand what the builder emits before running a query in production.
* Log slow queries with their actual parameter values.
* Write unit tests that assert on generated Cypher rather than on live data.
* Diagnose unexpected results by reading the exact query sent to the database.

.. code-block:: python

    from runic.orm import select

    cypher: str
    params: dict[str, Any]
    cypher, params = (
        select(User).alias("u")
        .where(User.age > 18)
        .traverse(User.friends).alias("f")
        .where(User.active == True, on="f")
        .return_target("f")
        .build()
    )

    print(cypher)
    # MATCH (u:User) WHERE (u.age > $p0)
    # OPTIONAL MATCH (u)-[:FRIENDS]->(f:User)
    # WHERE (f.active = $p1)
    # RETURN f

    print(params)
    # {'p0': 18, 'p1': True}

Parameters are always positional (``$p0``, ``$p1``, …) and listed in the order
they appear in the generated Cypher.

----

When to use raw Cypher
-----------------------

The query builder covers the most common patterns, but some Cypher features are
not yet supported.  For these, use the escape hatches directly:

.. code-block:: python

    # Via Repository — result rows decoded to the repo's type
    results: list[User] = repo.cypher(
        "MATCH (n:User)-[:FRIEND*2]-(m:User) WHERE n.id = $id RETURN m",
        {"id": user_id},
        returns=User,
    )

    # Via Session — raw GraphResult
    result = session.execute(cypher, params)

Use raw Cypher when you need:

* ``UNION`` / ``UNION ALL`` across multiple patterns.
* ``CASE`` expressions in ``RETURN``.
* ``EXISTS { ... }`` subqueries.
* ``CALL { ... }`` subqueries (correlated or uncorrelated).
* Pattern comprehensions (``[(a)-[:T]->(b) | b.prop]``).
* Procedure calls not wrapped by the builder (e.g. graph algorithms).

For everything else, prefer the builder — it handles parameter binding,
alias generation, and result decoding automatically.

----

Cypher feature coverage
------------------------

.. list-table::
   :header-rows: 1
   :widths: 42 14 44

   * - Feature
     - Support
     - How to use
   * - MATCH
     - ✓
     - Root of every ``session.query()`` call
   * - OPTIONAL MATCH
     - ✓
     - Default for ``.traverse()``
   * - WHERE (comparison)
     - ✓
     - ``==``, ``!=``, ``>``, ``>=``, ``<``, ``<=``
   * - WHERE (string)
     - ✓
     - ``.contains()``, ``.startswith()``, ``.endswith()``, ``.matches()``
   * - WHERE (null)
     - ✓
     - ``.is_null()``, ``.is_not_null()``, ``== None``
   * - WHERE (list)
     - ✓
     - ``.in_()``, ``.not_in_()``
   * - WHERE (boolean logic)
     - ✓
     - ``&``, ``|``, ``~``
   * - RETURN
     - ✓
     - Automatic; customised by ``return_target()``, ``project()``
   * - ORDER BY
     - ✓
     - ``.order_by(field, desc=False)``
   * - SKIP / LIMIT
     - ✓
     - ``.skip(n)``, ``.limit(n)``
   * - DISTINCT
     - ✓
     - ``.distinct()``
   * - WITH
     - ✓
     - ``.with_("alias")``
   * - Aggregation (count/avg/sum/…)
     - ✓
     - ``.aggregate(...)`` + helpers from ``runic.orm.query``
   * - Edge property filter
     - ✓
     - ``traverse(edge_alias=)`` + ``where(on=)``
   * - Relationship traversal (1-hop)
     - ✓
     - ``.traverse(Cls.relation)``
   * - Multi-hop traversal
     - ✓
     - Chained ``.traverse()`` calls
   * - Variable-length paths (``*n..m``)
     - ✓
     - ``.repeat(Cls.relation, min_hops=, max_hops=)``
   * - Full-text search (CALL)
     - ✓
     - ``session.fulltext_search()``
   * - Vector KNN
     - ✓
     - ``session.vector_search()``
   * - TypeConverter in WHERE
     - ✓
     - Auto-applied for ``datetime``, ``Enum``, ``Vector``, ``GeoLocation``
   * - UNION / UNION ALL
     - ✗
     - Use ``repo.cypher()``
   * - CASE expressions
     - ✗
     - Use ``repo.cypher()``
   * - EXISTS { subpattern }
     - ✗
     - Use ``repo.cypher()``
   * - CALL { ... } subqueries
     - ✗
     - Use ``repo.cypher()``
   * - Pattern comprehensions
     - ✗
     - Use ``repo.cypher()``
