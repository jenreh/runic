"""The 37 catalogue statements, as builder expressions.

Split from :mod:`tests.runic.ogm.catalog_cases`, which holds the case model and
the registry; this module is the data. See that module's docstring for what a
case records and what the gap identifiers mean.
"""

from __future__ import annotations

from runic.ogm import alias, fulltext_search, select, unwind, vector_search
from runic.ogm.query.expressions import collect, count
from runic.ogm.query.values import left, param, row, score, var, when
from tests.runic.ogm.catalog_cases import ADDRESSED_TYPES, CatalogCase
from tests.runic.ogm.catalog_models import (
    About,
    Account,
    Address,
    CoAddressed,
    Group,
    InstanceOf,
    Message,
    Template,
    Topic,
)

__all__ = ["ALL_CASES"]


# ---------------------------------------------------------------------------
# Shared handles — an Alias is immutable, so statements can share them
# ---------------------------------------------------------------------------

_m = alias(Message, "m")
_node = alias(Message, "node")
_a = alias(Address, "a")
_b = alias(Address, "b")
_r = alias(CoAddressed, "r")
_about = alias(About, "r")


# ---------------------------------------------------------------------------
# Reads — ground truth
# ---------------------------------------------------------------------------

_READS: list[CatalogCase] = [
    CatalogCase(
        name="ACCOUNT_ADDRESSES",
        expect=("MATCH (n:Account)", "n.address IS NOT NULL", "DISTINCT", "AS address"),
        build=lambda: (
            select(Account)
            .where(Account.address.is_not_null())  # ty: ignore[unresolved-attribute]
            .distinct()
            .project(Account.address)
        ),
    ),
    CatalogCase(
        name="MESSAGE_PROPERTIES",
        params=("after", "limit"),
        expect=(
            "MATCH (n:Message)",
            "n.id IS NOT NULL",
            "n.id > $after",
            "AS subject_norm",
            "ORDER BY n.id ASC",
            "LIMIT $limit",
        ),
        build=lambda: (
            select(Message)
            .where(Message.id.is_not_null() & (Message.id > param("after")))  # ty: ignore[unresolved-attribute]
            # id stays projected: the cursor's next $after comes from it.
            .project(Message.id, Message.subject_norm)
            .order_by(Message.id)
            .limit(param("limit"))
        ),
    ),
    CatalogCase(
        name="MESSAGE_RELATIONS",
        params=("limit",),
        expect=(
            "WITH m",
            "ORDER BY m.id ASC",
            "LIMIT $limit",
            "OPTIONAL MATCH (m)-[:SENT_FROM]->",
            "OPTIONAL MATCH (m)-[:SENT_TO|COPIED_TO]->",
            "collect(DISTINCT s.id) AS senders",
        ),
        build=lambda: (
            select(_m)
            # The page is cut before the optional matches, not after — paging
            # written before the traversals compiles into the WITH stage that
            # does exactly that. A trailing LIMIT would pay for the whole
            # archive's expansion to keep one page.
            .order_by(_m.id)
            .limit(param("limit"))
            .traverse(Message.sent_from, from_=_m, to="s", optional=True)
            .traverse(
                Message.sent_to,
                from_=_m,
                types=ADDRESSED_TYPES,
                optional=True,
            )
            .project(
                _m.id,
                collect(alias(Address, "s").id, distinct=True).as_("senders"),
            )
        ),
        unsupported={
            "age": (
                "Apache AGE's openCypher subset has no relationship type "
                "alternation ([:A|B]). Matching the two types as separate "
                "patterns would double-count anything using both, so there is "
                "no faithful rewrite."
            )
        },
    ),
    CatalogCase(
        name="COUNT_UNIDENTIFIED",
        expect=("MATCH (n:Message)", "n.id IS NULL", "count(*) AS total"),
        build=lambda: (
            select(Message)
            .where(Message.id.is_null())  # ty: ignore[unresolved-attribute]
            .project(count("*").as_("total"))
        ),
    ),
    CatalogCase(
        name="COUNT_MESSAGES",
        expect=("MATCH (n:Message)", "n.id IS NOT NULL", "count(*) AS total"),
        build=lambda: (
            select(Message)
            .where(Message.id.is_not_null())  # ty: ignore[unresolved-attribute]
            .project(count("*").as_("total"))
        ),
    ),
    CatalogCase(
        name="MESSAGE_BODIES",
        params=("ids",),
        expect=("MATCH (n:Message)", "n.id IN $ids", "AS body_clean"),
        build=lambda: (
            select(Message)
            .where(Message.id.in_(param("ids")))  # ty: ignore[unresolved-attribute]
            .project(Message.id, Message.body_clean)
        ),
    ),
]

