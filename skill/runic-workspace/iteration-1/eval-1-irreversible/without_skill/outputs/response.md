# Renaming Person.username to Person.handle — Irreversible Migration

## Migration File

Place this file in your `versions/` directory. The filename follows the runic convention: `{revision_id}_{slug}.py`.

**Example filename:** `a1b2c3d4e5f6_rename_person_username_to_handle.py`

```python
"""rename Person.username to handle — irreversible data migration

Revision ID: a1b2c3d4e5f6
Revises: <your_current_head_revision>
Create Date: 2026-05-30T12:00:00+00:00
"""
from datetime import UTC, datetime

message = "rename Person.username to handle — irreversible data migration"
create_date = datetime.fromisoformat("2026-05-30T12:00:00+00:00")

revision = "a1b2c3d4e5f6"
down_revision = "<your_current_head_revision>"
branch_labels = []
depends_on = []
irreversible = True   # downgrade is blocked unless --force is passed
snapshot = True       # runic takes a GRAPH.COPY before upgrade; auto-restores on failure


def upgrade(op) -> None:
    # rename_property copies values in batches (default 10 000 nodes per query)
    # and is idempotent — safe to re-run if the migration is interrupted.
    op.rename_property("Person", "username", "handle")


def downgrade(op) -> None:
    # The original username values no longer exist after upgrade.
    # runic will automatically restore the pre-migration snapshot
    # (taken because snapshot=True) when this revision is rolled back.
    raise NotImplementedError(
        "irreversible — runic will restore the pre-migration snapshot"
    )
```

## Flags to Set

### In the migration file itself

| Flag | Value | Why |
|------|-------|-----|
| `irreversible` | `True` | Tells runic the downgrade path is permanently blocked. Running `runic downgrade` against this revision will raise an error unless `--force` is explicitly passed on the CLI. |
| `snapshot` | `True` | Instructs runic to call `GRAPH.COPY` before applying `upgrade()`. If the migration fails partway through, runic automatically restores from that copy. Because you cannot reconstruct the old data, this is your only safety net. |

### On the CLI (when applying)

```bash
# Preview what will run — no writes to the graph
runic upgrade --dry-run

# Apply the migration
runic upgrade
```

If you ever need to force a rollback past an irreversible revision (restoring from the snapshot):

```bash
runic downgrade --force <target_revision>
```

Without `--force`, runic refuses to downgrade through any revision marked `irreversible = True`.

## How it works

1. **Before upgrade** — because `snapshot = True`, runic calls `GRAPH.COPY` to create a point-in-time copy of your graph.
2. **During upgrade** — `op.rename_property("Person", "username", "handle")` runs the following Cypher in batches until no nodes remain with the old property:
   ```cypher
   MATCH (n:Person)
   WHERE n.`username` IS NOT NULL AND n.`handle` IS NULL
   WITH n LIMIT 10000
   SET n.`handle` = n.`username`
   REMOVE n.`username`
   RETURN count(n) AS affected
   ```
3. **On failure** — runic detects the error and restores from the snapshot automatically.
4. **On success** — the snapshot is retained until explicitly dropped; `username` no longer exists on any `Person` node.

## Important Notes

- Replace `<your_current_head_revision>` with the actual revision ID of your current head (find it with `runic heads` or `runic history`).
- Replace the `revision` value (`a1b2c3d4e5f6`) with a real 12-character hex ID, or generate one with `runic revision --autogenerate` (or let runic generate the file via `runic revision -m "rename Person.username to handle"`).
- If `username` is indexed, add `op.create_range_index("Person", "handle")` after the rename and `op.drop_range_index("Person", "username")` before it (or vice versa depending on your index strategy).
