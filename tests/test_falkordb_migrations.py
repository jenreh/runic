from __future__ import annotations

import importlib
from dataclasses import dataclass
from types import ModuleType
from typing import Any

import pytest

import falkordb
from falkordb.bootstrap import main as bootstrap_main
from falkordb.client import connect_to_graph
from falkordb.config import FalkorDBSettings
from falkordb.migration_runner import (
    MigrationChecksumMismatchError,
    MigrationRunner,
)
from falkordb.migration_runner import (
    main as runner_main,
)
from falkordb.migrations.base import Migration
from falkordb.migrations.registry import (
    DuplicateMigrationVersionError,
    discover_migrations,
)
from falkordb.migrations.utils import IndexWaitTimeoutError, wait_for_indexes
from falkordb.queries.location_queries import search_locations_query
from falkordb.queries.recommendation_queries import recommend_locations_query
from falkordb.queries.trip_queries import get_trip_by_id_query
from falkordb.schema.constraints import REQUIRED_CONSTRAINTS, ConstraintSpec
from falkordb.schema.labels import INTEREST, LOCATION, TRIP, USER
from falkordb.schema.relationships import (
    CAN_ACCESS,
    HAS_CATEGORY,
    INTERESTED_IN,
    OWNS,
    VISITS,
)
from falkordb.services.authorization_service import AuthorizationService
from falkordb.services.location_graph_service import LocationGraphService
from falkordb.services.trip_graph_service import TripGraphService
from falkordb.validate import (
    SchemaValidationError,
    assert_constraint_exists,
    validate_required_constraints,
)
from falkordb.validate import (
    main as validate_main,
)

InitialSchema = importlib.import_module(
    "falkordb.migrations.versions.001_initial_schema"
).InitialSchema
LocationIndexes = importlib.import_module(
    "falkordb.migrations.versions.002_location_indexes"
).LocationIndexes
InterestNodes = importlib.import_module(
    "falkordb.migrations.versions.003_interest_nodes"
).InterestNodes
AddGeoPoints = importlib.import_module(
    "falkordb.migrations.versions.004_add_geo_points"
).AddGeoPoints
TripAccessConstraints = importlib.import_module(
    "falkordb.migrations.versions.005_trip_access_constraints"
).TripAccessConstraints


class _FakeResult:
    def __init__(self, result_set: list[tuple[Any, ...]]) -> None:
        self.result_set = result_set


@dataclass
class _Constraint:
    label: str
    properties: list[str]


@dataclass
class _Index:
    status: str


class _GraphRecorder:
    def __init__(
        self,
        migration_rows: list[tuple[Any, ...]] | None = None,
        query_result_sets: list[list[tuple[Any, ...]]] | None = None,
        constraints: list[_Constraint] | None = None,
        indexes: list[list[_Index]] | None = None,
    ) -> None:
        self.migration_rows = migration_rows or []
        self.query_result_sets = query_result_sets or []
        self.constraints = constraints or []
        self.indexes = indexes or [[_Index(status="OPERATIONAL")]]
        self.ro_calls: list[tuple[str, dict[str, Any] | None]] = []
        self.query_calls: list[tuple[str, dict[str, Any] | None]] = []
        self.created_operations: list[tuple[str, tuple[Any, ...]]] = []
        self._index_call_count = 0

    def ro_query(
        self,
        query: str,
        params: dict[str, Any] | None = None,
    ) -> _FakeResult:
        self.ro_calls.append((query, params))
        if "SchemaMigration" in query:
            return _FakeResult(self.migration_rows)
        if self.query_result_sets:
            return _FakeResult(self.query_result_sets.pop(0))
        return _FakeResult([])

    def query(self, query: str, params: dict[str, Any] | None = None) -> None:
        self.query_calls.append((query, params))

    def list_indexes(self) -> list[_Index]:
        selected_index = min(self._index_call_count, len(self.indexes) - 1)
        self._index_call_count += 1
        return self.indexes[selected_index]

    def list_constraints(self) -> list[_Constraint]:
        return self.constraints

    def create_node_range_index(self, label: str, property_name: str) -> None:
        self.created_operations.append(("range", (label, property_name)))

    def create_node_unique_constraint(self, label: str, property_name: str) -> None:
        self.created_operations.append(("unique", (label, property_name)))

    def create_node_fulltext_index(self, label: str, *property_names: str) -> None:
        self.created_operations.append(("fulltext", (label, *property_names)))


