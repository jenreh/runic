# Renaming `username` to `handle` on Person nodes — irreversible migration

## Migration file

Place this file in `runic/versions/` (e.g. `<rev_id>_rename_person_username_to_handle.py`).
Replace `<rev_id>` and `down_revision` with the values runic assigns when you run
`runic revision -m "rename Person.username to handle"`.

```python
"""rename Person.username to handle — irreversible data migration

Revision ID: <rev_id>
Revises: <previous_rev_id>
Create Date: 2026-05-30T12:00:00+00:00
"""
from datetime import UTC, datetime

message = "rename Person.username to handle — irreversible data migration"
create_date = datetime.fromisoformat("2026-05-30T12:00:00+00:00")

revision = "<rev_id>"
down_revision = "<previous_rev_id>"   # None if this is the first migration
branch_labels = []
depends_on = []
irreversible = True   # downgrade blocked unless --force is passed
snapshot = True       # runic GRAPH.COPYs the graph before upgrade; restores on failure


def upgrade(op) -> None:
    # Step 1: copy username → handle for every Person node that has not been
    # migrated yet.  rename_property is batched (default 10 000 nodes per
    # query) and idempotent — safe to re-run after a partial failure.
    op.rename_property("Person", "username", "handle")

    # Step 2: remove the old property.  The original value cannot be
    # reconstructed, so we drop it explicitly.
    # The WHERE guard makes this idempotent.
    op.run_cypher(
        "MATCH (p:Person) WHERE p.username IS NOT NULL REMOVE p.username"
    )


def downgrade(op) -> None:
    # The original username values are gone; a true reversal is impossible.
    # Because snapshot=True, runic will automatically restore the
    # GRAPH.COPY snapshot taken before this upgrade ran.
    raise NotImplementedError(
        "irreversible — original username data cannot be reconstructed; "
        "runic will restore the pre-migration snapshot automatically"
    )
```

---

## Flags to set in the migration file

| Flag | Value | Why |
|---|---|---|
| `irreversible` | `True` | Tells runic to refuse `runic downgrade` for this revision unless the operator explicitly passes `--force`. Protects against accidental rollback of a destructive change. |
| `snapshot` | `True` | Instructs runic to call `GRAPH.COPY` on the live graph before executing `upgrade`. If the upgrade fails mid-run, the snapshot is restored automatically. It also serves as the rollback target when `irreversible = True` and `--force` is used. |

---

## How to apply

```bash
# Preview what will run (no writes):
runic upgrade head --preview

# Apply the migration:
runic upgrade head
```

## Attempting a downgrade

Because `irreversible = True`, a plain downgrade is refused:

```
runic downgrade -1
# ERROR: revision <rev_id> is marked irreversible. Pass --force to override.
```

If you must roll back (e.g. in a disaster-recovery scenario), use `--force`.
Runic will restore the `GRAPH.COPY` snapshot taken at upgrade time:

```bash
runic downgrade -1 --force
```

---

## Key design notes

1. **`op.rename_property` is idempotent.** It runs
   `WHERE n.username IS NOT NULL AND n.handle IS NULL` in batches, so a
   re-run after a crash will continue from where it left off without
   duplicating work.

2. **Drop the old property explicitly** with `op.run_cypher` after the rename
   so that no stale `username` values linger on partially-migrated nodes.
   The `WHERE p.username IS NOT NULL` guard makes this step re-runnable.

3. **Order matters:** rename first, then remove the old key. Reversing this
   order would silently discard data.

4. **`snapshot = True` is the safety net.** Because FalkorDB has no
   multi-statement transactions, a mid-migration crash leaves the graph in
   a mixed state. The snapshot lets runic restore a clean pre-migration
   baseline automatically.
