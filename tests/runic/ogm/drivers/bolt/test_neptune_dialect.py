"""Unit tests for NeptuneDialect and the Neptune Database driver factory."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from runic.ogm.driver import CypherFeature, dialect_supports, require_feature
from runic.ogm.driver.bolt import BoltDriver, BoltEdge
from runic.ogm.driver.neptune import (
    _NEPTUNE_DIALECT,
    _TOKEN_TTL_SECONDS,
    NeptuneDialect,
    NeptuneNode,
    _make_auth_manager,
    _resolve_region,
    _signed_auth_token,
    create_neptune_driver,
)

_ENDPOINT_URL = "https://cluster.example.neptune.amazonaws.com:8182"
_REGION = "eu-central-1"


def _frozen_credentials() -> object:
    from botocore.credentials import Credentials

    return Credentials("AKIA_TEST", "test-secret")


class TestNeptuneDialectFeatures:
    def test_unsupported_features(self) -> None:
        assert _NEPTUNE_DIALECT.unsupported_features == frozenset(
            {
                CypherFeature.PROCEDURE_CALL,
                CypherFeature.FULLTEXT_SEARCH,
                CypherFeature.VECTOR_SEARCH,
            }
        )

    def test_alternation_and_undirected_merge_supported(self) -> None:
        assert dialect_supports(
            _NEPTUNE_DIALECT, CypherFeature.RELATIONSHIP_ALTERNATION
        )
        assert dialect_supports(_NEPTUNE_DIALECT, CypherFeature.UNDIRECTED_MERGE)

    def test_require_feature_names_neptune(self) -> None:
        with pytest.raises(NotImplementedError, match="Neptune"):
            require_feature(
                _NEPTUNE_DIALECT, CypherFeature.VECTOR_SEARCH, "vector_search()"
            )

    def test_supports_geo_update_false(self) -> None:
        assert NeptuneDialect.supports_geo_update is False


class TestNeptuneDialectGeneratedIdWhere:
    def test_no_integer_cast(self) -> None:
        result = _NEPTUNE_DIALECT.generated_id_where("n", "pk")
        assert result == "WHERE id(n) = $pk"
        assert "toInteger" not in result


class TestNeptuneDialectCypherFnForField:
    def test_returns_none_always(self) -> None:
        fi = MagicMock()
        assert _NEPTUNE_DIALECT.cypher_fn_for_field(fi) is None


class TestNeptuneDialectSearchRaises:
    def test_fulltext_call_raises(self) -> None:
        with pytest.raises(NotImplementedError, match="OpenSearch"):
            _NEPTUNE_DIALECT.fulltext_call("Label", "n", "q")

    def test_vector_knn_start_raises(self) -> None:
        with pytest.raises(NotImplementedError, match="Neptune Analytics"):
            _NEPTUNE_DIALECT.vector_knn_start("n", ":Label", "Label", "embedding")

    def test_vector_knn_call_raises(self) -> None:
        with pytest.raises(NotImplementedError, match="Neptune Analytics"):
            _NEPTUNE_DIALECT.vector_knn_call("n", "Label", "embedding", "$k", "$v")

    def test_vector_score_expr_raises(self) -> None:
        with pytest.raises(NotImplementedError):
            _NEPTUNE_DIALECT.vector_score_expr()

    def test_fulltext_yields_score_false(self) -> None:
        assert _NEPTUNE_DIALECT.fulltext_yields_score() is False


class TestNeptuneDialectWrappers:
    def test_wrap_node_returns_neptune_node(self) -> None:
        raw = MagicMock()
        assert isinstance(_NEPTUNE_DIALECT.wrap_node(raw), NeptuneNode)

    def test_wrap_edge_returns_bolt_edge(self) -> None:
        assert isinstance(_NEPTUNE_DIALECT.wrap_edge(MagicMock()), BoltEdge)


class TestNeptuneNodeElementId:
    def test_element_id_is_string(self) -> None:
        raw = MagicMock()
        raw.element_id = "72c2e8c1-7d5f-5f30-10ca-9d2bb8c4afbc"
        node = NeptuneNode(raw)
        assert node.element_id == "72c2e8c1-7d5f-5f30-10ca-9d2bb8c4afbc"

    def test_element_id_ignores_legacy_int_id(self) -> None:
        raw = MagicMock()
        raw.id = 42
        raw.element_id = "custom-id"
        assert NeptuneNode(raw).element_id == "custom-id"


class TestSignedAuthToken:
    def test_token_shape(self) -> None:
        token = _signed_auth_token(_ENDPOINT_URL, _REGION, _frozen_credentials())
        assert token.scheme == "basic"
        assert token.principal == "username"
        payload = json.loads(token.credentials)
        assert payload["HttpMethod"] == "GET"
        assert payload["Host"] == "cluster.example.neptune.amazonaws.com:8182"
        assert payload["Authorization"].startswith("AWS4-HMAC-SHA256")
        assert "neptune-db" in payload["Authorization"]
        assert "X-Amz-Date" in payload

    def test_security_token_included_for_temporary_credentials(self) -> None:
        from botocore.credentials import Credentials

        creds = Credentials("AKIA_TEST", "secret", token="session-token")  # noqa: S106
        token = _signed_auth_token(_ENDPOINT_URL, _REGION, creds)
        assert "X-Amz-Security-Token" in json.loads(token.credentials)

    def test_missing_credentials_raises(self) -> None:
        with (
            patch("botocore.session.Session.get_credentials", return_value=None),
            pytest.raises(RuntimeError, match="credentials"),
        ):
            _signed_auth_token(_ENDPOINT_URL, _REGION)


class TestAuthManager:
    def test_caches_token_within_ttl(self) -> None:
        manager = _make_auth_manager(_ENDPOINT_URL, _REGION, _frozen_credentials())
        assert manager.get_auth() is manager.get_auth()

    def test_security_exception_invalidates_token(self) -> None:
        manager = _make_auth_manager(_ENDPOINT_URL, _REGION, _frozen_credentials())
        first = manager.get_auth()
        assert manager.handle_security_exception(first, None) is True
        assert manager.get_auth() is not first

    def test_expired_token_is_resigned(self) -> None:
        manager = _make_auth_manager(_ENDPOINT_URL, _REGION, _frozen_credentials())
        first = manager.get_auth()
        # Age the token relative to its issue time — an absolute 0.0 is NOT
        # reliably expired: time.monotonic() counts from boot, and a fresh CI
        # VM can be younger than the TTL.
        manager._issued -= _TOKEN_TTL_SECONDS + 1  # noqa: SLF001 - force expiry
        assert manager.get_auth() is not first


class TestResolveRegion:
    def test_explicit_region_wins(self) -> None:
        assert _resolve_region("us-west-2") == "us-west-2"

    def test_unresolvable_region_raises(self) -> None:
        with (
            patch("botocore.session.Session.get_config_variable", return_value=None),
            pytest.raises(ValueError, match="region"),
        ):
            _resolve_region(None)


class TestCreateNeptuneDriver:
    def test_iam_auth_uses_auth_manager_and_tls(self) -> None:
        with patch("neo4j.GraphDatabase.driver") as mock_driver:
            driver = create_neptune_driver(
                "cluster.example.neptune.amazonaws.com",
                region=_REGION,
                credentials=_frozen_credentials(),
            )
        assert isinstance(driver, BoltDriver)
        assert driver.dialect is _NEPTUNE_DIALECT
        assert driver.uri.startswith("bolt+s://")
        auth = mock_driver.call_args.kwargs["auth"]
        from neo4j.auth_management import AuthManager

        assert isinstance(auth, AuthManager)

    def test_without_iam_auth_uses_placeholder_tuple(self) -> None:
        with patch("neo4j.GraphDatabase.driver"):
            driver = create_neptune_driver(
                "cluster.example.neptune.amazonaws.com", use_iam_auth=False
            )
        assert driver.uri == "bolt+s://cluster.example.neptune.amazonaws.com:8182"
        assert driver.auth == ("username", "password")

    def test_factory_dispatch(self) -> None:
        from runic.ogm.driver.factory import create_driver

        with patch("neo4j.GraphDatabase.driver"):
            driver = create_driver(
                "neptune",
                endpoint="cluster.example.neptune.amazonaws.com",
                use_iam_auth=False,
            )
        assert isinstance(driver, BoltDriver)
        assert isinstance(driver.dialect, NeptuneDialect)
