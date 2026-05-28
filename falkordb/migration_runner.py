from __future__ import annotations

import hashlib
import logging
from typing import Any

from falkordb.client import GraphFactory, connect_to_graph
from falkordb.config import FalkorDBSettings
from falkordb.migrations.base import Migration
from falkordb.migrations.registry import discover_migrations
from falkordb.migrations.utils import wait_for_indexes
from falkordb.schema.labels import SCHEMA_MIGRATION

log = logging.getLogger(__name__)


class MigrationChecksumMismatchError(RuntimeError):
    """Raised when an applied migration checksum no longer matches source."""


class MigrationRunner:
    def __init__(
        self,
        graph: Any,
        poll_interval: float = 0.5,
        max_wait: float = 30.0,
    ) -> None:
        self.graph = graph
        self.poll_interval = poll_interval
        self.max_wait = max_wait

    def get_applied_migrations(self) -> dict[str, str | None]:
        query = f"""
        MATCH (m:{SCHEMA_MIGRATION})
        RETURN m.version AS version, m.checksum AS checksum
        """
        result = self.graph.ro_query(query)
        return {row[0]: row[1] if len(row) > 1 else None for row in result.result_set}

    def get_applied_versions(self) -> set[str]:
        return set(self.get_applied_migrations())

    @staticmethod
    def _checksum_for(migration: Migration) -> str:
        payload = f"{migration.version}:{migration.description}".encode()
        return hashlib.sha256(payload).hexdigest()

    def _validate_checksums(self, migrations: list[Migration]) -> dict[str, str | None]:
        applied = self.get_applied_migrations()
        for migration in migrations:
            recorded_checksum = applied.get(migration.version)
            current_checksum = self._checksum_for(migration)
            if recorded_checksum is not None and recorded_checksum != current_checksum:
                msg = (
                    "Applied FalkorDB migration checksum does not match the current "
                    f"implementation: {migration.version}"
                )
                raise MigrationChecksumMismatchError(msg)
        return applied

    def apply_migration(self, migration: Migration) -> None:
        log.info("Applying FalkorDB migration %s", migration.version)
        migration.up(self.graph)
        wait_for_indexes(
            self.graph,
            poll_interval=self.poll_interval,
            max_wait=self.max_wait,
        )

        query = f"""
        CREATE (:{SCHEMA_MIGRATION} {{
            version: $version,
            description: $description,
            checksum: $checksum,
            applied_at: datetime()
        }})
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
        migrations = discover_migrations()
        applied = self._validate_checksums(migrations)

        for migration in migrations:
            if migration.version not in applied:
                self.apply_migration(migration)
                applied[migration.version] = self._checksum_for(migration)


def main(
    settings: FalkorDBSettings | None = None,
    graph_factory: GraphFactory | None = None,
) -> None:
    active_settings = settings or FalkorDBSettings.from_env()
    graph = connect_to_graph(active_settings, graph_factory)
    runner = MigrationRunner(
        graph,
        poll_interval=active_settings.index_poll_interval,
        max_wait=active_settings.index_timeout,
    )
    runner.run()


if __name__ == "__main__":
    main()