class _Migration001(Migration):
    version = "001"
    description = "first"

    def up(self, graph: _GraphRecorder) -> None:
        graph.created_operations.append(("migration", (self.version,)))


class _Migration002(Migration):
    version = "002"
    description = "second"

    def up(self, graph: _GraphRecorder) -> None:
        graph.created_operations.append(("migration", (self.version,)))


def _empty_up(_graph: _GraphRecorder) -> None:
    return None


def test_settings_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    expected_secret = "-".join(["service", "secret"])

    monkeypatch.setenv("FALKORDB_HOST", "graph.example")
    monkeypatch.setenv("FALKORDB_PORT", "6380")
    monkeypatch.setenv("FALKORDB_GRAPH", "voyager-test")
    monkeypatch.setenv("FALKORDB_USERNAME", "service-user")
    monkeypatch.setenv("FALKORDB_PASSWORD", expected_secret)
    monkeypatch.setenv("FALKORDB_INDEX_POLL_INTERVAL", "1.5")
    monkeypatch.setenv("FALKORDB_INDEX_TIMEOUT", "12.5")

    settings = FalkorDBSettings.from_env()

    assert settings.host == "graph.example"
    assert settings.port == 6380
    assert settings.graph_name == "voyager-test"
    assert settings.username == "service-user"
    assert settings.password == expected_secret
    assert settings.index_poll_interval == 1.5
    assert settings.index_timeout == 12.5


def test_connect_to_graph_uses_injected_factory() -> None:
    settings = falkordb.FalkorDBSettings(graph_name="voyager")

    graph = connect_to_graph(settings, lambda received: {"graph": received.graph_name})

    assert graph == {"graph": "voyager"}


def test_connect_to_graph_requires_factory() -> None:
    with pytest.raises(RuntimeError, match="graph_factory"):
        connect_to_graph(FalkorDBSettings())


def test_discover_migrations_returns_ordered_versions() -> None:
    migrations = discover_migrations()
    versions = [migration.version for migration in migrations]

    assert versions == sorted(versions)
    assert versions == [
        "001_initial_schema",
        "002_location_indexes",
        "003_interest_nodes",
        "004_add_geo_points",
        "005_trip_access_constraints",
    ]


def test_discover_migrations_rejects_duplicate_versions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = ModuleType("falkordb.migrations.versions")
    package.__path__ = ["/virtual"]
    module = ModuleType("falkordb.migrations.versions.fake")

    class DuplicateA(Migration):
        version = "001"
        description = "duplicate-a"
        up = _empty_up

    class DuplicateB(Migration):
        version = "001"
        description = "duplicate-b"
        up = _empty_up

    module.DuplicateA = DuplicateA
    module.DuplicateB = DuplicateB

    def fake_import(name: str) -> ModuleType:
        if name == "falkordb.migrations.versions":
            return package
        if name == "falkordb.migrations.versions.fake":
            return module
        msg = f"Unexpected import: {name}"
        raise AssertionError(msg)

    monkeypatch.setattr("falkordb.migrations.registry.importlib.import_module", fake_import)
    monkeypatch.setattr(
        "falkordb.migrations.registry.pkgutil.iter_modules",
        lambda _path: [(None, "fake", False)],
    )

    with pytest.raises(DuplicateMigrationVersionError):
        discover_migrations()


def test_migration_down_is_not_supported() -> None:
    migration = _Migration001()

    with pytest.raises(NotImplementedError, match="Rollback not supported"):
        migration.down(_GraphRecorder())


def test_initial_schema_creates_expected_indexes_and_constraints() -> None:
    graph = _GraphRecorder()

    InitialSchema().up(graph)

    assert graph.created_operations == [
        ("range", ("User", "auth_user_id")),
        ("unique", ("User", "auth_user_id")),
        ("range", ("Trip", "id")),
        ("unique", ("Trip", "id")),
        ("range", ("Location", "geo")),
        ("fulltext", ("Location", "title", "description")),
        ("unique", ("Location", "id")),
    ]


