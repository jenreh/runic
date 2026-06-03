import os

from runic.adapters import create_adapter
from runic import context

# ---------------------------------------------------------------------------
# Connection — two variants, pick one.
#
# Variant A: URL  (embed credentials directly in the connection string)
#   No auth:             falkor://localhost:6379
#   Password only:       falkor://:mypassword@localhost:6379
#   User + password:     falkor://myuser:mypassword@localhost:6379
#
# Variant B: explicit host / port / credentials
# ---------------------------------------------------------------------------

# Variant A — URL (active by default)
adapter = create_adapter(
    "falkordb",
    url=os.getenv("FALKORDB_URL", "falkor://localhost:6379"),
    graph_name=os.getenv("FALKORDB_GRAPH", "my_graph"),
)

# Variant B — explicit params (comment out Variant A above and uncomment this)
# adapter = create_adapter(
#     "falkordb",
#     host=os.getenv("FALKORDB_HOST", "localhost"),
#     port=int(os.getenv("FALKORDB_PORT", "6379")),
#     username=os.getenv("FALKORDB_USERNAME") or None,
#     password=os.getenv("FALKORDB_PASSWORD") or None,
#     graph_name=os.getenv("FALKORDB_GRAPH", "my_graph"),
# )

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

# max length of characters to apply to the "slug" field (default: 40)
# truncate_slug_length = 40

# template used to generate migration file names (default: "%(rev)s_%(slug)s")
# available tokens: rev, slug, year, month, day, hour, minute
# date-prefixed example:
# file_template = "%(year).4d_%(month).2d_%(day).2d_%(hour).2d%(minute).2d-%(rev)s_%(slug)s"

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
