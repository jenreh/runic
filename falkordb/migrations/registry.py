from __future__ import annotations

import importlib
import pkgutil

from falkordb.migrations.base import Migration


def discover_migrations() -> list[Migration]:
    """Discover and return migration instances ordered by version."""
    migrations: list[Migration] = []
    package_name = "falkordb.migrations.versions"
    package = importlib.import_module(package_name)

    for _, module_name, _ in pkgutil.iter_modules(package.__path__):
        module = importlib.import_module(f"{package_name}.{module_name}")

        migrations.extend(
            value()
            for value in module.__dict__.values()
            if (
                isinstance(value, type)
                and issubclass(value, Migration)
                and value is not Migration
            )
        )

    migrations.sort(key=lambda migration: migration.version)
    return migrations
