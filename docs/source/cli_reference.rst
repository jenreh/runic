CLI Reference
=============

The runic CLI is installed as the ``runic`` command.  Every command accepts
``--config <path>`` (default: ``runic/env.py``) to override the location of
``env.py``.

**Config auto-resolution** — if the default ``runic/env.py`` does not exist,
runic checks for a ``.runic`` marker file in the current directory and resolves
the path from it.  ``runic init <custom-dir>`` writes this file automatically.

Commands that do **not** require a database connection
(``init``, ``revision``, ``history``, ``heads``, ``branches``, ``show``,
``merge``, ``info --mode LOCAL``)
read the script directory from ``--config``'s parent directory and never
execute ``env.py``.

Commands that **do** require a connection
(``upgrade``, ``downgrade``, ``current``, ``stamp``, ``test``,
``check``, ``validate``, ``run``, ``info``)
execute ``env.py`` which calls ``context.configure()``.

----

init
----

.. code-block:: bash

   runic init [DIRECTORY] [--force]

Scaffold a new runic migration environment.

**Arguments**

``DIRECTORY``
    Directory to create (default: ``runic``).

**Options**

``--force``
    Overwrite the directory if it already exists.

**Creates**

* ``<DIRECTORY>/env.py`` — connection script template
* ``<DIRECTORY>/script.py.mako`` — migration file template
* ``<DIRECTORY>/versions/`` — empty directory for revision scripts
* ``.runic`` — config pointer (written only when DIRECTORY is not the default
  ``runic``; commit this file so the rest of the team can omit ``--config``)

**Example**

.. code-block:: bash

   $ runic init
   Created runic environment at runic/
     runic/env.py
     runic/script.py.mako
     runic/versions/

   $ runic init migrations
   Created runic environment at migrations/
     migrations/env.py
     migrations/script.py.mako
     migrations/versions/
     .runic  (config pointer — commit this file)

   $ runic init migrations --force   # overwrite existing directory

----

revision
--------

.. code-block:: bash

   runic revision -m MESSAGE [OPTIONS]

Create a new migration revision script.

**Required options**

``-m``, ``--message TEXT``
    Short description used in the filename and docstring.

**Options**

``--config PATH``
    Path to ``env.py`` (default: ``runic/env.py``).

``--head TEXT``
    Explicitly set ``down_revision`` to this revision ID instead of the
    current head.

``--rev-id TEXT``
    Use a specific revision ID instead of a random hex string.

``--branch-label TEXT``
    Assign a branch label to this revision (stored in ``branch_labels``).

``--depends-on TEXT``
    Add a cross-branch dependency (may be repeated).

``--autogenerate``
    Diff the live schema against ``target_manifest`` set in ``env.py`` and
    fill in ``upgrade``/``downgrade`` bodies automatically.  Requires a
    database connection and ``target_manifest`` to be set.  See
    :doc:`autogenerate`.

``--preview``
    Print the revision file content that *would* be created without writing
    it to disk.  Useful for reviewing the generated script before committing.

    .. code-block:: bash

       $ runic revision --preview -m "add order index"
       # Would create: a1b2c3d4
       """add order index
       ...
       """
       ...

``--format``
    Run ``ruff format`` on the generated file after creation (requires ruff
    on ``PATH``).

**Example**

.. code-block:: bash

   $ runic revision -m "add person email index"
   Created revision: runic/versions/3f9a12c1_add_person_email_index.py

   $ runic revision -m "new feature index" --branch-label feature-x
   Created revision: runic/versions/a1b2c3d4_new_feature_index.py

----

upgrade
-------

.. code-block:: bash

   runic upgrade [TARGET] [--config PATH] [--preview]
                 [--validate-on-migrate] [--installed-by TEXT]

Apply migrations up to ``TARGET`` (default: ``head``).

**Arguments**

``TARGET``
    Revision ID, unique prefix, ``head`` (default), or relative ``+N``.

**Options**

``--config PATH``
    Path to ``env.py``.

``--preview``
    Print operations without executing them.  Version node is not updated.

``--validate-on-migrate``
    Before applying any pending revisions, verify that the checksums of all
    already-applied scripts still match their stored values.  Aborts if any
    mismatch is found.  Requires ``track_checksums=True`` in ``env.py``
    (the default).

``--installed-by TEXT``
    Override the user/system recorded as having applied this upgrade.
    If omitted, the value is resolved from the ``RUNIC_INSTALLED_BY``
    environment variable, then falls back to the OS username.
    Has no effect when ``track_installed_by=False`` in ``env.py``.

**Examples**

.. code-block:: bash

   $ runic upgrade               # apply all pending revisions
   Upgraded to: head

   $ runic upgrade 3f9a12c1      # apply up to a specific revision
   Upgraded to: 3f9a12c1

   $ runic upgrade +1            # apply the next revision only
   Upgraded to: 7b3d9e2f

   $ runic upgrade --preview
   CREATE RANGE INDEX: CREATE INDEX FOR (n:Person) ON (n.email) params=None

   $ runic upgrade --validate-on-migrate --installed-by "ci-bot"
   Upgraded to: head

