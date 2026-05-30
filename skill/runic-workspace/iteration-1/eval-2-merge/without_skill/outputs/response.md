# Resolving Multiple Heads in Runic

## The Problem

When two branches each introduce a migration based on the same parent revision, the migration graph develops multiple heads. Running `runic heads` shows both:

```
abc123 (head)
def456 (head)
```

This means the migration history has forked — there is no single linear path to the latest state — and Runic will refuse to run `runic upgrade` until the fork is resolved.

## Resolution Steps

You need to create a **merge revision** that declares both `abc123` and `def456` as its down-revision parents. This collapses the two heads into one.

### Step 1: Generate the merge revision

Using a command analogous to Alembic (which Runic is modeled after):

```bash
runic merge abc123 def456 -m "merge_branch_a_and_branch_b"
```

This creates a new migration file with both heads listed as parents.

### Step 2: Review and apply

After generating the merge file, run:

```bash
runic heads        # should now show only one head
runic upgrade head # apply the merge
```

---

## What the Merge Revision File Looks Like

A Runic merge revision file is a Python file in your migrations directory. Its key characteristic is that `down_revision` is a **tuple** containing both parent revision IDs instead of a single string.

```python
"""merge_branch_a_and_branch_b

Revision ID: 7f3a1c9e2b05
Revises: abc123, def456
Create Date: 2026-05-30 10:00:00.000000

"""

from runic import MigrationContext

# revision identifiers, used by Runic
revision = "7f3a1c9e2b05"
down_revision = ("abc123", "def456")   # tuple — both parents
branch_labels = None
depends_on = None


def upgrade(context: MigrationContext) -> None:
    # Merge revisions typically contain no operations.
    # Both branch migrations are already applied independently;
    # this revision only stitches the graph back together.
    pass


def downgrade(context: MigrationContext) -> None:
    pass
```

### Key Points

- `down_revision` is a **tuple** (or list), not a plain string. This is what signals to Runic that this is a merge point.
- The `upgrade` and `downgrade` functions are usually empty (`pass`). The actual schema changes were already applied by `abc123` and `def456` independently.
- After this file is applied, `runic heads` will return only the single new merge revision ID (`7f3a1c9e2b05` in the example).
- The merge revision must be committed and shared with both teams so everyone is working from the same linear history going forward.

---

## Why This Happens

Multiple heads occur when two developers (or two branches) both run `runic revision` against the same current head. Each new revision records the same `down_revision`, creating a fork. The merge revision is the standard way to reconcile this without losing either branch's changes.
