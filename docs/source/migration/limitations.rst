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

**Why:** Schema introspection APIs return the current state of indexes and
constraints.  There is no rename-event or change-log API in any supported
backend.  Detecting a rename requires comparing two names and inferring intent,
which is inherently ambiguous.

**What to do:** Write rename operations manually using ``op.rename_property``
and ``op.relabel_nodes``.  Do not rely on autogenerate for rename migrations.

Autogenerate covers schema objects only
-----------------------------------------

**What this means:** Autogenerate diffs indexes and constraints.  It does not
compare node labels present in the graph, property names used on existing
nodes, relationship types, or any actual data.

**Why:** Graph databases do not expose a declarative schema for node data.  A
``Person`` node with an ``email`` property can coexist with a ``Person`` node
without one; there is no "schema" to diff against.

**What to do:** Data migrations (seeding reference data, normalising values,
backfilling properties) must be written manually using ``op.run_cypher``,
``op.seed``, ``op.rename_property``, and ``op.relabel_nodes``.

No property-type diffing
--------------------------

**What this means:** Autogenerate detects the presence or absence of an index
but cannot detect that an indexed property changed type (e.g. ``string`` →
``integer``).

**Why:** The schema introspection queries used by runic return only the index
type (``RANGE``, ``FULLTEXT``, ``VECTOR``) and the property name.  No
property-type metadata is available.

**What to do:** If you need to change the type of an indexed property, write a
migration that drops the old index, migrates the data, and recreates the index.

No index-options drift detection
---------------------------------

**What this means:** Autogenerate detects the presence or absence of a vector
index but does not detect changes to its HNSW parameters (``dimension``,
``similarity``, ``m``, ``ef_construction``, ``ef_runtime``).

**Why:** A parameter change always requires a drop + create regardless of
backend — there is no ``ALTER INDEX`` path.  Comparing floating-point options
reliably against live schema data is fragile and would not unlock a simpler
migration path anyway.

**What to do:** Write vector index parameter changes as explicit migrations
using ``op.drop_vector_index`` + ``op.create_vector_index``.

ORM schema validation vs. autogenerate introspection
------------------------------------------------------

These are two separate concerns that use different code paths:

**ORM schema validation** (``IndexManager`` / ``SchemaManager``) uses
``get_existing_specs()`` to read the live schema at startup and diff/sync it
against your model declarations.  This is implemented for:

* **FalkorDB** — via ``CALL db.indexes()`` / ``CALL db.constraints()``
* **Neo4j** — via ``SHOW INDEXES`` / ``SHOW CONSTRAINTS``
* **Memgraph** — via ``SHOW INDEX INFO`` / ``SHOW CONSTRAINT INFO``
  (RANGE indexes and UNIQUE / MANDATORY constraints only — FULLTEXT and VECTOR
  indexes are not exposed by these commands)

ArcadeDB and Apache AGE return an empty set from ``get_existing_specs()``;
every declared spec is treated as missing.

**Migrate autogenerate** (``runic revision --autogenerate`` and
``runic check``) uses ``read_live_schema()`` to generate a diff against your
``SchemaManifest``.  This is implemented **only for FalkorDB**.  All other
adapters return an empty live schema from ``read_live_schema()``.  If you run
``--autogenerate`` against a non-FalkorDB backend, runic sees the entire
manifest as "new" and generates a create-all script — it does not produce a
meaningful diff.

**What to do:** For Neo4j and Memgraph, use ``SchemaManager.validate_schema``
and ``sync_schema`` at startup for live introspection.  Write migration scripts
manually rather than relying on autogenerate.  Autogenerate's *revision
creation* still works as a scaffolding tool — review and trim the generated
creates on first run if your schema already exists.

Version state lives inside the graph
--------------------------------------

**What this means:** The current revision is stored as a node inside the graph
being migrated.  If the graph is deleted, the version pointer is lost.

**Consequences:**

* Deleting and recreating a graph loses version tracking.  Use ``runic stamp``
  to re-attach the version pointer after recreating.
* On FalkorDB, copying a graph via ``GRAPH.COPY`` also copies the version node.
  A copied graph already knows its revision.
* There is no separate version table, file, or external metadata store.

No async client support
-------------------------

**What this means:** All migration adapters use synchronous (blocking) I/O.
runic does not integrate with asyncio or any async graph client.

**Why:** The core ``upgrade``/``downgrade`` loop calls adapter methods
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

No automatic rollback on partial failure
------------------------------------------

**What this means:** If a migration script raises an exception mid-way (e.g.,
after creating one index but before creating a second), the database is left in
a partially applied state.  The version node is not updated (it remains at the
prior revision), but the partial changes are not automatically undone.

**The exception (FalkorDB only):** Revisions with ``snapshot = True`` take a
full graph copy before running.  On failure the snapshot is restored, leaving
the graph in its pre-migration state.  This mechanism is not available on other
backends.

**Why:** DDL operations are not transactional across the adapters runic
supports.  Automatic rollback of arbitrary Cypher is not possible.

**Recommendation:** Use ``snapshot = True`` (FalkorDB) for high-risk migrations
on production data.  On other backends, prefer small, focused revisions that are
easy to reason about if they need to be re-run after a failure.

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
