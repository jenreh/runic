# Full Runic Setup Walkthrough — socialnet on localhost:6379

This guide walks through every step: installing runic, initialising the
environment, configuring env.py for your graph, writing the first migration,
and applying it.

---

## 1. Install runic

```bash
uv add runic
# or: pip install runic
```

---

## 2. Initialise the migration environment

Run this once at the root of your project:

```bash
runic init
```

This creates:

```
runic/
├── env.py
├── script.py.mako
└── versions/
    └── .gitkeep
```

---

## 3. Configure runic/env.py

Open `runic/env.py` and replace its contents with the following.  
The `FALKORDB_URL` and `FALKORDB_GRAPH` env vars let you override settings
per-environment (dev / CI / prod) without touching the file.

```python
import os
from runic import context
from runic.adapters import create_adapter
from runic.manifest import SchemaManifest, RangeIndex, UniqueConstraint

adapter = create_adapter(
    "falkordb",
    url=os.getenv("FALKORDB_URL", "falkor://localhost:6379"),
    graph_name=os.getenv("FALKORDB_GRAPH", "socialnet"),
)

# Optional but recommended: declare your target schema so runic can
# autogenerate migrations and power the `runic check` CI gate.
manifest = SchemaManifest(
    range_indexes=[
        RangeIndex("User", "email"),
    ],
    constraints=[
        UniqueConstraint("NODE", "User", ["email"]),
    ],
)

context.configure(adapter, target_manifest=manifest)
```

Key points:
- The URL scheme is `falkor://` (not `redis://`).
- `graph_name` must match the graph you already use in your app — here
  `"socialnet"`.
- Adding `target_manifest` is optional for a hand-written migration, but it
  enables `runic check` (CI drift detection) and `--autogenerate` later.

---

## 4. Create the first migration

```bash
runic revision -m "add User email range index and unique constraint"
```

Runic writes a new file under `runic/versions/` named something like
`runic/versions/1975ea83b712_add_user_email_range_index_and_unique_constraint.py`.

Open that file and fill in `upgrade` and `downgrade`:

```python
"""add User email range index and unique constraint

Revision ID: 1975ea83b712
Revises: None
Create Date: 2026-05-30T14:00:00+00:00
"""
from datetime import UTC, datetime

message = "add User email range index and unique constraint"
create_date = datetime.fromisoformat("2026-05-30T14:00:00+00:00")

revision = "1975ea83b712"
down_revision = None       # first migration — no parent
branch_labels = []
depends_on = []
irreversible = False
snapshot = False


def upgrade(op) -> None:
    # 1. Create the range index first — the unique constraint needs it.
    op.create_range_index("User", "email")
    # 2. Create the unique constraint.
    #    runic polls CALL db.constraints() until status = OPERATIONAL.
    op.create_constraint("UNIQUE", "NODE", "User", ["email"])


def downgrade(op) -> None:
    # Always drop the constraint BEFORE the backing index, or FalkorDB
    # will refuse the index drop.
    op.drop_constraint("UNIQUE", "NODE", "User", ["email"])
    op.drop_range_index("User", "email")
```

### Ordering rules to remember

| Phase     | Order                                       |
|-----------|---------------------------------------------|
| upgrade   | range index first, then unique constraint   |
| downgrade | unique constraint first, then range index   |

`create_constraint("UNIQUE", ...)` will auto-create the backing range index
if it does not exist, but creating it explicitly first is clearer and keeps
the downgrade symmetrical.

---

## 5. Preview (dry-run, optional)

Before touching the live graph, confirm what runic will run:

```bash
runic upgrade head --preview
```

You will see the ops logged without any changes applied.

---

## 6. Apply the migration

```bash
runic upgrade head
```

Runic connects to `falkor://localhost:6379`, opens the `socialnet` graph,
creates a `(:_FalkorMigrateVersion)` tracking node if it does not exist, runs
`upgrade(op)`, and stamps the graph at revision `1975ea83b712`.

Confirm the applied revision:

```bash
runic current
# → 1975ea83b712
```

View the full history:

```bash
runic history
```

---

## 7. Optional: test the migration round-trip

```bash
runic test 1975ea83b712
```

This runs upgrade → downgrade → upgrade on an ephemeral copy of the graph and
prints entity/index/constraint counts at each phase. The copy is deleted on
exit. Expected output:

```
─────────────────────────────────────────────
Phase A (upgrade):    ✓  nodes=0  indices=1  constraints=1
Phase B (downgrade):  ✓  nodes=0  indices=0  constraints=0
Phase C (idempotency):✓  nodes=0  indices=1  constraints=1
─────────────────────────────────────────────
PASSED
```

---

## 8. CI drift gate (optional)

Add this to your CI pipeline. It exits with code 1 if the live graph is out of
sync with the manifest declared in `env.py`:

```bash
runic check
```

---

## Summary of commands used

```bash
uv add runic
runic init
# edit runic/env.py
runic revision -m "add User email range index and unique constraint"
# edit the generated versions/*.py
runic upgrade head --preview   # optional dry-run
runic upgrade head
runic current
runic test 1975ea83b712        # optional round-trip test
runic check                    # optional CI gate
```
