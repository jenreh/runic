Operations Reference
====================

The ``op`` object passed to every ``upgrade(op)`` and ``downgrade(op)``
function is an instance of :class:`~runic.migrate.operations.GraphOperations`.  It
wraps the FalkorDB client and exposes a safe, preview-aware API for all
supported schema operations.

In preview mode (``runic upgrade --preview``) none of the methods below
touch the database; instead each operation is recorded as a string in
``op.preview_log`` and printed to the console.

----

Range indexes
--------------

Range indexes support equality and range queries on node or relationship
properties (``WHERE n.prop = $x``, ``WHERE n.prop > $x``).

.. py:method:: op.create_range_index(label, prop, *, rel=False)

   Create a range index on ``label.prop``.

   :param label: Node label (or relationship type when ``rel=True``).
   :param prop: Property name.
   :param rel: ``True`` to index a relationship property instead of a node property.

   .. code-block:: python

      def upgrade(op) -> None:
          op.create_range_index("Person", "email")
          op.create_range_index("KNOWS", "since", rel=True)

   The generated Cypher is:

   .. code-block:: cypher

      CREATE INDEX FOR (n:Person) ON (n.email)
      CREATE INDEX FOR ()-[r:KNOWS]->() ON (r.since)

.. py:method:: op.drop_range_index(label, prop, *, rel=False)

   Drop a range index.

   :param label: Node label or relationship type.
   :param prop: Property name.
   :param rel: ``True`` for a relationship index.

   .. code-block:: python

      def downgrade(op) -> None:
          op.drop_range_index("Person", "email")

----

Fulltext indexes
-----------------

Fulltext indexes enable substring and token search via
``CALL db.idx.fulltext.queryNodes()``.

.. py:method:: op.create_fulltext_index(label, *props, language=None, stopwords=None)

   Create a fulltext index on one or more properties of a node label.

   :param label: Node label.
   :param props: One or more property names.
   :param language: Optional language for the text analyzer
       (e.g. ``"english"``, ``"german"``).  Defaults to ``"english"``
       when omitted.
   :param stopwords: Optional list of stopword strings.

   .. code-block:: python

      def upgrade(op) -> None:
          op.create_fulltext_index("Article", "title", "body")
          op.create_fulltext_index(
              "Review",
              "text",
              language="german",
              stopwords=["und", "oder"],
          )

.. py:method:: op.drop_fulltext_index(label, *props)

   Drop a fulltext index.

   :param label: Node label.
   :param props: Property names (one per call internally).

   .. code-block:: python

      def downgrade(op) -> None:
          op.drop_fulltext_index("Article", "title", "body")

----

Vector indexes
--------------

Vector indexes enable approximate nearest-neighbour search (ANN) via HNSW.
Used for semantic similarity queries.

.. py:method:: op.create_vector_index(label, prop, dimension, similarity, *, m=16, ef_construction=200, ef_runtime=10)

   Create a vector index.

   :param label: Node label.
   :param prop: Property name that stores the vector (list of floats).
   :param dimension: Vector dimensionality (e.g. ``1536`` for OpenAI
       ``text-embedding-3-small``).
   :param similarity: Distance function — ``"cosine"`` or ``"euclidean"``.
   :param m: HNSW ``M`` parameter (max neighbours per layer). Default 16.
   :param ef_construction: HNSW ``efConstruction`` (build-time search width).
       Default 200.
   :param ef_runtime: HNSW ``efRuntime`` (query-time search width). Default 10.

   .. code-block:: python

      def upgrade(op) -> None:
          op.create_vector_index(
              "Document",
              "embedding",
              dimension=1536,
              similarity="cosine",
          )

.. py:method:: op.drop_vector_index(label, prop)

   Drop a vector index.

   .. code-block:: python

      def downgrade(op) -> None:
          op.drop_vector_index("Document", "embedding")

----

Constraints
-----------

FalkorDB supports two constraint kinds: ``UNIQUE`` (ensures no two nodes of
the same label share the same property value) and ``MANDATORY`` (ensures the
property is always present).

.. py:method:: op.create_constraint(kind, entity, label, props)

   Create a constraint and poll until it becomes ``OPERATIONAL``.

   :param kind: ``"UNIQUE"`` or ``"MANDATORY"``.
   :param entity: ``"NODE"`` or ``"RELATIONSHIP"``.
   :param label: Node label or relationship type.
   :param props: List of property names.

   .. note::

      For ``UNIQUE`` constraints, runic automatically calls
      ``create_range_index`` on each property before creating the
      constraint.  You do not need to call ``create_range_index`` separately
      in ``upgrade`` for this case.

   .. code-block:: python

      def upgrade(op) -> None:
          op.create_constraint("UNIQUE", "NODE", "Person", ["email"])
          op.create_constraint("MANDATORY", "NODE", "Person", ["name"])

   runic polls ``CALL db.constraints()`` in a loop (30 retries × 0.5 s) and
   raises :class:`~runic.migrate.operations.ConstraintFailedError` if the status
   becomes ``FAILED``, or :class:`~runic.migrate.operations.ConstraintTimeoutError`
   if it does not become ``OPERATIONAL`` within 15 seconds.

.. py:method:: op.drop_constraint(kind, entity, label, props)

   Drop a constraint.

   :param kind: ``"UNIQUE"`` or ``"MANDATORY"``.
   :param entity: ``"NODE"`` or ``"RELATIONSHIP"``.
   :param label: Node label or relationship type.
   :param props: List of property names.

   .. code-block:: python

      def downgrade(op) -> None:
          op.drop_constraint("UNIQUE", "NODE", "Person", ["email"])
          op.drop_range_index("Person", "email")

----

Data transformation
--------------------

These helpers perform batched Cypher queries for common data-level changes.
They are safe to run on large graphs because they operate in configurable
batch sizes.

.. py:method:: op.rename_property(label, old, new, batch=10_000)

   Rename a property on all nodes of a given label.  Runs in a loop until
   no more nodes are affected.

   :param label: Node label.
   :param old: Current property name.
   :param new: New property name.
   :param batch: Number of nodes processed per query. Default 10 000.

   .. code-block:: python

      def upgrade(op) -> None:
          op.rename_property("User", "email_address", "email")

   .. warning::

      Property renames are **not** detected by autogenerate.  You must write
      them manually in both ``upgrade`` and ``downgrade``.

.. py:method:: op.relabel_nodes(old, new, batch=10_000)

   Rename a node label across the entire graph.  Adds the new label and
   removes the old one for each matching node in batches.

   :param old: Current label.
   :param new: New label.
   :param batch: Nodes per batch.

   .. code-block:: python

      def upgrade(op) -> None:
          op.relabel_nodes("User", "Person")

.. py:method:: op.seed(merge_query, rows)

   Insert or merge reference data.  Wraps each row with
   ``UNWIND $rows AS row <merge_query>``.

   :param merge_query: Cypher fragment starting after the ``UNWIND ... AS row``
       clause (e.g. ``"MERGE (c:Country {code: row.code}) SET c.name = row.name"``).
   :param rows: List of parameter dicts, one per row.

   .. code-block:: python

      _COUNTRIES = [
          {"code": "DE", "name": "Germany"},
          {"code": "FR", "name": "France"},
      ]

      def upgrade(op) -> None:
          op.seed(
              "MERGE (c:Country {code: row.code}) SET c.name = row.name",
              _COUNTRIES,
          )

      def downgrade(op) -> None:
          op.run_cypher(
              "MATCH (c:Country) WHERE c.code IN $codes DETACH DELETE c",
              {"codes": [r["code"] for r in _COUNTRIES]},
          )

----

Raw Cypher
----------

For anything not covered by the helpers above:

.. py:method:: op.run_cypher(query, params=None)

   Execute an arbitrary Cypher query against the graph.

   :param query: Cypher string.
   :param params: Optional parameter dict.
   :returns: The raw adapter result object (or ``None`` in preview mode).

   .. code-block:: python

      def upgrade(op) -> None:
          op.run_cypher(
              "MATCH (n:Person) SET n.active = true"
          )
          op.run_cypher(
              "MATCH (n:Person) WHERE n.score < $threshold DELETE n",
              {"threshold": 0},
          )

----

Error classes
-------------

These exceptions are raised by ``op.create_constraint()`` during constraint
polling.  They live in :mod:`runic.migrate.exceptions` and are exported from the
top-level ``runic`` package.

.. autoclass:: runic.migrate.exceptions.ConstraintFailedError
   :no-members:
   :no-index:

.. autoclass:: runic.migrate.exceptions.ConstraintTimeoutError
   :no-members:
   :no-index:
