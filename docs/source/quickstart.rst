Quickstart
==========

This page takes you from a fresh install to a working migration in about
five minutes.

Prerequisites: runic installed (:doc:`installation`) and a FalkorDB instance
reachable at ``falkor://localhost:6379``.

Step 1 — Initialise the migration directory
--------------------------------------------

Run ``runic init`` from your project root.  It creates a small directory
tree that runic uses to store revision scripts and your database connection
config:

.. code-block:: bash

   $ runic init
   Created runic environment at runic/
     runic/env.py
     runic/script.py.mako
     runic/versions/

``runic/`` is the default directory name.  Pass any path to place it
elsewhere:

.. code-block:: bash

   $ runic init migrations

Three files are created:

``env.py``
    Executed by the CLI whenever a live database connection is needed.
    It reads your connection URL from an environment variable and calls
    ``context.configure()``.

``script.py.mako``
    Mako template used by ``runic revision`` to generate new migration
    files.  You rarely need to edit this.

``versions/``
    Empty directory (with a ``.gitkeep``) where generated revision scripts
    are placed.

Step 2 — Configure your connection
------------------------------------

Open ``runic/env.py``.  The generated file reads connection details from
environment variables:

.. code-block:: python

   import os
   from falkordb import FalkorDB
   from runic import context

   FALKORDB_URL = os.getenv("FALKORDB_URL", "falkor://localhost:6379")
   FALKORDB_GRAPH = os.getenv("FALKORDB_GRAPH", "my_graph")

   db = FalkorDB.from_url(FALKORDB_URL)
   graph = db.select_graph(FALKORDB_GRAPH)
   context.configure(connection=db, graph=graph)

Set ``FALKORDB_URL`` and ``FALKORDB_GRAPH`` in your environment (or a
``.env`` file loaded by your shell).

Step 3 — Create your first revision
--------------------------------------

.. code-block:: bash

   $ runic revision -m "add person email index"
   Created revision: runic/versions/3f9a12c1_add_person_email_index.py

Open the generated file.  It contains two empty functions:

.. code-block:: python

   revision = "3f9a12c1"
   down_revision = None          # None = this is the first revision
   branch_labels = []
   depends_on = []
   irreversible = False
   snapshot = False

   def upgrade(op) -> None:
       pass

   def downgrade(op) -> None:
       pass

Edit ``upgrade`` and ``downgrade`` to describe the schema change:

.. code-block:: python

   def upgrade(op) -> None:
       op.create_range_index("Person", "email")

   def downgrade(op) -> None:
       op.drop_range_index("Person", "email")

Step 4 — Preview the migration (optional)
-------------------------------------------

``--preview`` prints the operations that *would* run without touching the
database:

.. code-block:: bash

   $ runic upgrade --preview
   CREATE RANGE INDEX: CREATE INDEX FOR (n:Person) ON (n.email) params=None

Step 5 — Apply the migration
-----------------------------

.. code-block:: bash

   $ runic upgrade
   Upgraded to: head

Step 6 — Check the current revision
--------------------------------------

.. code-block:: bash

   $ runic current
   3f9a12c1 — add person email index

Step 7 — Roll back
-------------------

.. code-block:: bash

   $ runic downgrade base
   Downgraded to: base

   $ runic current
   <none>

Next steps
----------

* :doc:`tutorial/first_migration` — deeper walkthrough of revision anatomy
* :doc:`tutorial/upgrade_downgrade` — relative targets, irreversible flags,
  snapshot-based rollback
* :doc:`operations_reference` — full list of ``op.*`` calls
* :doc:`autogenerate` — generate migration scripts from a schema manifest
