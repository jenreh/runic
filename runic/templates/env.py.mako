import os

from runic.adapters import create_adapter
from runic import context

# ---------------------------------------------------------------------------
# Connection
# Override via environment variables or edit the defaults below.
#
# FALKORDB_URL   — connection string, e.g. falkor://user:pass@host:6379
# FALKORDB_GRAPH — graph name in FalkorDB
# ---------------------------------------------------------------------------
adapter = create_adapter(
    "falkordb",
    url=os.getenv("FALKORDB_URL", "falkor://localhost:6379"),
    graph_name=os.getenv("FALKORDB_GRAPH", "my_graph"),
)

# ---------------------------------------------------------------------------
# Optional: target schema manifest
# Required for `runic check` and `runic revision --autogenerate`.
# Declare the desired end-state; runic diffs it against the live schema.
# ---------------------------------------------------------------------------
# from runic.manifest import (
#     FulltextIndex,
#     MandatoryConstraint,
#     RangeIndex,
#     SchemaManifest,
#     UniqueConstraint,
#     VectorIndex,
# )
#
# target_manifest = SchemaManifest(
#     range_indexes=[
#         RangeIndex(label="User", prop="email"),
#         RangeIndex(label="FOLLOWS", prop="since", rel=True),
#     ],
#     fulltext_indexes=[
#         FulltextIndex(label="Post", props=["title", "body"]),
#     ],
#     vector_indexes=[
#         VectorIndex(label="Document", prop="vec", dimension=1536, similarity="cosine"),
#     ],
#     constraints=[
#         UniqueConstraint(entity="NODE", label="User", props=["email"]),
#         MandatoryConstraint(entity="NODE", label="User", props=["created_at"]),
#     ],
# )

context.configure(
    adapter,

    # enable schema drift detection
    # target_manifest=target_manifest,

    # set False to disable checksum recording/validation
    track_checksums=True,

    # When track_installed_by=True, attribution resolution order:
    #   RUNIC_INSTALLED_BY env var → OS user
    #   --installed-by still overrides when False
    track_installed_by=False,
)