# ---------------------------------------------------------------------------
# Writes — dropping and rebuilding the derived layer
# ---------------------------------------------------------------------------

_DELETES: list[CatalogCase] = [
    CatalogCase(
        name="DELETE_GROUPS",
        params=("batch",),
        expect=("MATCH (n:Group)", "WITH n", "LIMIT $batch", "DETACH DELETE n"),
        build=lambda: select(Group).limit(param("batch")).delete(detach=True),
    ),
    CatalogCase(
        name="DELETE_TOPICS",
        params=("batch",),
        expect=("MATCH (n:Topic)", "WITH n", "LIMIT $batch", "DETACH DELETE n"),
        build=lambda: select(Topic).limit(param("batch")).delete(detach=True),
    ),
    CatalogCase(
        name="DELETE_TEMPLATES",
        params=("batch",),
        expect=("MATCH (n:Template)", "WITH n", "LIMIT $batch", "DETACH DELETE n"),
        build=lambda: select(Template).limit(param("batch")).delete(detach=True),
    ),
    CatalogCase(
        name="DELETE_CO_ADDRESSED",
        params=("batch",),
        # DELETE r, never DETACH DELETE: detaching would take both addresses
        # down and with them every SENT_TO in the archive.
        expect=("[r:CO_ADDRESSED]", "WITH r", "LIMIT $batch", "DELETE r"),
        build=lambda: (
            select(_a)
            .traverse(_a.co_addressed, to=_b, edge=_r, direction="OUTGOING")
            .with_(_r, limit=param("batch"))
            .delete(_r)
        ),
    ),
]

