Inspecting History
==================

runic provides several commands for inspecting the revision DAG without
modifying the database.

``runic history``
-----------------

Print all revisions, newest first:

.. code-block:: bash

   $ runic history
   7b3d9e2f         (head)                add email fulltext index
   3f9a12c1                               add person email index

Show verbose metadata for each revision with ``--verbose``:

.. code-block:: bash

   $ runic history --verbose
   7b3d9e2f         (head)                add email fulltext index
       create_date:   2026-05-30 10:00:00+00:00
       down_revision: 3f9a12c1ab4e

   3f9a12c1                               add person email index
       create_date:   2026-05-30 09:00:00+00:00
       down_revision: None

Mark the currently applied revision in the output with ``--indicate-current``
(requires a database connection):

.. code-block:: bash

   $ runic history --indicate-current
   7b3d9e2f         (head, current)       add email fulltext index
   3f9a12c1                               add person email index

Show only a subset of the chain with ``--range start:end``:

.. code-block:: bash

   $ runic history --range 3f9a12c1:7b3d9e2f
   7b3d9e2f         (head)                add email fulltext index
   3f9a12c1                               add person email index

Either side of the range may be omitted: ``--range :7b3d9e2f`` means "from
the base up to that revision", and ``--range 3f9a12c1:`` means "from that
revision to head".

``runic show``
--------------

Print full metadata for a single revision by ID or unique prefix:

.. code-block:: bash

   $ runic show 3f9a12c1
   Revision ID:   3f9a12c1ab4e
   Revises:       <base>
   Message:       add person email index
   Create Date:   2026-05-30 09:00:00+00:00
   Irreversible:  False
   Snapshot:      False
   Branch Labels: []
   Depends On:    []
   Path:          runic/versions/3f9a12c1ab4e_add_person_email_index.py

``runic current``
-----------------

Print the currently applied revision (requires a database connection):

.. code-block:: bash

   $ runic current
   7b3d9e2f — add email fulltext index

   # When no revision has been applied:
   $ runic current
   <none>

``runic heads``
---------------

Print all head revisions — revisions that no other revision points back to:

.. code-block:: bash

   # Single head (normal state):
   $ runic heads
   7b3d9e2f  add email fulltext index  (single head)

   # Multiple heads (after a branch is created):
   $ runic heads
   c1d2e3f4  add vector index          (MULTIPLE HEADS — use merge to resolve)
   7b3d9e2f  add email fulltext index  (MULTIPLE HEADS — use merge to resolve)

When there are multiple heads, ``runic upgrade head`` and ``runic upgrade``
(without a target) will refuse to run.  Use ``runic merge`` to create a merge
revision, or specify an explicit revision ID.

``runic branches``
------------------

Print every revision that is a *branch point* — a revision that two or more
other revisions build upon:

.. code-block:: bash

   $ runic branches
   3f9a12c1  add person email index  ['7b3d9e2f', 'c1d2e3f4']

The last column lists the direct child revision IDs.

See also
---------

* :doc:`../branching` — working with branches and merge revisions
* :doc:`../cli_reference` — complete flag reference for all commands