----

downgrade
---------

.. code-block:: bash

   runic downgrade TARGET [--config PATH] [--force] [--preview]

Revert migrations to ``TARGET``.

**Arguments**

``TARGET``
    Required.  Revision ID, unique prefix, ``base``, or relative ``-N``.

**Options**

``--config PATH``
    Path to ``env.py``.

``--force``
    Cross ``irreversible = True`` markers.

``--preview``
    Print operations without executing them.

**Examples**

.. code-block:: bash

   $ runic downgrade base             # revert all
   Downgraded to: base

   $ runic downgrade 3f9a12c1         # revert to a specific revision
   Downgraded to: 3f9a12c1

   $ runic downgrade -1               # undo the most recent revision
   Downgraded to: 3f9a12c1

   $ runic downgrade base --force     # force past irreversible markers

----

current
-------

.. code-block:: bash

   runic current [--config PATH]

Print the currently applied revision ID and message.

**Options**

``--config PATH``
    Path to ``env.py``.

**Output**

.. code-block:: bash

   $ runic current
   7b3d9e2f — add email fulltext index

   $ runic current
   <none>   # no revision applied

----

history
-------

.. code-block:: bash

   runic history [--config PATH] [--verbose] [--indicate-current] [--range START:END]

Print all revisions, newest first.  Does not require a database connection
unless ``--indicate-current`` is used.

**Options**

``--config PATH``
    Path to ``env.py`` (used as script location source; db only needed with
    ``--indicate-current``).

``--verbose``
    Include ``create_date`` and ``down_revision`` for each entry.

``--indicate-current``
    Mark the currently applied revision as ``current`` in the output.
    Requires a database connection.

``--range START:END``
    Restrict output to an inclusive revision range.  Either side may be
    omitted (``--range :7b3d9e2f`` = from base to that revision;
    ``--range 3f9a12c1:`` = from that revision to head).

**Example**

.. code-block:: bash

   $ runic history --verbose --indicate-current
   7b3d9e2f         (head, current)       add email fulltext index
       create_date:   2026-05-30 10:00:00+00:00
       down_revision: 3f9a12c1ab4e

   3f9a12c1                               add person email index
       create_date:   2026-05-30 09:00:00+00:00
       down_revision: None

----

heads
-----

.. code-block:: bash

   runic heads [--config PATH]

Print all head revisions (revisions not referenced as ``down_revision`` by
any other revision).

**Example**

.. code-block:: bash

   $ runic heads
   7b3d9e2f  add email fulltext index  (single head)

When multiple heads exist (a branch was created):

.. code-block:: bash

   $ runic heads
   c1d2e3f4  add vector index  (MULTIPLE HEADS — use merge to resolve)
   7b3d9e2f  add email index   (MULTIPLE HEADS — use merge to resolve)

----

branches
--------

.. code-block:: bash

   runic branches [--config PATH]

Print every branch-point revision — revisions that two or more other
revisions declare as their ``down_revision``.

**Example**

.. code-block:: bash

   $ runic branches
   3f9a12c1  add person email index  ['7b3d9e2f', 'c1d2e3f4']

----

stamp
-----

.. code-block:: bash

   runic stamp TARGET [--config PATH] [--purge]

Set the version pointer without running any migration code.

**Arguments**

``TARGET``
    Revision ID, ``base`` (clear the pointer), or ``heads`` (stamp all
    current heads at once).

**Options**

``--config PATH``
    Path to ``env.py``.

``--purge``
    Clear the existing version node before stamping.

**Examples**

.. code-block:: bash

   $ runic stamp 3f9a12c1
   Stamped: 3f9a12c1

   $ runic stamp base
   Stamped: <none>

   $ runic stamp heads   # after a merge, stamp both heads
   Stamped: heads

----

show
----

.. code-block:: bash

   runic show REV [--config PATH]

Print full metadata for a single revision.

**Arguments**

``REV``
    Revision ID or unique prefix.

**Example**

.. code-block:: bash

   $ runic show 3f9
   Revision ID:   3f9a12c1ab4e
   Revises:       <base>
   Message:       add person email index
   Create Date:   2026-05-30 09:00:00+00:00
   Irreversible:  False
   Snapshot:      False
   Branch Labels: []
   Depends On:    []
   Path:          runic/versions/3f9a12c1ab4e_add_person_email_index.py

----

test
----

.. code-block:: bash

   runic test REV [--config PATH] [--url URL] [--graph GRAPH]

Round-trip test a revision: ``upgrade → downgrade → upgrade`` on an
ephemeral copy of the graph, then report node/index/constraint counts at
each phase.

**Arguments**

``REV``
    Revision ID or unique prefix to test.

**Options**

``--config PATH``
    Path to ``env.py``.  Used to obtain the database connection when
    ``--url`` is not given.