_MERGES: list[CatalogCase] = [
    CatalogCase(
        name="MERGE_GROUPS",
        params=("rows",),
        sample_params={
            "rows": [
                {
                    "id": "g1",
                    "size": 3,
                    "message_count": 7,
                    "first_seen": None,
                    "last_seen": None,
                }
            ]
        },
        expect=("UNWIND $rows AS row", "MERGE (n:Group {id: row.id})", "SET n.size"),
        build=lambda: (
            unwind(param("rows")).merge(Group, key=Group.id, alias="n").set(Group.size)
        ),
    ),
    CatalogCase(
        name="MERGE_ADDRESSED_GROUP",
        params=("rows",),
        sample_params={"rows": [{"message_id": "m1", "group_id": "g1"}]},
        expect=(
            "UNWIND $rows AS row",
            "MATCH (m:Message {id: row.message_id})",
            "MERGE (m)-[:ADDRESSED_GROUP]->",
        ),
        # MATCH and not MERGE on the endpoints: a group that is not there yet
        # is a bug in the caller's ordering, and merging it would paper over
        # that with an empty node instead of writing no edge.
        build=lambda: (
            unwind(param("rows"))
            .match(Message, key={Message.id: row("message_id")}, alias="m")
            .match(Group, key={Group.id: row("group_id")}, alias="g")
            .merge_edge("m", Message.addressed_group, "g")
        ),
    ),
    CatalogCase(
        name="MERGE_CO_ADDRESSED",
        params=("rows",),
        sample_params={
            "rows": [
                {
                    "left": "a1",
                    "right": "a2",
                    "count": 3,
                    "first_seen": None,
                    "last_seen": None,
                }
            ]
        },
        # No arrow, so the same pair handed in either order finds the same edge
        # instead of growing a second one. FalkorDB rejects an undirected MERGE.
        expect=("UNWIND $rows AS row", "MERGE (a)-[r:CO_ADDRESSED]-(b)", "SET r.count"),
        build=lambda: (
            unwind(param("rows"))
            .match(Address, key={Address.id: row("left")}, alias="a")
            .match(Address, key={Address.id: row("right")}, alias="b")
            .merge_edge("a", CoAddressed, "b", alias="r", directed=False)
            .set(CoAddressed.count, on="r")
        ),
        unsupported={
            "falkordb": (
                "FalkorDB only supports directed edges; an undirected MERGE is "
                "rejected. The pair must be canonically ordered by the caller "
                "and merged with an arrow instead."
            ),
            "age": (
                "Apache AGE cannot parse an unquoted property named 'count'; "
                "see TOP_CO_ADDRESSED."
            ),
        },
    ),
    CatalogCase(
        name="MERGE_TOPICS",
        params=("rows",),
        sample_params={
            "rows": [
                {
                    "id": "t1",
                    "label": "billing",
                    "method": "token",
                    "score": 0.9,
                    "message_count": 4,
                    "first_seen": None,
                    "last_seen": None,
                }
            ]
        },
        expect=("UNWIND $rows AS row", "MERGE (n:Topic {id: row.id})", "SET n.label"),
        build=lambda: (
            unwind(param("rows")).merge(Topic, key=Topic.id, alias="n").set(Topic.label)
        ),
    ),
    CatalogCase(
        name="MERGE_ABOUT",
        params=("rows",),
        sample_params={
            "rows": [
                {"message_id": "m1", "topic_id": "t1", "score": 0.7, "method": "token"}
            ]
        },
        expect=("UNWIND $rows AS row", "MERGE (m)-[r:ABOUT]->", "SET r.score"),
        # Score and method are per message, not per topic: a message pulled in
        # by a ticket token and one pulled in by a shared attachment sit in the
        # same cluster and should not claim the same confidence.
        build=lambda: (
            unwind(param("rows"))
            .match(Message, key={Message.id: row("message_id")}, alias="m")
            .match(Topic, key={Topic.id: row("topic_id")}, alias="t")
            .merge_edge("m", About, "t", alias="r")
            .set(About.score, on="r")
        ),
    ),
    CatalogCase(
        name="MERGE_TEMPLATES",
        params=("rows",),
        sample_params={
            "rows": [
                {
                    "id": "tpl1",
                    "sample_text": "Dear customer",
                    "occurrences": 12,
                    "automation_score": 0.8,
                    "direction": "sent",
                    "first_seen": None,
                    "last_seen": None,
                }
            ]
        },
        expect=(
            "UNWIND $rows AS row",
            "MERGE (n:Template {id: row.id})",
            "SET n.sample_text",
        ),
        build=lambda: (
            unwind(param("rows"))
            .merge(Template, key=Template.id, alias="n")
            .set(Template.sample_text)
        ),
    ),
    CatalogCase(
        name="MERGE_INSTANCE_OF",
        params=("rows",),
        sample_params={
            "rows": [{"message_id": "m1", "template_id": "tpl1", "distance": 2}]
        },
        expect=("UNWIND $rows AS row", "MERGE (m)-[r:INSTANCE_OF]->", "SET r.distance"),
        build=lambda: (
            unwind(param("rows"))
            .match(Message, key={Message.id: row("message_id")}, alias="m")
            .match(Template, key={Template.id: row("template_id")}, alias="t")
            .merge_edge("m", InstanceOf, "t", alias="r")
            .set(InstanceOf.distance, on="r")
        ),
    ),
]

# ---------------------------------------------------------------------------
# Reads — the derived layer and its cross-checks
# ---------------------------------------------------------------------------

