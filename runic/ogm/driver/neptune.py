"""Amazon Neptune Database dialect and driver factory.

Neptune Database speaks openCypher over the Bolt protocol (cluster endpoint,
port 8182, TCP only, TLS mandatory), so the connection reuses the generic
:class:`~runic.ogm.driver.bolt.BoltDriver` — only the dialect and the IAM
authentication token are Neptune-specific.

Authentication comes in two flavours:

- **IAM auth disabled** on the cluster: Neptune ignores the Bolt ``auth``
  parameters entirely; any placeholder credentials work.
- **IAM auth enabled** (the AWS default recommendation): every new Bolt
  connection must present an AWS SigV4-signed token.  Signatures expire after
  roughly five minutes, so a static token would break connection-pool growth;
  :func:`create_neptune_driver` therefore installs a ``neo4j`` AuthManager
  that re-signs on demand and invalidates the token on security errors.

Implemented against AWS's documented behaviour (engine ``1.4.x``, 2026-08) but
**not yet live-verified** — Neptune is VPC-only and has no local emulator.
Known openCypher gaps are declared on :class:`NeptuneDialect`; see
``docs/ogm/drivers.md`` for the full support matrix.
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from runic.ogm.driver import CypherFeature
from runic.ogm.driver.bolt import BoltDriver, BoltEdge, BoltNode

if TYPE_CHECKING:
    from runic.ogm.core.descriptors import FieldInfo

_SERVICE_NAME = "neptune-db"
# SigV4 signatures are valid for ~5 minutes; refresh comfortably before expiry.
_TOKEN_TTL_SECONDS = 240.0
_SIGNED_HEADERS = ("Authorization", "X-Amz-Date", "X-Amz-Security-Token", "Host")


class NeptuneNode(BoltNode):
    """BoltNode variant returning Neptune's string node ID.

    Neptune node IDs are strings (UUIDs when auto-assigned), so the legacy
    integer ``.id`` that :class:`BoltNode` reads carries no meaning here; the
    Bolt ``element_id`` field holds the real ID.
    """

    @property
    def element_id(self) -> str:
        return str(self._raw.element_id)


class NeptuneDialect:
    """Strategy for Amazon Neptune Database-specific Cypher generation.

    Key differences from Neo4j:

    - ``id()`` returns **strings**, not integers — no ``toInteger()`` cast.
    - No ``CALL … YIELD`` for arbitrary procedures.
    - No Cypher-level fulltext search (Neptune integrates with Amazon
      OpenSearch instead) and no vector search (a Neptune Analytics feature).
    - No Cypher function wrappers (``vecf32``, ``point``) — GeoLocation is
      stored as a ``{"latitude": x, "longitude": y}`` map.
    """

    unsupported_features: frozenset[str] = frozenset(
        {
            CypherFeature.PROCEDURE_CALL,
            CypherFeature.FULLTEXT_SEARCH,
            CypherFeature.VECTOR_SEARCH,
        }
    )

    supports_geo_update: bool = False

    def generated_id_where(self, alias: str, param: str) -> str:
        return f"WHERE id({alias}) = ${param}"

    def cypher_fn_for_field(self, fi: FieldInfo) -> str | None:  # noqa: ARG002
        return None

    def fulltext_call(self, label: str, alias: str, query_param: str) -> str:  # noqa: ARG002
        raise NotImplementedError(
            "Neptune does not support Cypher-level fulltext search. "
            "Use the Amazon OpenSearch Service integration instead."
        )

    def vector_knn_start(
        self,
        alias: str,  # noqa: ARG002
        labels_str: str,  # noqa: ARG002
        type_name: str,  # noqa: ARG002
        field_name: str,  # noqa: ARG002
    ) -> str:
        raise NotImplementedError(
            "Neptune Database does not support vector search. "
            "Vector similarity is a Neptune Analytics feature."
        )

    def vector_knn_score_expr(self, alias: str, field_name: str) -> str:  # noqa: ARG002
        raise NotImplementedError(
            "Neptune Database does not support vector search. "
            "Vector similarity is a Neptune Analytics feature."
        )

    def vector_knn_call(
        self,
        alias: str,  # noqa: ARG002
        label: str,  # noqa: ARG002
        field_name: str,  # noqa: ARG002
        k_ref: str,  # noqa: ARG002
        vec_ref: str,  # noqa: ARG002
    ) -> str:
        raise NotImplementedError(
            "Neptune Database does not support vector search. "
            "Vector similarity is a Neptune Analytics feature."
        )

    def vector_score_expr(self) -> str:
        raise NotImplementedError(
            "Neptune Database does not support vector search. "
            "Vector similarity is a Neptune Analytics feature."
        )

    def fulltext_yields_score(self) -> bool:
        return False

    def wrap_node(self, raw: Any) -> NeptuneNode:
        return NeptuneNode(raw)

    def wrap_edge(self, raw: Any) -> BoltEdge:
        return BoltEdge(raw)


_NEPTUNE_DIALECT = NeptuneDialect()


# ---------------------------------------------------------------------------
# IAM (SigV4) authentication
# ---------------------------------------------------------------------------


def _resolve_region(region: str | None) -> str:
    """Return *region* or resolve it from the default botocore config chain."""
    if region:
        return region
    import botocore.session

    resolved = botocore.session.get_session().get_config_variable("region")
    if not resolved:
        raise ValueError(
            "Neptune IAM auth requires an AWS region; pass region=... or "
            "configure one (e.g. AWS_DEFAULT_REGION or ~/.aws/config)."
        )
    return str(resolved)


def _signed_auth_token(
    endpoint_url: str, region: str, credentials: Any | None = None
) -> Any:
    """Build the SigV4-signed ``neo4j.Auth`` token AWS documents for Neptune.

    Signs a dummy ``GET {endpoint_url}/opencypher`` request with the
    ``neptune-db`` service name and JSON-encodes the signed headers as the
    basic-auth credential, exactly as the Neptune Bolt documentation
    prescribes.  *credentials* accepts any botocore credentials object; the
    default resolver chain is used when it is ``None``.
    """
    from botocore.auth import SigV4Auth
    from botocore.awsrequest import AWSRequest
    from neo4j import Auth

    if credentials is None:
        import botocore.session

        credentials = botocore.session.get_session().get_credentials()
    if credentials is None:
        raise RuntimeError(
            "Neptune IAM auth: no AWS credentials found via the default "
            "botocore resolver chain (env vars, shared config, instance role)."
        )
    if hasattr(credentials, "get_frozen_credentials"):
        credentials = credentials.get_frozen_credentials()

    request = AWSRequest(method="GET", url=f"{endpoint_url}/opencypher")
    request.headers.add_header("Host", urlsplit(endpoint_url).netloc)
    SigV4Auth(credentials, _SERVICE_NAME, region).add_auth(request)

    auth_obj: dict[str, str] = {
        header: request.headers[header]
        for header in _SIGNED_HEADERS
        if header in request.headers
    }
    auth_obj["HttpMethod"] = "GET"
    return Auth("basic", "username", json.dumps(auth_obj), "realm")


def _make_auth_manager(
    endpoint_url: str, region: str, credentials: Any | None = None
) -> Any:
    """Return a ``neo4j`` AuthManager that re-signs before the ~5-min expiry."""
    from neo4j.auth_management import AuthManager

    class _NeptuneAuthManager(AuthManager):
        def __init__(self) -> None:
            self._auth: Any = None
            self._issued = 0.0

        def get_auth(self) -> Any:
            if (
                self._auth is None
                or time.monotonic() - self._issued > _TOKEN_TTL_SECONDS
            ):
                self._auth = _signed_auth_token(endpoint_url, region, credentials)
                self._issued = time.monotonic()
            return self._auth

        def handle_security_exception(self, auth: Any, error: Any) -> bool:  # noqa: ARG002
            self._auth = None
            return True

    return _NeptuneAuthManager()


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_neptune_driver(
    endpoint: str,
    port: int = 8182,
    *,
    use_iam_auth: bool = True,
    region: str | None = None,
    credentials: Any | None = None,
) -> BoltDriver:
    """Create a :class:`~runic.ogm.driver.bolt.BoltDriver` for Neptune Database.

    Parameters
    ----------
    endpoint:
        The Neptune cluster (or reader/custom) endpoint host name, e.g.
        ``"my-cluster.cluster-xxxx.eu-central-1.neptune.amazonaws.com"``.
        Neptune is VPC-only — the endpoint must be reachable from where this
        code runs (VPN, bastion, or in-VPC deployment).
    port:
        The DB cluster port (default ``8182``).
    use_iam_auth:
        When ``True`` (default), every new Bolt connection is authenticated
        with an AWS SigV4-signed token via a refreshing AuthManager (requires
        ``botocore`` and resolvable AWS credentials).  Set to ``False`` for
        clusters with IAM database authentication disabled — Neptune then
        ignores the auth parameters entirely.
    region:
        AWS region of the cluster.  Only used with IAM auth; resolved from the
        default AWS config chain when omitted.
    credentials:
        Optional explicit botocore credentials object (e.g. from an assumed
        role).  Only used with IAM auth; defaults to the standard resolver
        chain.

    The connection always uses TLS (``bolt+s://``) — Neptune requires it.
    """
    uri = f"bolt://{endpoint}:{port}"
    auth: Any
    if use_iam_auth:
        resolved_region = _resolve_region(region)
        endpoint_url = f"https://{endpoint}:{port}"
        auth = _make_auth_manager(endpoint_url, resolved_region, credentials)
    else:
        # Neptune ignores Bolt auth when IAM database authentication is off.
        auth = ("username", "password")
    return BoltDriver(uri, auth, None, _NEPTUNE_DIALECT, encrypted=True)