def test_runner_applies_only_pending_migrations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = _GraphRecorder(migration_rows=[("001", None)])
    runner = MigrationRunner(graph)

    monkeypatch.setattr(
        "falkordb.migration_runner.discover_migrations",
        lambda: [_Migration001(), _Migration002()],
    )
    monkeypatch.setattr(
        "falkordb.migration_runner.wait_for_indexes",
        lambda *_args, **_kwargs: None,
    )

    runner.run()

    assert graph.created_operations == [("migration", ("002",))]
    assert graph.query_calls[0][1] == {
        "version": "002",
        "description": "second",
        "checksum": runner._checksum_for(_Migration002()),
    }


def test_runner_detects_checksum_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    graph = _GraphRecorder(migration_rows=[("001", "outdated-checksum")])
    runner = MigrationRunner(graph)

    monkeypatch.setattr(
        "falkordb.migration_runner.discover_migrations",
        lambda: [_Migration001()],
    )

    with pytest.raises(MigrationChecksumMismatchError, match="001"):
        runner.run()


def test_wait_for_indexes_waits_until_operational(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = _GraphRecorder(indexes=[[ _Index(status="BUILDING")], [_Index(status="OPERATIONAL")]])
    sleeps: list[float] = []

    monkeypatch.setattr("falkordb.migrations.utils.time.sleep", sleeps.append)

    wait_for_indexes(graph, poll_interval=0.01, max_wait=1.0)

    assert sleeps == [0.01]


def test_wait_for_indexes_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    graph = _GraphRecorder(indexes=[[ _Index(status="BUILDING")]])
    monotonic_values = iter([0.0, 0.0])

    monkeypatch.setattr(
        "falkordb.migrations.utils.time.monotonic",
        lambda: next(monotonic_values),
    )

    with pytest.raises(IndexWaitTimeoutError, match="Timed out"):
        wait_for_indexes(graph, max_wait=0.0)


def test_assert_constraint_exists_raises_when_missing() -> None:
    graph = _GraphRecorder(constraints=[])

    with pytest.raises(SchemaValidationError, match=r"Missing Trip\(id\) constraint"):
        assert_constraint_exists(graph, "Trip", "id")


def test_validate_required_constraints_checks_all() -> None:
    graph = _GraphRecorder(
        constraints=[
            _Constraint(label="User", properties=["auth_user_id"]),
            _Constraint(label="Trip", properties=["id"]),
            _Constraint(label="Location", properties=["id"]),
            _Constraint(label="Interest", properties=["id"]),
        ]
    )

    validate_required_constraints(graph, REQUIRED_CONSTRAINTS)


def test_bootstrap_graph_runs_migrations_and_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    class FakeRunner:
        def __init__(self, graph: Any, poll_interval: float, max_wait: float) -> None:
            assert graph == "graph"
            assert poll_interval == 0.25
            assert max_wait == 9.0
            calls.append("init")

        def run(self) -> None:
            calls.append("run")

    monkeypatch.setattr("falkordb.bootstrap.MigrationRunner", FakeRunner)
    monkeypatch.setattr(
        "falkordb.bootstrap.validate_required_constraints",
        lambda graph: calls.append(f"validate:{graph}"),
    )

    falkordb.bootstrap_graph("graph", poll_interval=0.25, max_wait=9.0)

    assert calls == ["init", "run", "validate:graph"]


def test_bootstrap_main_uses_settings_and_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = FalkorDBSettings(index_poll_interval=1.25, index_timeout=7.5)
    calls: list[Any] = []

    monkeypatch.setattr(
        "falkordb.bootstrap.bootstrap_graph",
        lambda graph, poll_interval, max_wait: calls.extend(
            [graph, poll_interval, max_wait]
        ),
    )

    bootstrap_main(settings, lambda _settings: "graph")

    assert calls == ["graph", 1.25, 7.5]


def test_runner_main_builds_graph_from_settings() -> None:
    settings = FalkorDBSettings(index_poll_interval=2.0, index_timeout=4.0)
    calls: list[Any] = []

    def graph_factory(_settings: FalkorDBSettings) -> str:
        return "graph"

    class FakeRunner:
        def __init__(self, graph: Any, poll_interval: float, max_wait: float) -> None:
            calls.extend([graph, poll_interval, max_wait])

        def run(self) -> None:
            calls.append("run")

    import falkordb.migration_runner as migration_runner_module

    migration_runner_module.MigrationRunner = FakeRunner  # type: ignore[assignment]
    try:
        runner_main(settings, graph_factory)
    finally:
        migration_runner_module.MigrationRunner = MigrationRunner  # type: ignore[assignment]

    assert calls == ["graph", 2.0, 4.0, "run"]


def test_validate_main_builds_graph_and_validates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[Any] = []
    settings = FalkorDBSettings()

    def capture_validation(graph: Any) -> None:
        calls.append(graph)

    monkeypatch.setattr(
        "falkordb.validate.validate_required_constraints",
        capture_validation,
    )

    validate_main(settings, lambda _settings: "graph")

    assert calls == ["graph"]


def test_query_builders_are_parameterized() -> None:
    trip_query, trip_params = get_trip_by_id_query("trip-1")
    location_query, location_params = search_locations_query("museum")
    recommendation_query, recommendation_params = recommend_locations_query(
        "trip-1", limit=3
    )

    assert "$trip_id" in trip_query
    assert trip_params == {"trip_id": "trip-1"}
    assert "$search_text" in location_query
    assert location_params == {"search_text": "museum"}
    assert "$limit" in recommendation_query
    assert recommendation_params == {"trip_id": "trip-1", "limit": 3}


def test_trip_and_location_services_delegate_read_queries() -> None:
    graph = _GraphRecorder(
        query_result_sets=[[("trip",)], [("location",)], [("rec",)]]
    )
    trip_service = TripGraphService(graph)
    location_service = LocationGraphService(graph)

    assert trip_service.get_trip("trip-1").result_set == [("trip",)]
    assert location_service.search("museum").result_set == [("location",)]
    assert location_service.recommend_for_trip("trip-1", 5).result_set == [("rec",)]
    assert graph.ro_calls[0][1] == {"trip_id": "trip-1"}
    assert graph.ro_calls[1][1] == {"search_text": "museum"}
    assert graph.ro_calls[2][1] == {"trip_id": "trip-1", "limit": 5}


def test_authorization_service_returns_boolean() -> None:
    allowed_graph = _GraphRecorder(query_result_sets=[[(True,)]])
    denied_graph = _GraphRecorder(query_result_sets=[[(False,)]])
    allowed_service = AuthorizationService(allowed_graph)
    denied_service = AuthorizationService(denied_graph)

    assert allowed_service.user_can_access_trip("user-1", "trip-1") is True
    assert denied_service.user_can_access_trip("user-1", "trip-1") is False


def test_constraint_spec_shape() -> None:
    assert REQUIRED_CONSTRAINTS == (
        ConstraintSpec("User", ("auth_user_id",)),
        ConstraintSpec("Trip", ("id",)),
        ConstraintSpec("Location", ("id",)),
        ConstraintSpec("Interest", ("id",)),
    )


def test_relationship_constants_are_exposed() -> None:
    assert (OWNS, VISITS, CAN_ACCESS) == ("OWNS", "VISITS", "CAN_ACCESS")


def test_new_relationship_constants_are_exposed() -> None:
    assert INTERESTED_IN == "INTERESTED_IN"
    assert HAS_CATEGORY == "HAS_CATEGORY"


def test_schema_label_constants() -> None:
    assert USER == "User"
    assert TRIP == "Trip"
    assert LOCATION == "Location"
    assert INTEREST == "Interest"


def test_location_indexes_migration_creates_expected_indexes() -> None:
    graph = _GraphRecorder()

    LocationIndexes().up(graph)

    assert graph.created_operations == [
        ("range", ("Location", "country")),
        ("range", ("Location", "category")),
    ]


def test_interest_nodes_migration_creates_expected_schema() -> None:
    graph = _GraphRecorder()

    InterestNodes().up(graph)

    assert graph.created_operations == [
        ("range", ("Interest", "id")),
        ("unique", ("Interest", "id")),
        ("fulltext", ("Interest", "name")),
    ]


def test_add_geo_points_migration_creates_expected_indexes() -> None:
    graph = _GraphRecorder()

    AddGeoPoints().up(graph)

    assert graph.created_operations == [
        ("range", ("Location", "latitude")),
        ("range", ("Location", "longitude")),
    ]


def test_trip_access_constraints_migration_creates_expected_schema() -> None:
    graph = _GraphRecorder()

    TripAccessConstraints().up(graph)

    assert graph.created_operations == [
        ("range", ("User", "id")),
        ("unique", ("User", "id")),
        ("range", ("Trip", "created_at")),
    ]
