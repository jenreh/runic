# Migration

`runic.migrate` is an Alembic-style schema migration engine for graph
databases — FalkorDB, ArcadeDB, Neo4j, Memgraph, and Apache AGE.
It tracks every change to your graph's indexes and constraints as a versioned,
replayable script and gives you a CLI to apply, roll back, inspect, and test
those changes safely.

## Migration

- [Migration quickstart](./quickstart.md) — Install runic, run `runic init`, write your first migration, and apply it — all in one page.
- [OGM + Migration guide](./integration.md) — Three-stage workflow, Field→op translation, ordering rules, and 7 annotated patterns — the complete lifecycle guide.
- [CLI reference](./cli-reference.md) — Every command, option, and flag documented with examples.
- [Operations reference](./operations-reference.md) — Full list of `op.*` calls available inside migration scripts.
- [Schema management](./schema.md) — IndexManager and SchemaManager — declare, validate, and sync indexes.
- [Migration API reference](./api.md) — `runic.migrate` — programmatic migration engine API.

---
