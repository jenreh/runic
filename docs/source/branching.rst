Branching and Merging
=====================

runic supports a branched revision DAG, similar to Alembic.  Branches allow
separate lines of development to evolve independently and be merged before
deployment.

----

When branches appear
--------------------

A branch is created whenever two revisions share the same ``down_revision``:

.. code-block:: text

                  ┌── c1d2e3f4 (add vector index)
   3f9a12c1 ──────┤
                  └── 7b3d9e2f (add fulltext index)

This happens when:

* Two developers create new revisions at the same time from the same head.
* You explicitly create a revision off an older revision using
  ``--head <older-rev-id>``.

Detecting multiple heads
-------------------------

``runic heads`` lists all head revisions:

.. code-block:: bash

   $ runic heads
   c1d2e3f4  add vector index    (MULTIPLE HEADS — use merge to resolve)
   7b3d9e2f  add fulltext index  (MULTIPLE HEADS — use merge to resolve)

While multiple heads exist, ``runic upgrade`` (without an explicit target)
will raise an error.  Specify an explicit revision to apply one branch at a
time, or create a merge revision to converge the two lines.

Creating a revision on a specific branch
-----------------------------------------

Use ``--head <rev-id>`` with ``runic revision`` to create a new revision
that extends a specific existing revision rather than the current head:

.. code-block:: bash

   # Current head: 7b3d9e2f
   # Create a revision branching off 3f9a12c1 instead:
   $ runic revision -m "add vector index" --head 3f9a12c1
   Created revision: runic/versions/c1d2e3f4_add_vector_index.py

The new revision file will contain:

.. code-block:: python

   revision = "c1d2e3f4"
   down_revision = "3f9a12c1"

Branch labels
-------------

Assign a symbolic name to a branch with ``--branch-label``:

.. code-block:: bash

   $ runic revision -m "start feature-x" --branch-label feature-x
   Created revision: runic/versions/a1b2c3d4_start_feature_x.py

Branch labels can be used as targets in ``upgrade`` and ``downgrade``:

.. code-block:: bash

   $ runic upgrade feature-x     # upgrade to the head of branch feature-x

``runic branches`` lists all branch points:

.. code-block:: bash

   $ runic branches
   3f9a12c1  add person email index  ['7b3d9e2f', 'c1d2e3f4']

Merging branches
-----------------

Use ``runic merge`` to create a merge revision that declares two heads as its
``down_revision`` tuple:

.. code-block:: bash

   $ runic merge 7b3d9e2f c1d2e3f4 -m "merge fulltext and vector indexes"
   Created revision: runic/versions/fa2b3c4d_merge_fulltext_and_vector_indexes.py

The generated file:

.. code-block:: python

   revision = "fa2b3c4d"
   down_revision = ("7b3d9e2f", "c1d2e3f4")
   branch_labels = []
   depends_on = []
   irreversible = False
   snapshot = False

   def upgrade(op) -> None:
       pass   # merge revisions usually have no operations

   def downgrade(op) -> None:
       pass

After the merge revision there is a single head again:

.. code-block:: text

   3f9a12c1 ──┬── 7b3d9e2f ──┐
              └── c1d2e3f4 ──┴── fa2b3c4d  (head)

Applying across a merge
------------------------

When upgrading from a state before the branch point, runic uses a
topological sort (Kahn's BFS) to produce a valid application order.  Both
branch legs are applied in dependency order before the merge revision:

.. code-block:: bash

   $ runic upgrade
   # Applies: 7b3d9e2f, then c1d2e3f4, then fa2b3c4d

The exact order of the two branch legs (``7b3d9e2f`` vs ``c1d2e3f4``) is
determined by BFS from the merge node, but both are guaranteed to run before
``fa2b3c4d``.

Cross-branch dependencies
--------------------------

If a revision depends on another revision in a *different* branch (without a
shared ancestor), use ``depends_on`` in the revision metadata or
``--depends-on`` on the CLI:

.. code-block:: python

   revision = "b5c6d7e8"
   down_revision = "7b3d9e2f"
   depends_on = ["c1d2e3f4"]   # must also be applied before this runs

.. code-block:: bash

   $ runic revision -m "combined feature" --depends-on c1d2e3f4

runic's topological sort respects ``depends_on`` edges in addition to
``down_revision`` edges.

Resolving accidental branches
-------------------------------

When two developers push revisions from the same head simultaneously, the
result is an accidental branch.  The standard fix is:

1. Both developers push their revision files.
2. One developer runs ``runic merge`` against the two new heads.
3. The merge revision is committed alongside the two branch revisions.
4. The pipeline runs ``runic upgrade`` and all three revisions are applied.

See also
--------

* :doc:`tutorial/history` — inspecting heads and branch points
* :doc:`cli_reference` — ``merge``, ``heads``, ``branches`` command details
