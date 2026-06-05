Upgrading and Downgrading
=========================

This tutorial covers how to apply and revert migrations, use relative targets,
preview changes before executing them, and understand how the version node is
managed.

How runic tracks state
-----------------------

runic stores the current revision inside your graph as a special node of
label ``_FalkorMigrateVersion``.  The node holds a ``revisions`` list
property (and a legacy ``revision`` string for single-head deployments).
No external file or table is involved — the version travels with the graph.

This means:

* **Delete the graph → lose the version pointer.**  Stamp the new graph with
  ``runic stamp`` before running migrations on it.
* **Copy the graph → copy the version pointer.**  A copied graph already
  knows which revision it is at.

Basic upgrade
--------------

Apply all pending revisions up to ``head``:

.. code-block:: bash

   $ runic upgrade
   Upgraded to: head

Apply up to a specific revision (by full ID or unique prefix):

.. code-block:: bash

   $ runic upgrade 3f9a12c1

Relative targets
-----------------

Use ``+N`` to advance exactly *N* revisions from the current position:

.. code-block:: bash

   $ runic upgrade +1   # apply the next revision only
   $ runic upgrade +3   # apply the next three revisions

``+N`` is not available when there are multiple heads (use an explicit ID
instead).

Basic downgrade
----------------

Revert to a specific revision:

.. code-block:: bash

   $ runic downgrade 3f9a12c1

Revert all the way to the initial state (no revisions applied):

.. code-block:: bash

   $ runic downgrade base

Use ``-N`` to step back exactly *N* revisions:

.. code-block:: bash

   $ runic downgrade -1   # undo the most recent revision
   $ runic downgrade -2   # undo the last two revisions

Irreversible revisions
-----------------------

If a revision sets ``irreversible = True``, runic raises
:class:`~runic.migrate.context.IrreversibleMigrationError` when downgrade encounters
it:

.. code-block:: bash

   $ runic downgrade base
   Error: revision 'e1a2b3c4' is marked irreversible; use --force to override

Use ``--force`` to skip the guard (data loss may result):

.. code-block:: bash

   $ runic downgrade base --force

Preview mode
------------

``--preview`` prints every operation that *would* be executed without actually
touching the database.  The version node is not stamped.

.. code-block:: bash

   $ runic upgrade --preview
   CREATE RANGE INDEX: CREATE INDEX FOR (n:Person) ON (n.email) params=None
   CREATE CONSTRAINT: UNIQUE NODE Person ['email']

   $ runic current
   <none>   # version node unchanged

Preview mode is useful in CI pipelines to document what a deployment will do
before it runs.

Snapshot-based rollback
------------------------

Revisions with ``snapshot = True`` trigger a ``GRAPH.COPY`` *before* the
upgrade runs.  If the upgrade raises an exception the snapshot is automatically
restored:

.. code-block:: text

   runic upgrade  →  snapshot mygraph → mygraph__premig_<rev>
                  →  run upgrade(op)
                  →  if exception: restore snapshot
                  →  delete ephemeral snapshot graph

The snapshot graph name follows the pattern
``<graph_name>__premig_<revision_id>``.  Snapshots are created and deleted
automatically; you do not manage them directly.

The ``stamp`` command
----------------------

``stamp`` sets the version pointer *without* running any migration code.  This
is useful when you have applied migrations by hand or are adopting runic on an
existing graph:

.. code-block:: bash

   # Mark the graph as already at revision 3f9a12c1
   $ runic stamp 3f9a12c1
   Stamped: 3f9a12c1

   # Reset version to "no revision applied"
   $ runic stamp base
   Stamped: <none>

   # Stamp all current heads at once (for multi-head graphs after a merge)
   $ runic stamp heads

Use ``--purge`` to clear the existing version node before stamping:

.. code-block:: bash

   $ runic stamp 3f9a12c1 --purge

Adopting runic on an existing graph
--------------------------------------

If you already have a FalkorDB graph with indexes and constraints created by
hand:

1. Write revision scripts that recreate the current state from scratch.
2. Apply them to an empty graph to verify correctness.
3. On the existing production graph, run ``runic stamp <head-revision>`` to
   mark it as already up-to-date **without** re-applying the schema (which
   would fail since the objects already exist).

See also
--------

* :doc:`history` — inspecting the revision chain
* :doc:`../operations_reference` — ``op.*`` reference
* :doc:`../testing` — round-trip testing revisions