_ANALYSES: list[CatalogCase] = [
    CatalogCase(
        name="CO_RECIPIENTS",
        params=("limit",),
        expect=(
            "[:SENT_TO|COPIED_TO]",
            "a.id < b.id",
            "count(",
            "ORDER BY together DESC",
            "LIMIT $limit",
        ),
        # The sender is deliberately absent from the pattern: they are the one
        # addressing, not one of the addressed, and including them would make
        # the heaviest pair in every archive "the user, and everyone they mail".
        build=lambda: (
            select(_m)
            .traverse(Message.sent_to, from_=_m, to=_a, types=ADDRESSED_TYPES)
            .traverse(Message.sent_to, from_=_m, to=_b, types=ADDRESSED_TYPES)
            # Makes an unordered pair appear once instead of twice.
            .where(_a.id < _b.id)
            .project(
                _a.id.as_("left_id"),
                _b.id.as_("right_id"),
                count("*").as_("together"),
            )
            .order_by(count("*").as_("together"), desc=True)
            .limit(param("limit"))
        ),
        unsupported={
            "age": (
                "Apache AGE's openCypher subset has no relationship type "
                "alternation ([:A|B]). Matching the two types as separate "
                "patterns would double-count anything using both, so there is "
                "no faithful rewrite."
            )
        },
    ),
    CatalogCase(
        name="TOP_CO_ADDRESSED",
        params=("limit",),
        # Undirected read: which way the edge was stored is an accident, so
        # the load-bearing detail is the absent arrow, not the single pattern —
        # runic emits the root MATCH separately, which matches the same rows.
        expect=(
            "-[r:CO_ADDRESSED]-(b:Address)",
            "a.id < b.id",
            "r.count IS NOT NULL",
            "LIMIT $limit",
        ),
        build=lambda: (
            select(_a)
            .traverse(_a.co_addressed, to=_b, edge=_r)
            .where(_a.id < _b.id)
            .where(_r.count.is_not_null())
            .project(_a.id.as_("left_id"), _b.id.as_("right_id"))
            .limit(param("limit"))
        ),
        unsupported={
            "age": (
                "Apache AGE cannot parse an unquoted property named 'count' — "
                "its parser reads it as the aggregate function. Verified: "
                "r.count fails, r.`count` succeeds, and the same holds for node "
                "properties. runic does not yet escape property names in "
                "emitted Cypher; tracked separately."
            )
        },
    ),
    CatalogCase(
        name="RECURRING_GROUPS",
        params=("min_size", "min_messages", "limit"),
        expect=(
            "MATCH (n:Group)",
            "n.size >= $min_size",
            "n.message_count >= $min_messages",
            "LIMIT $limit",
        ),
        build=lambda: (
            select(Group)
            .where(
                (Group.size >= param("min_size"))
                & (Group.message_count >= param("min_messages"))
            )
            .limit(param("limit"))
        ),
    ),
    CatalogCase(
        name="TOP_TEMPLATES",
        params=("direction", "limit"),
        expect=(
            "MATCH (n:Template)",
            "n.direction = $direction",
            "ORDER BY automation_score DESC",
            "LIMIT $limit",
        ),
        build=lambda: (
            select(Template)
            .where(Template.direction == param("direction"))  # ty: ignore[invalid-argument-type]
            .project(Template.automation_score)
            .order_by("automation_score", desc=True)
            .limit(param("limit"))
        ),
    ),
    CatalogCase(
        name="TOPIC_BREAKDOWN",
        params=("limit",),
        expect=("[r:ABOUT]->", "AS method", "count(", "LIMIT $limit"),
        build=lambda: (
            select(_m)
            .traverse(Message.about, edge=_about)
            .project(_about.method, count("*").as_("messages"))
            .limit(param("limit"))
        ),
    ),
    CatalogCase(
        name="COUNT_GROUPS",
        expect=("MATCH (n:Group)", "count(*) AS total"),
        build=lambda: select(Group).project(count("*").as_("total")),
    ),
    CatalogCase(
        name="COUNT_TOPICS",
        expect=("MATCH (n:Topic)", "count(*) AS total"),
        build=lambda: select(Topic).project(count("*").as_("total")),
    ),
    CatalogCase(
        name="COUNT_TEMPLATES",
        expect=("MATCH (n:Template)", "count(*) AS total"),
        build=lambda: select(Template).project(count("*").as_("total")),
    ),
    CatalogCase(
        name="COUNT_CO_ADDRESSED",
        # Directed although the edge is undirected in meaning: both ends carry
        # the same label, so an arrow costs no matches and saves counting each
        # edge twice.
        expect=("[r:CO_ADDRESSED]->", "count(r) AS total"),
        build=lambda: (
            select(Address)
            .traverse(Address.co_addressed, edge=_r, direction="OUTGOING")
            .project(count("r").as_("total"))
        ),
    ),
]

# ---------------------------------------------------------------------------
# The semantic phase — embeddings, KNN, fulltext, index DDL
# ---------------------------------------------------------------------------

