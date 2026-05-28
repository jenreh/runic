from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest

from falkordb.migration_runner import MigrationRunner
from falkordb.migrations.base import Migration
from falkordb.migrations.registry import discover_migrations
from falkordb.migrations.utils import wait_for_indexes
from falkordb.validate import assert_constraint_exists


class _FakeResult:
    def __init__(self, result_set: list[tuple[str]]) -> None:
        self.result_set = result_set


class _FakeGraph:
    def __init__(self, applied: list[str]) -> None:
        self._applied = applied
        self.applied_calls: list[str] = []
        self.query_calls: list[dict[str, Any]] = []
        self._index_calls = 0

    def ro_query(self, _query: str) -> _FakeResult:
        return _FakeResult([(version,) for version in self._applied])

    def query(self, _query: str, params: dict[str, Any]) -> None:
        self.query_calls.append(params)

    def list_indexes(self) -> list[SimpleNamespace]:
        self._index_calls += 1
        if self._index_calls == 1:
            return [SimpleNamespace(status="BUILDING")]
        return [SimpleNamespace(status="OPERATIONAL")]


class _Migration001(Migration):
    version = "001"
    description = "first"

    def up(self, graph: _FakeGraph) -> None:
        graph.applied_calls.append(self.version)


class _Migration002(Migration):
    version = "002"
    description = "second"

    def up(self, graph: _FakeGraph) -> None:
        graph.applied_calls.append(self.version)


def test_discover_migrations_returns_ordered_versions() -> None:
    migrations = discover_migrations()
    versions = [migration.version for migration in migrations]

    assert versions == sorted(versions)
    assert "001_initial_schema" in versions


def test_runner_applies_only_pending_migrations(monkeypatch: pytest.MonkeyPatch) -> None:
    graph = _FakeGraph(applied=["001"])
    runner = MigrationRunner(graph)

    monkeypatch.setattr(
        "falkordb.migration_runner.discover_migrations",
        lambda: [_Migration001(), _Migration002()],
    )
    monkeypatch.setattr("falkordb.migration_runner.wait_for_indexes", lambda _graph: None)

    runner.run()

    assert graph.applied_calls == ["002"]
    assert len(graph.query_calls) == 1
    assert graph.query_calls[0]["version"] == "002"
    assert "checksum" in graph.query_calls[0]


def test_wait_for_indexes_waits_until_operational(monkeypatch: pytest.MonkeyPatch) -> None:
    graph = _FakeGraph(applied=[])
    sleeps: list[float] = []

    monkeypatch.setattr("falkordb.migrations.utils.time.sleep", sleeps.append)

    wait_for_indexes(graph, poll_interval=0.01)

    assert sleeps == [0.01]


def test_assert_constraint_exists_raises_when_missing() -> None:
    graph = SimpleNamespace(list_constraints=list)

    with pytest.raises(RuntimeError, match=r"Missing Trip\(id\) constraint"):
        assert_constraint_exists(graph, "Trip", "id")


@dataclass
class _Constraint:
    label: str
    properties: list[str]


def test_assert_constraint_exists_passes_when_present() -> None:
    graph = SimpleNamespace(
        list_constraints=lambda: [_Constraint(label="Trip", properties=["id"])]
    )

    assert_constraint_exists(graph, "Trip", "id")
