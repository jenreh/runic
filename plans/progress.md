# Ralph Progress Log

Started: 2026-06-07
Project: runic (multi-DB graph ORM)

## Codebase Patterns

- Python 3.14+, uv, task runner (Taskfile.dist.yml)
- Verification: `task lint && task typecheck && task test`
- Adapter/Strategy/Factory architecture for multi-DB drivers (Neo4j, Memgraph, AGE, FalkorDB)
- Session(driver) as the public API; GraphResult.rows for query results
- Field() and Relation() are -> Any functions; FieldDescriptor is the internal class

## Key Files

- `runic/orm/` - ORM core (fields, session, query builder, drivers)
- `runic/migrate/adapters/` - Migration adapters per DB
- `tests/` - Unit tests (pytest with coverage)
- `taskfiles/Taskfile.qa.yml` - lint, format, typecheck, test tasks

---