_SEMANTIC: list[CatalogCase] = [
    CatalogCase(
        name="COUNT_NEEDING_EMBEDDING",
        params=("model",),
        expect=(
            "MATCH (n:Message)",
            "n.body_clean IS NOT NULL",
            "n.embedding_model <> $model",
            "count(*) AS total",
        ),
        build=lambda: (
            select(Message)
            .where(
                Message.body_clean.is_not_null()  # ty: ignore[unresolved-attribute]
                & (Message.embedding_model != param("model"))
            )
            .project(count("*").as_("total"))
        ),
    ),
    CatalogCase(
        name="MESSAGES_NEEDING_EMBEDDING",
        params=("after", "model", "max_chars", "limit"),
        expect=(
            "n.id > $after",
            "n.embedding_model <> $model",
            "left(n.body_clean, $max_chars) AS body",
            "LIMIT $limit",
        ),
        build=lambda: (
            select(Message)
            .where(
                (Message.id > param("after"))  # ty: ignore[unsupported-operator]
                & (Message.embedding_model != param("model"))
            )
            .project(
                Message.id,
                left(Message.body_clean, param("max_chars")).as_("body"),
            )
            .limit(param("limit"))
        ),
    ),
    CatalogCase(
        name="WRITE_EMBEDDINGS",
        params=("rows",),
        sample_params={"rows": [{"id": "m1", "vector": [0.1, 0.2, 0.3, 0.4]}]},
        expect=(
            "UNWIND $rows AS row",
            "MATCH (m:Message {id: row.id})",
            "SET m.embedding = vecf32(row.vector)",
            "count(m) AS written",
        ),
        # MATCH and never MERGE: a row naming a message that is not there is a
        # bug in the caller, and merging it would invent an empty Message
        # carrying nothing but a vector.
        build=lambda: (
            unwind(param("rows"))
            .match(Message, key=Message.id, alias="m")
            .set({Message.embedding: row("vector")}, on="m")
            .returning(count("m").as_("written"))
        ),
    ),
    CatalogCase(
        name="SEMANTIC_NEIGHBOURS",
        # $k is how wide the index search goes; $limit is what the caller sees.
        # The procedure cannot be narrowed before the fact, so every row a
        # filter drops has to be paid for up front by $k. Asking for k == limit
        # and then filtering leaves a short page that looks like a small
        # archive.
        params=("k", "vector", "model", "limit"),
        expect=(
            "db.idx.vector.queryNodes",
            "$k",
            "YIELD node",
            "node.embedding_model = $model",
            "OPTIONAL MATCH (node)-[:SENT_FROM]->",
            "LIMIT $limit",
        ),
        build=lambda: (
            vector_search(_node.embedding, vector=param("vector"), k=param("k"))
            .where(_node.embedding_model == param("model"))
            .traverse(Message.sent_from, optional=True)
            .project(_node.id)
            .limit(param("limit"))
        ),
        unsupported={
            "age": (
                "Apache AGE has no Cypher-reachable vector or fulltext index; "
                "use pgvector and PostgreSQL full-text search on the underlying "
                "tables instead."
            ),
            "arcadedb": ("ArcadeDB exposes no fulltext search through Cypher."),
            "memgraph": (
                "Memgraph's vector index keeps references to deleted nodes, so "
                "the search raises 'property from a deleted object' on a "
                "database other tests have written to. A fixture isolation "
                "limitation rather than a defect in the statement."
            ),
            "neptune": (
                "Neptune Database has no vector search — vector similarity is "
                "a Neptune Analytics feature."
            ),
        },
    ),
    CatalogCase(
        name="SEMANTIC_TOPIC_PAIRS",
        params=("k", "max_distance"),
        expect=(
            "MATCH (m:Message)",
            "db.idx.vector.queryNodes",
            "m.embedding",
            "node.id > m.id",
            "score <= $max_distance",
        ),
        # The whole archive's neighbours in ONE round trip, which is the
        # difference between this signal being usable and a per-message KNN
        # over a hundred thousand messages.
        #
        # node.id > m.id does two jobs with one predicate: the KNN returns the
        # query node itself first for every message, and it is symmetric, so an
        # unordered comparison would yield one self-pair plus one duplicate per
        # edge.
        build=lambda: (
            select(_m)
            # Load-bearing, not decoration: a message without a vector reaches
            # the procedure as a NULL argument, which the backend rejects.
            .where(_m.embedding.is_not_null())
            .call(
                "db.idx.vector.queryNodes",
                "Message",
                "embedding",
                param("k"),
                _m.embedding,
                yields=["node", "score"],
            )
            .with_(_m, _node, var("score"))
            .where((_node.id > _m.id) & (var("score") <= param("max_distance")))
            .project(_m.id.as_("left"), _node.id.as_("right"))
        ),
        unsupported={
            "neo4j": (
                "call() names a procedure literally, so a statement using one "
                "is exactly as portable as that procedure. Neo4j's is "
                "db.index.vector.queryNodes with a different argument order. "
                "For a portable KNN use vector_search(), which asks the "
                "dialect; call() is the escape hatch for when you need a "
                "specific backend's procedure, as a correlated KNN does."
            ),
            "memgraph": (
                "Memgraph's vector procedure is vector_search.search, with a "
                "different name and signature; see the neo4j note."
            ),
            "arcadedb": "ArcadeDB has no CALL … YIELD for arbitrary procedures.",
            "age": "Apache AGE has no CALL … YIELD for arbitrary procedures.",
            "neptune": (
                "Neptune Database has no CALL … YIELD for arbitrary procedures."
            ),
            "neptune_analytics": (
                "Neptune Analytics only exposes its built-in neptune.algo.* "
                "procedures; FalkorDB's db.idx.vector.queryNodes does not "
                "exist there. See the neo4j note."
            ),
        },
    ),
    CatalogCase(
        name="FULLTEXT_MESSAGES",
        params=("text", "limit"),
        expect=(
            "db.idx.fulltext.queryNodes",
            "$text",
            "AS relevance",
            "ORDER BY relevance DESC",
            "LIMIT $limit",
        ),
        # score is a relevance here — higher is better, the opposite of a
        # vector distance. The two must never be sorted into one list without
        # a stated normalisation.
        build=lambda: (
            fulltext_search(_node, query=param("text"))
            .project(score().as_("relevance"))
            .order_by("relevance", desc=True)
            .limit(param("limit"))
        ),
        unsupported={
            "age": (
                "Apache AGE has no Cypher-reachable vector or fulltext index; "
                "use pgvector and PostgreSQL full-text search on the underlying "
                "tables instead."
            ),
            "arcadedb": ("ArcadeDB exposes no fulltext search through Cypher."),
            "neptune": (
                "Neptune has no Cypher-level fulltext search; fulltext goes "
                "through the Amazon OpenSearch integration."
            ),
            "neptune_analytics": (
                "Neptune Analytics has no Cypher-level fulltext search."
            ),
        },
    ),
    CatalogCase(
        name="VECTOR_COVERAGE",
        params=("model",),
        expect=(
            "count(*) AS total",
            # The THEN value is bound rather than inlined, which is why this
            # asserts the branch and not a literal 1.
            "CASE WHEN n.embedding_model = $model THEN",
            "AS embedded",
            "AS unembeddable",
        ),
        build=lambda: select(Message).project(
            count("*").as_("total"),
            count(when(Message.embedding_model == param("model"), 1)).as_(  # ty: ignore[invalid-argument-type]
                "embedded"
            ),
            count(
                when(Message.body_clean.is_null(), 1)  # ty: ignore[unresolved-attribute]
            ).as_("unembeddable"),
        ),
    ),
    CatalogCase(
        name="CLEAR_EMBEDDINGS",
        expect=(
            "MATCH (n:Message)",
            "SET n.embedding = NULL",
            "count(n) AS cleared",
        ),
        # Ground truth is untouched: these two properties are the semantic
        # phase's own, declared on the node and left empty by the import.
        build=lambda: (
            select(Message)
            .set({Message.embedding: None})
            .returning(count("n").as_("cleared"))
        ),
    ),
    CatalogCase(
        name="CREATE_VECTOR_INDEX",
        params=("dimension", "similarity", "m", "ef_construction", "ef_runtime"),
        expect=("CREATE VECTOR INDEX", "Message", "embedding", "$dimension"),
        # Not a statement and never will be: DDL is not a query. The dimension
        # follows whichever embedder a person configured, which is a setting and
        # not something a migration chain can express.
        operation=lambda ops: ops.create_vector_index(
            Message, Message.embedding, dimension=4
        ),
    ),
    CatalogCase(
        name="DROP_VECTOR_INDEX",
        expect=("DROP VECTOR INDEX", "Message", "embedding"),
        operation=lambda ops: ops.drop_vector_index(Message, Message.embedding),
    ),
    CatalogCase(
        name="VECTOR_INDEX_OPTIONS",
        expect=("DB.INDEXES()", "options"),
        # The one statement that reads schema rather than data. A backend
        # accepts a vector of the wrong length, stores it and never indexes it,
        # so the live dimension is a thing a job has to be able to read.
        operation=lambda ops: ops.describe(),
    ),
]

ALL_CASES: tuple[CatalogCase, ...] = (
    *_READS,
    *_DELETES,
    *_MERGES,
    *_ANALYSES,
    *_SEMANTIC,
)
"""Every statement, in the order the source catalogue declares them."""