``--url TEXT``
    FalkorDB URL (e.g. ``falkor://localhost:6379``).  Takes precedence over
    ``env.py``.

``--graph TEXT``
    Graph name when using ``--url`` (default: ``test``).

**Output**

.. code-block:: bash

   $ runic test 3f9a12c1
   runic test 3f9a12c1ab4e
   ─────────────────────────────────────────────
   Phase A (upgrade):    ✓  nodes=0  indices=1  constraints=1
   Phase B (downgrade):  ✓  nodes=0  indices=0  constraints=0
   Phase C (idempotency):✓  nodes=0  indices=1  constraints=1
   ─────────────────────────────────────────────
   PASSED

The test runs on a throw-away graph named
``<graph_name>__test_<rev_id>_<token>`` which is deleted regardless of
whether the test passes or fails.

----

merge
-----

.. code-block:: bash

   runic merge R1 R2 -m MESSAGE [--config PATH] [--branch-label LABEL]

Create a merge revision combining two branch heads.  See :doc:`branching`.

**Arguments**

``R1``, ``R2``
    Revision IDs or unique prefixes of the two heads to merge.

**Required options**

``-m``, ``--message TEXT``
    Description for the merge revision.

**Options**

``--config PATH``
    Path to ``env.py``.

``--branch-label TEXT``
    Branch label for the resulting merge revision.

**Example**

.. code-block:: bash

   $ runic merge 7b3d9e2f c1d2e3f4 -m "merge feature-x into main"
   Created revision: runic/versions/fa2b3c4d_merge_feature_x_into_main.py

----

validate
--------

.. code-block:: bash

   runic validate [--config PATH]

Verify that the local files for all applied revisions still match the
checksums recorded at apply-time.  Exits 0 when all checksums are valid;
exits 1 and lists mismatches otherwise.

Requires ``track_checksums=True`` in ``env.py`` (the default).  Revisions
applied before checksum tracking was introduced are silently skipped.

**Options**

``--config PATH``
    Path to ``env.py``.

**Output**

.. code-block:: bash

   # All good:
   $ runic validate
   All checksums valid.

   # A script was modified after being applied:
   $ runic validate
     x 3f9a12c1ab4e (add person email index): checksum mismatch — script was modified after being applied
   $ echo $?
   1

----

run
---

.. code-block:: bash

   runic run SCRIPT [SCRIPT ...] [--config PATH]

Execute one or more Python migration scripts against the database **without**
recording them in the migration chain.  Useful for one-off operational tasks
(data patches, manual seed loads) where you explicitly do not want a revision
record.

Each ``SCRIPT`` must be a ``.py`` file that defines an ``upgrade(op)``
function.  The function receives the same :class:`~runic.operations.GraphOperations`
object as a normal migration.

**Arguments**

``SCRIPT``
    One or more ``.py`` files.

**Options**

``--config PATH``
    Path to ``env.py``.

**Example**

.. code-block:: bash

   $ runic run patches/backfill_user_roles.py
   Executed: backfill_user_roles.py

   $ runic run patch_a.py patch_b.py
   Executed: patch_a.py
   Executed: patch_b.py

----

info
----

.. code-block:: bash

   runic info [--config PATH] [--mode MODE]

Show migration status.  Three modes are available:

``COMPARE`` (default)
    Compare the live database state against local revision files.  Shows the
    current revision, how many revisions are applied vs total, and lists any
    pending migrations.  Requires a database connection.

``LOCAL``
    Count local revision files and list heads.  Does **not** require a database
    connection — safe for offline or CI use.

``REMOTE``
    Show only what the database knows (the currently applied revision ID).
    Requires a database connection.

**Options**

``--config PATH``
    Path to ``env.py``.

``--mode TEXT``
    ``COMPARE`` | ``LOCAL`` | ``REMOTE`` (default: ``COMPARE``).

**Examples**

.. code-block:: bash

   # Default COMPARE view:
   $ runic info
   Database : my_graph
   Current  : 7b3d9e2f  add email fulltext index
   Applied  : 2 of 3
   Pending  : 1

   Pending migrations:
     c1d2e3f4  add vector index

   # Offline — no database needed:
   $ runic info --mode LOCAL
   Local revisions : 3
   Heads           : 1
     c1d2e3f4  add vector index

   # Database state only:
   $ runic info --mode REMOTE
   Applied : 7b3d9e2f  add email fulltext index

----

check
-----

.. code-block:: bash

   runic check [--config PATH]

Exit with code 1 if the live graph schema has drifted from the
``target_manifest`` defined in ``env.py``.  Exits 0 when the schema is
up-to-date.

Intended for CI pipelines to catch uncommitted schema changes.

**Options**

``--config PATH``
    Path to ``env.py``.

**Example**

.. code-block:: bash

   # Schema is up-to-date:
   $ runic check
   Schema up-to-date.

   # Schema has drifted:
   $ runic check
   Pending schema changes (run `runic revision --autogenerate -m "..."` to generate):
     + op.create_range_index("Order", "placed_at")
   $ echo $?
   1

See :doc:`autogenerate` for how to configure ``target_manifest``.
