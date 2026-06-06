Query Builder
=============

The runic query builder provides a fluent, type-safe API for constructing
FalkorDB Cypher queries from your ORM model declarations — without writing
raw Cypher strings for the common cases.

Overview
--------

All queries start from :meth:`~runic.orm.session.session.Session.query`,
which returns a :class:`~runic.orm.query.builder.QueryBuilder` bound to the
session::

    from runic.orm import Session, QueryBuilder

    with Session(graph) as session:
        users = (
            session.query(User)
            .where(User.active == True)
            .order_by(User.name)
            .limit(20)
            .all()
        )

The builder generates Cypher and delegates execution / result decoding to the
existing ``Mapper`` and identity-map machinery — so entities returned by the
builder are tracked in the session exactly like entities returned by
``session.get()`` or ``repo.find_all()``.

Entry points
------------

+---------------------------------------------+----------------------------------------------+
| Method                                      | Returns                                      |
+=============================================+==============================================+
| ``session.query(NodeCls)``                  | ``QueryBuilder[NodeCls]``                    |
+---------------------------------------------+----------------------------------------------+
| ``session.fulltext_search(Cls, query=...)`` | ``FulltextQueryBuilder[Cls]``                |
+---------------------------------------------+----------------------------------------------+
| ``session.vector_search(Cls, field=..., …)``| ``VectorQueryBuilder[Cls]``                  |
+---------------------------------------------+----------------------------------------------+
| ``repo.query()``                            | ``QueryBuilder[T]`` (bound to repo's type)   |
+---------------------------------------------+----------------------------------------------+

Filtering
---------

Filters are created by using Python comparison operators on **class-level
field accesses**.  The operator overloads on
:class:`~runic.orm.core.descriptors.FieldDescriptor` return
:class:`~runic.orm.query.expressions.FilterExpr` objects, not Python booleans.

.. code-block:: python

    # Equality / inequality
    User.name == "Alice"          # WHERE n.name = $p0
    User.status != "banned"       # WHERE n.status <> $p0
    User.deleted_at == None       # WHERE n.deleted_at IS NULL  (alias for .is_null())
    User.email != None            # WHERE n.email IS NOT NULL   (alias for .is_not_null())

    # Numeric comparison
    User.age > 18
    User.score >= 4.5
    User.age < 65
    User.credit <= 0

    # String predicates
    User.name.contains("ali")          # WHERE n.name CONTAINS $p0
    User.email.startswith("admin@")    # WHERE n.email STARTS WITH $p0
    User.url.endswith(".org")          # WHERE n.url ENDS WITH $p0
    User.bio.matches(r".*graph.*")     # WHERE n.bio =~ $p0  (regex)

    # Null checks (explicit, more readable than == None)
    User.deleted_at.is_null()          # WHERE n.deleted_at IS NULL
    User.email.is_not_null()           # WHERE n.email IS NOT NULL

    # List membership
    User.role.in_(["admin", "mod"])    # WHERE n.role IN $p0
    Post.tag.not_in_(["spam"])         # WHERE NOT n.tag IN $p0

Boolean composition
~~~~~~~~~~~~~~~~~~~

Use ``&`` (AND), ``|`` (OR), and ``~`` (NOT) to compose predicates::

    # AND
    session.query(User).where((User.age > 18) & (User.active == True))

    # OR
    session.query(User).where((User.role == "admin") | (User.role == "mod"))

    # NOT
    session.query(User).where(~(User.banned == True))

Multiple ``.where()`` calls are always joined by AND::

    session.query(User)
        .where(User.age > 18)
        .where(User.active == True)
    # WHERE (n.age > $p0) AND (n.active = $p1)

Aliases
-------

Give a Cypher variable name to the root node with ``.alias()``::

    session.query(User).alias("u").where(User.name == "Alice", on="u")

The ``on=`` parameter of ``.where()`` overrides which alias a predicate is
applied to.  This is especially useful with traversals (see below) and with
edge property filtering.

Traversals
----------

Single-hop
~~~~~~~~~~

:meth:`~runic.orm.query.builder.QueryBuilder.traverse` follows a
:func:`~runic.orm.core.descriptors.Relation` field declaration.  It returns a
:class:`~runic.orm.query.traversal.TraversalStep`; call ``.alias()`` on the
step to name the target node and resume the builder chain::

    # Default: OPTIONAL MATCH (left-join — keeps users with no friends)
    friends = (
        session.query(User).alias("u")
        .where(User.id == uid)
        .traverse(User.friends).alias("f")
        .where(User.age > 25, on="f")
        .return_target("f")
        .all()
    )

    # Inner join (MATCH) — drops users without a company
    employed = (
        session.query(User).alias("u")
        .traverse(User.works_for, optional=False).alias("c")
        .all()
    )

Multi-hop
~~~~~~~~~

Chain multiple ``.traverse()`` calls::

    posts_by_friends = (
        session.query(User).alias("u")
        .traverse(User.friends).alias("f")
        .traverse(User.authored_posts).alias("p")
        .where(Post.title.contains("graph"), on="p")
        .return_target("p")
        .all()
    )

Variable-length paths
~~~~~~~~~~~~~~~~~~~~~

Use :meth:`~runic.orm.query.builder.QueryBuilder.repeat` to generate
``*min..max`` path quantifiers::

    ancestors = (
        session.query(Employee).alias("e")
        .where(Employee.id == emp_id)
        .repeat(Employee.reports_to, min_hops=1, max_hops=5).alias("anc")
        .all()
    )
    # MATCH (e)-[:REPORTS_TO*1..5]->(anc:Employee)

    # Unbounded (no max)
    all_reachable = (
        session.query(Station)
        .repeat(Station.connected_to, min_hops=1).alias("s2")
        .all()
    )

Edge properties
---------------

By default, relationship patterns are anonymous: ``(a)-[:TYPE]->(b)``.
Pass ``edge_alias=`` to :meth:`~runic.orm.query.builder.QueryBuilder.traverse`
to name the relationship variable, enabling edge property access::

    class Rated(Edge, type="RATED"):
        score: float = Field()

    class User(Node, labels=["User"]):
        rated: list[Movie] = Relation(
            relationship="RATED",
            direction="OUTGOING",
            target="Movie",
            edge_model=Rated,       # link the Edge class
        )

    rows = (
        session.query(User).alias("u")
        .traverse(User.rated, edge_alias="r").alias("m")  # (u)-[r:RATED]->(m)
        .where(Rated.score > 4.0, on="r")
        .return_nodes("u", "m").return_edge("r")
        .all_with_edges()           # list[tuple[User, Rated, Movie]]
    )

    for user, edge, movie in rows:
        print(f"{user.name} rated {movie.title}: {edge.score}")

.. note::
   The existing lazy/eager relationship loading paths (``session.get(..., fetch=[...])``)
   remain unchanged and still use anonymous patterns.  Named relationship
   variables are only emitted by the query builder when ``edge_alias=`` is given.

WITH clause (multi-stage pipelining)
-------------------------------------

Use :meth:`~runic.orm.query.builder.QueryBuilder.with_` to insert a Cypher
``WITH`` clause between query stages::

    (
        session.query(User).alias("u")
        .where(User.active == True)
        .with_("u")                   # WITH u
        .traverse(User.posts).alias("p")
        .return_target("p")
        .all()
    )

Ordering, pagination, DISTINCT
-------------------------------

.. code-block:: python

    session.query(User)
        .order_by(User.age, desc=True)  # ORDER BY n.age DESC
        .skip(20)                        # SKIP 20
        .limit(10)                       # LIMIT 10
        .all()

    session.query(User).distinct().project(User.country).scalars()
    # RETURN DISTINCT n.country

Aggregation
-----------

Import and use the aggregation helpers::

    from runic.orm.query import count, avg, sum_, min_, max_, collect

    # Count all users
    total = session.query(User).aggregate(count().as_("total")).scalar()

    # Average age
    avg_age = session.query(User).aggregate(avg(User.age).as_("avg")).scalar()

    # Friends per user (GROUP BY u)
    rows = (
        session.query(User).alias("u")
        .traverse(User.friends)
        .aggregate(count("*").as_("friends"), group_by="u")
        .all_rows()   # list[dict] → [{"u": <User>, "friends": 5}, ...]
    )

    # Via .count() terminal shortcut
    n = session.query(User).where(User.active == True).count()

Projection (scalar results)
----------------------------

Use :meth:`~runic.orm.query.builder.QueryBuilder.project` to return only
specific field values::

    # Single-field flat list
    names = session.query(User).project(User.name).scalars()

    # Multi-field dicts
    rows = session.query(User).project(User.name, User.age).all_rows()
    # [{"n.name": "Alice", "n.age": 30}, ...]

Terminal methods
----------------

+---------------------+--------------------------------------------------+
| Method              | Returns                                          |
+=====================+==================================================+
| ``.all()``          | ``list[T]`` — decoded Node instances             |
+---------------------+--------------------------------------------------+
| ``.one()``          | ``T | None`` — first result (LIMIT 1)            |
+---------------------+--------------------------------------------------+
| ``.all_with_edges`` | ``list[tuple]`` — (NodeA, Edge, NodeB) tuples    |
+---------------------+--------------------------------------------------+
| ``.all_rows()``     | ``list[dict]`` — column-keyed dicts              |
+---------------------+--------------------------------------------------+
| ``.count()``        | ``int`` — ``count(*)``                           |
+---------------------+--------------------------------------------------+
| ``.scalar()``       | ``Any`` — first column of first row              |
+---------------------+--------------------------------------------------+
| ``.scalars()``      | ``list[Any]`` — first column of every row        |
+---------------------+--------------------------------------------------+
| ``.build()``        | ``(str, dict)`` — raw Cypher + params (debug)    |
+---------------------+--------------------------------------------------+

FalkorDB fulltext search
------------------------

Requires a fulltext index on the node label (created via
:class:`~runic.orm.schema.schema_manager.SchemaManager` or migration ops)::

    class Post(Node, labels=["Post"]):
        title: str = Field(index_type="FULLTEXT")
        body: str = Field(index_type="FULLTEXT")

    posts = (
        session.fulltext_search(Post, query="graph databases")
        .where(Post.published == True)
        .order_by(Post.created_at, desc=True)
        .limit(20)
        .all()
    )

Cypher emitted::

    CALL db.idx.fulltext.queryNodes('Post', $__fts_query) YIELD node AS n
    WHERE n.published = $p0
    RETURN n
    ORDER BY n.created_at DESC
    LIMIT 20

FalkorDB vector KNN search
--------------------------

Requires a vector (HNSW) index on the field::

    class Document(Node, labels=["Document"]):
        id: str = Field(primary_key=True)
        embedding: Vector = Field(index_type="VECTOR")

    similar = (
        session.vector_search(
            Document,
            field=Document.embedding,
            vector=query_embedding,   # list[float]
            k=10,
        )
        .where(Document.active == True)
        .all()
    )

Cypher emitted::

    MATCH (n:Document)
    WHERE n.active = $p0
    RETURN n, vecf32(n.embedding) <-> vecf32($__knn_vec) AS __score
    ORDER BY __score ASC
    LIMIT 10

.. note::
   The exact vector KNN syntax may vary by FalkorDB version.  If the emitted
   pattern does not work, fall back to ``repo.cypher()`` with a hand-written
   query.

Async usage
-----------

:class:`~runic.orm.session.async_session.AsyncSession` returns an
:class:`~runic.orm.query.builder.AsyncQueryBuilder` from ``.query()``.
The intermediate/chaining methods are identical; only the terminal methods are
``async``::

    async with AsyncSession(graph) as session:
        users = await (
            session.query(User)
            .where(User.active == True)
            .order_by(User.name)
            .limit(50)
            .all()
        )

        friends = await (
            session.query(User).alias("u")
            .traverse(User.friends).alias("f")
            .where(User.age > 25, on="f")
            .all()
        )

.. note::
   Lazy relationship loading is not supported in async context.  Use
   ``fetch=[...]`` on ``session.get()`` or call
   :meth:`~runic.orm.query.builder.QueryBuilder.traverse` in the query builder
   instead.

Raw Cypher escape hatch
-----------------------

For Cypher features not covered by the builder (``UNION``, ``CASE``,
``EXISTS { subquery }``, custom procedures), use the existing escape hatch::

    # Via Repository
    results = repo.cypher(
        "MATCH (n:User)-[:FRIEND*2]-(m:User) "
        "WHERE n.id = $id RETURN m",
        {"id": user_id},
        returns=User,
    )

    # Via Session
    result = session.execute(cypher, params)

Cypher features coverage
------------------------

+----------------------------------+---------+-----------------------------+
| Feature                          | Support | Notes                       |
+==================================+=========+=============================+
| MATCH                            | ✓       | root node pattern           |
+----------------------------------+---------+-----------------------------+
| OPTIONAL MATCH                   | ✓       | default for ``.traverse()`` |
+----------------------------------+---------+-----------------------------+
| WHERE (comparison)               | ✓       | ``==``, ``!=``, ``>``, …    |
+----------------------------------+---------+-----------------------------+
| WHERE (string)                   | ✓       | ``.contains()``, etc.       |
+----------------------------------+---------+-----------------------------+
| WHERE (null)                     | ✓       | ``.is_null()``, etc.        |
+----------------------------------+---------+-----------------------------+
| WHERE (list)                     | ✓       | ``.in_()``, ``.not_in_()``  |
+----------------------------------+---------+-----------------------------+
| WHERE (boolean logic)            | ✓       | ``&``, ``|``, ``~``         |
+----------------------------------+---------+-----------------------------+
| RETURN                           | ✓       |                             |
+----------------------------------+---------+-----------------------------+
| ORDER BY                         | ✓       | ``.order_by()``             |
+----------------------------------+---------+-----------------------------+
| SKIP / LIMIT                     | ✓       |                             |
+----------------------------------+---------+-----------------------------+
| DISTINCT                         | ✓       | ``.distinct()``             |
+----------------------------------+---------+-----------------------------+
| WITH                             | ✓       | ``.with_()``                |
+----------------------------------+---------+-----------------------------+
| Aggregation (count/avg/sum/…)    | ✓       | ``.aggregate()``            |
+----------------------------------+---------+-----------------------------+
| Edge property filter             | ✓       | ``edge_alias=`` + ``on=``   |
+----------------------------------+---------+-----------------------------+
| Relationship traversal (1-hop)   | ✓       | ``.traverse()``             |
+----------------------------------+---------+-----------------------------+
| Multi-hop traversal              | ✓       | chained ``.traverse()``     |
+----------------------------------+---------+-----------------------------+
| Variable-length paths ``*n..m``  | ✓       | ``.repeat()``               |
+----------------------------------+---------+-----------------------------+
| Fulltext search (CALL)           | ✓       | ``.fulltext_search()``      |
+----------------------------------+---------+-----------------------------+
| Vector KNN                       | ✓       | ``.vector_search()``        |
+----------------------------------+---------+-----------------------------+
| TypeConverter in WHERE           | ✓       | auto-applied                |
+----------------------------------+---------+-----------------------------+
| UNION                            | ✗       | use ``repo.cypher()``       |
+----------------------------------+---------+-----------------------------+
| CASE expressions                 | ✗       | use ``repo.cypher()``       |
+----------------------------------+---------+-----------------------------+
| EXISTS { subpattern }            | ✗       | use ``repo.cypher()``       |
+----------------------------------+---------+-----------------------------+
| Subqueries ``CALL { ... }``      | ✗       | use ``repo.cypher()``       |
+----------------------------------+---------+-----------------------------+
| Pattern comprehensions           | ✗       | use ``repo.cypher()``       |
+----------------------------------+---------+-----------------------------+

API reference
-------------

.. autoclass:: runic.orm.query.builder.QueryBuilder
   :members:
   :undoc-members:
   :show-inheritance:

.. autoclass:: runic.orm.query.builder.AsyncQueryBuilder
   :members:
   :undoc-members:
   :show-inheritance:

.. autoclass:: runic.orm.query.builder.FulltextQueryBuilder
   :members:
   :undoc-members:
   :show-inheritance:

.. autoclass:: runic.orm.query.builder.VectorQueryBuilder
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: runic.orm.query.expressions
   :members:
   :undoc-members:
   :show-inheritance:

.. autoclass:: runic.orm.query.traversal.TraversalStep
   :members:
   :undoc-members:
   :show-inheritance:
