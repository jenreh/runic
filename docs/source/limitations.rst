Limitations
===========

runic is a focused, deliberately scoped tool.  This page documents what it
does **not** do and the reasoning behind each constraint.

----

Autogenerate cannot detect renames
------------------------------------

**What this means:** If you rename a property (``email_address`` →
``email``) or a node label (``User`` → ``Person``), autogenerate will
generate a **drop** for the old name and a **create** for the new one.
Applying this migration as-is would delete the index on the old property and
create a new index on a non-existent property — the actual data is unchanged.

**Why:** FalkorDB's ``CALL db.indexes()`` and ``CALL db.constraints()`` return
the current names; there is no change-log or rename-event API.  Detecting a
rename requires comparing two names and inferring intent, which is inherently
ambiguous.

**What to do:** Write rename operations manually using ``op.rename_property``
and ``op.relabel_nodes``.  Do not rely on autogenerate for rename migrations.

Autogenerate covers schema objects only
-----------------------------------------

**What this means:** Autogenerate diffs indexes and constraints.  It does not
compare node labels that exist in the graph, property names used on existing
nodes, relationship types, or any actual data.

**Why:** FalkorDB does not expose a declarative schema for node data.  A
``Person`` node with an ``email`` property can coexist with a ``Person`` node
without one; there is no "schema" to diff against.

**What to do:** Data migrations (seeding reference data, normalising values,
backfilling properties) must be written manually using ``op.run_cypher``,
``op.seed``, ``op.rename_property``, and ``op.relabel_nodes``.

No property-type diffing
--------------------------

**What this means:** FalkorDB does not expose property type information via
``CALL db.indexes()``.  Autogenerate cannot tell that a property was
previously indexed as a string and is now being used as an integer.

**Why:** The introspection API returns only the index type (``RANGE``,
``FULLTEXT``, ``VECTOR``) and the property name.  No type metadata is
available.

No index-options drift detection
---------------------------------

**What this means:** Autogenerate detects the presence or absence of a vector
index, but does not detect changes to its HNSW parameters (``dimension``,
``similarity``, ``m``, ``ef_construction``, ``ef_runtime``).

**Why:** Comparing floating-point options reliably against live schema data
is fragile.  FalkorDB does not currently expose ``ALTER INDEX`` semantics, so
a parameter change requires a drop + create anyway.

**What to do:** If you need to change vector index parameters, write a
migration with ``op.drop_vector_index`` + ``op.create_vector_index`` manually.

FalkorDB only
--------------

**What this means:** runic is built specifically for
`FalkorDB <https://falkordb.com>`_ and uses FalkorDB-specific Cypher
extensions, ``GRAPH.CONSTRAINT``, and ``GRAPH.COPY``.  It does not support
Neo4j, Amazon Neptune, AgeDB, or any other graph database.

**Why:** The operations API, constraint polling, snapshot mechanism, and
introspection layer all depend on FalkorDB-specific commands.  Building a
multi-database abstraction would require a complete architectural redesign.

Version state lives inside the graph
--------------------------------------

**What this means:** The current revision is stored as a
``_FalkorMigrateVersion`` node inside the graph being migrated.  If the graph
is deleted, the version pointer is lost.

**Consequences:**

* Deleting and recreating a graph loses version tracking.  Use ``runic stamp``
  to re-attach the version pointer after recreating.
* Copying a graph via ``GRAPH.COPY`` also copies the version node.  A copied
  graph already knows its revision.
* There is no separate version table, file, or external metadata store.

No async client support
-------------------------

**What this means:** runic uses the synchronous ``falkordb`` client (blocking
I/O).  It does not integrate with asyncio or any async FalkorDB client.

**Why:** The core ``upgrade``/``downgrade`` loop calls methods on the graph
synchronously.  Adding async support would require either an
``AsyncGraphOperations`` alternative or running the migration loop in a thread
pool, neither of which is in scope.

**What to do:** Call runic from a subprocess or thread if you need to run
migrations from an async application:

.. code-block:: python

   import subprocess
   result = subprocess.run(["runic", "upgrade"], check=True)

No parallel migration execution
---------------------------------

**What this means:** runic applies revisions one at a time, in topological
order.  There is no mechanism to run independent branches in parallel.

**Why:** Parallel execution introduces ordering hazards (two branches
creating conflicting indexes, for example).  The correctness guarantees of a
topological sort require sequential execution.

No automatic rollback on partial failure (without snapshot)
------------------------------------------------------------

**What this means:** If a migration script raises an exception mid-way (e.g.,
after creating one index but before creating a second), the database is left in
a partially applied state.  The version node is not updated (it remains at the
prior revision), but the partial changes are not automatically undone.

**The exception:** Revisions with ``snapshot = True`` take a full graph copy
before running.  On failure the snapshot is restored, leaving the graph in
its pre-migration state.

**Why:** FalkorDB does not support transactions that span schema changes (DDL
is not transactional).  Automatic rollback of arbitrary Cypher is not
possible.

**Recommendation:** Use ``snapshot = True`` for high-risk migrations on
production data.  For most schema-only changes (adding an index), partial
failure is recoverable by re-running the migration after fixing the script.

No ``--autogenerate`` without ``target_manifest``
--------------------------------------------------

**What this means:** ``runic revision --autogenerate`` and ``runic check``
both require ``target_manifest`` to be set in ``env.py`` via
``context.configure(..., target_manifest=...)``.  Without it they exit with
an error.

No ``runic.ini`` or TOML configuration file
--------------------------------------------

**What this means:** runic has no ``.ini``, ``pyproject.toml`` section, or
YAML config file.  All configuration happens in ``env.py`` (a Python script).

**Why:** The pure-Python config keeps secrets out of committed config files
and removes a second config surface.  Environment variables loaded by the
application's own config system (dotenv, Pydantic Settings, etc.) are
accessible from ``env.py`` without any runic-specific glue.

No built-in online migration / zero-downtime helpers
------------------------------------------------------

**What this means:** runic does not provide primitives for online schema
changes that must be applied in multiple steps to avoid locking (e.g.,
backfill-then-index patterns for large graphs under live traffic).

**What to do:** Model multi-step migrations as multiple sequential revisions.
Use ``op.run_cypher`` with ``LIMIT $batch`` (as ``op.rename_property`` does)
for large data changes that must proceed incrementally.
