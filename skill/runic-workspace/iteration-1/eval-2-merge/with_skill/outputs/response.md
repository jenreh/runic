## Resolving Diverged Migration Branches in Runic

When `runic heads` shows two entries (e.g. `abc123` and `def456`), it means two revisions were independently created from the same parent — a branch split. Runic refuses to upgrade to `head` when multiple heads exist, so you must merge them first.

### Step-by-step resolution

```bash
# 1. Confirm the two heads
runic heads
# → abc123  (branch A)
# → def456  (branch B)

# 2. Create a merge revision that declares both as parents
runic merge abc123 def456 -m "merge feature-x and feature-y into main"

# 3. (Optional) Open the generated file and add any reconciliation ops
#    needed to make the two branches compatible (e.g. drop a duplicate index).

# 4. Apply the merge revision and everything beneath it
runic upgrade head
```

After step 2, `runic heads` will show only the new merge revision ID. After step 4, the database is fully up-to-date.

### What the merge revision file looks like

Runic writes the merge file into `runic/versions/`. The critical field is `down_revision`, which is a **tuple** of both parent IDs instead of a single string:

```python
"""merge feature-x and feature-y into main

Revision ID: ab12cd34ef56
Revises: abc123, def456
Create Date: 2026-05-30T12:00:00+00:00
"""
from datetime import UTC, datetime

message = "merge feature-x and feature-y into main"
create_date = datetime.fromisoformat("2026-05-30T12:00:00+00:00")

revision = "ab12cd34ef56"
down_revision = ("abc123", "def456")   # <-- tuple, not a string
branch_labels = []
depends_on = []
irreversible = False
snapshot = False


def upgrade(op) -> None:
    pass   # add reconciliation ops here if the branches conflict


def downgrade(op) -> None:
    pass
```

### Key points

| Detail | Explanation |
|---|---|
| `down_revision` is a tuple | This is what distinguishes a merge revision from a normal one. Runic resolves both chains before applying the merge. |
| `upgrade` body is empty by default | The merge itself performs no schema change. Add ops only if the two branches need reconciliation (e.g. one branch created an index the other also created). |
| `downgrade` body is empty by default | Downgrading past the merge point splits back into both parent chains. |
| Order in the tuple | The order of the two revision IDs in `down_revision` does not matter for correctness, but keep it consistent for readability. |
| `depends_on` (alternative) | If you only need to express ordering without merging histories, use `depends_on = ["abc123"]` on one revision instead. This is useful across independent migration streams but does not resolve multiple heads. |

### When to add reconciliation ops

If both branches touch the same label/property (e.g. both create an index on `User.email`), the second `upgrade` call will fail or be a no-op depending on the FalkorDB version. Inspect both migration files and, if needed, add a guarded drop-and-recreate or an idempotent check in the merge revision's `upgrade` function:

```python
def upgrade(op) -> None:
    # Example: drop a duplicate index created by both branches
    op.drop_range_index("User", "email")
    op.create_range_index("User", "email")
```

Keep all data ops idempotent (use `MERGE` / guarded `WHERE … IS NULL`) since FalkorDB has no multi-statement transactions.
