from __future__ import annotations

import hashlib
from typing import Any

from falkordb.migrations.base import Migration
from falkordb.migrations.registry import discover_migrations
from falkordb.migrations.utils import wait_for_indexes


class MigrationRunner:
    def __init__(self, graph: Any) -> None:
        self.graph = graph

    def get_applied_versions(self) -> set[str]:
        query = """
        MATCH (m:SchemaMigration)
        RETURN m.version AS version
        """
        result = self.graph.ro_query(query)
        return {row[0] for row in result.result_set}

    @staticmethod
    def _checksum_for(migration: Migration) -> str:
        payload = f"{migration.version}:{migration.description}".encode()
        return hashlib.sha256(payload).hexdigest()

    def apply_migration(self, migration: Migration) -> None:
        migration.up(self.graph)
        wait_for_indexes(self.graph)

        query = """
        CREATE (:SchemaMigration {
            version: $version,
            description: $description,
            checksum: $checksum,
            applied_at: datetime()
        })
        """
        self.graph.query(
            query,
            {
                "version": migration.version,
                "description": migration.description,
                "checksum": self._checksum_for(migration),
            },
        )

    def run(self) -> None:
        applied = self.get_applied_versions()
        migrations = discover_migrations()

        for migration in migrations:
            if migration.version not in applied:
                self.apply_migration(migration)
                applied.add(migration.version)
