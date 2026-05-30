Testing Migrations
==================

runic ships two distinct testing mechanisms:

* **``runic test`` CLI command** — round-trip tests a single revision against
  a real graph.
* **``runic.testing`` pytest fixtures** — utilities for writing unit and
  integration tests for migration scripts in your own test suite.

----

Round-trip testing with ``runic test``
----------------------------------------

``runic test <rev>`` runs a three-phase idempotency check on an ephemeral
graph:

* **Phase A** — upgrade to the target revision.
* **Phase B** — downgrade to ``base``.
* **Phase C** — upgrade again (idempotency check).

At each phase, runic reports the count of nodes, indexes, and constraints:

.. code-block:: bash

   $ runic test 3f9a12c1
   runic test 3f9a12c1ab4e
   ─────────────────────────────────────────────
   Phase A (upgrade):    ✓  nodes=0  indices=1  constraints=1
   Phase B (downgrade):  ✓  nodes=0  indices=0  constraints=0
   Phase C (idempotency):✓  nodes=0  indices=1  constraints=1
   ─────────────────────────────────────────────
   PASSED

The command creates a temporary graph named
``<source_graph>__test_<rev>_<token>``, runs all three phases, then deletes
the graph — regardless of pass or fail.  Your production graph is never
touched.

Running against an embedded server
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

You can point ``runic test`` at a separate URL to avoid needing a production
connection:

.. code-block:: bash

   $ runic test 3f9a12c1 --url falkor://localhost:6379 --graph test_graph

Or use ``falkordblite`` for an embedded server (no Docker required).  Configure
``env.py`` to use the embedded adapter:

.. code-block:: python

   # runic/env.py  (falkordblite variant)
   from pathlib import Path
   from redislite import FalkorDB
   from runic import context
   from runic.adapters.falkordb import FalkorDBAdapter

   db = FalkorDB(protocol=2)
   graph = db.select_graph("test")
   adapter = FalkorDBAdapter(db, graph)
   context.configure(adapter, script_location=Path("runic"))

Then run ``runic test 3f9a12c1`` without any ``--url`` flag.

pytest fixtures
----------------

``runic.testing`` exports two pytest fixtures for use in your own test suite.
Add to your ``conftest.py``:

.. code-block:: python

   from runic.testing import falkordb_graph, runic_context  # noqa: F401

Or import directly in test files:

.. code-block:: python

   import pytest
   from runic.testing import falkordb_graph, runic_context

The fixtures use ``falkordblite`` (installed as ``redislite``) for an
embedded FalkorDB server that starts and stops with the test process.

.. note::

   Both fixtures skip the test automatically if ``falkordblite`` is not
   installed.  Install it with ``uv add --dev falkordblite``.

``falkordb_graph`` fixture
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Yields a ``(db, graph)`` tuple backed by an ephemeral embedded graph.  The
graph is deleted after the test.

.. code-block:: python

   def test_index_creation(falkordb_graph) -> None:
       db, graph = falkordb_graph
       graph.query("CREATE INDEX FOR (n:User) ON (n.id)")
       result = graph.ro_query("CALL db.indexes() YIELD label")
       assert result.result_set

``runic_context`` fixture
~~~~~~~~~~~~~~~~~~~~~~~~~~

Yields a fully configured :class:`~runic.context.Runic` instance backed by
an ephemeral embedded graph and a temporary ``versions/`` directory.  Use this
to test upgrade/downgrade logic end-to-end.

.. code-block:: python

   from pathlib import Path
   from runic.context import Runic
   from runic.testing import runic_context

   def test_full_migration(runic_context, tmp_path) -> None:
       ctx = runic_context
       versions = ctx.script_location / "versions"

       # Write a migration script programmatically
       (versions / "0001_test_index.py").write_text("""
   from datetime import UTC, datetime
   revision = "0001"
   down_revision = None
   branch_labels = []
   depends_on = []
   irreversible = False
   snapshot = False
   message = "test"
   create_date = datetime.now(UTC)

   def upgrade(op) -> None:
       op.create_range_index("Person", "email")

   def downgrade(op) -> None:
       op.drop_range_index("Person", "email")
   """)

       # Create a fresh Runic instance to pick up the new revision file
       ctx2 = Runic(ctx.adapter, ctx.script_location)

       ctx2.upgrade("head")
       assert ctx2.current() == "0001"

       ctx2.downgrade("base")
       assert ctx2.current() is None

Writing testable migration scripts
------------------------------------

Keep migration scripts testable by avoiding side effects outside ``upgrade``
and ``downgrade``:

* Do not query the database at module import time.
* Keep all state in ``op.*`` calls or local variables.
* For seed data, prefer deterministic ``op.seed(...)`` calls over
  ``op.run_cypher`` with hard-coded values.

Use the ``runic test`` command as a first-pass sanity check before committing,
and write focused pytest tests for scripts that involve complex data
transformations.

Integration test markers
-------------------------

If you add the ``integration`` pytest marker to tests that require
``falkordblite``, you can skip them in environments without it:

.. code-block:: python

   @pytest.mark.integration
   def test_migration_round_trip(runic_context) -> None:
       ...

.. code-block:: bash

   # Run only unit tests (skip integration)
   pytest -m "not integration"

   # Run all including integration
   pytest
