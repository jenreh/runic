"""The 37 catalogue statements, as builder expressions.

Split from :mod:`tests.runic.ogm.catalog_cases`, which holds the case model and
the registry; this module is the data. See that module's docstring for what a
case records and what the gap identifiers mean.
"""

from __future__ import annotations

from runic.ogm import select, unwind
from runic.ogm.query.expressions import collect, count
from runic.ogm.query.specialised import FulltextQueryBuilder, VectorQueryBuilder
from runic.ogm.query.values import col, left, param, row, score, var, when
from tests.runic.ogm.catalog_cases import ADDRESSED_TYPES, CatalogCase
from tests.runic.ogm.catalog_models import (
    About,
    Account,
    Address,
    Attachment,
    CoAddressed,
    Group,
    InstanceOf,
    Message,
    Template,
    Thread,
    Topic,
)

__all__ = ["ALL_CASES"]


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
            .project(col(Account.address).as_("address"))  # ty: ignore[invalid-argument-type]
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
            .project(
                col(Message.id).as_("id"),  # ty: ignore[invalid-argument-type]
                col(Message.sent_at).as_("sent_at"),  # ty: ignore[invalid-argument-type]
                col(Message.subject_norm).as_("subject_norm"),  # ty: ignore[invalid-argument-type]
                col(Message.participant_key).as_("participant_key"),  # ty: ignore[invalid-argument-type]
                col(Message.simhash).as_("simhash"),  # ty: ignore[invalid-argument-type]
                col(Message.refs).as_("refs"),  # ty: ignore[invalid-argument-type]
            )
            .order_by(Message.id)
            .limit(param("limit"))
        ),
    ),
    CatalogCase(
        name="MESSAGE_RELATIONS",
        params=("after", "limit"),
        expect=(
            "WITH m",
            "ORDER BY m.id ASC",
            "LIMIT $limit",
            "OPTIONAL MATCH (m)-[:SENT_FROM]->",
            "OPTIONAL MATCH (m)-[:SENT_TO|COPIED_TO]->",
            "collect(DISTINCT s.id) AS senders",
        ),
        build=lambda: (
            select(Message)
            .alias("m")
            .where(Message.id.is_not_null() & (Message.id > param("after")))  # ty: ignore[unresolved-attribute]
            # The page is cut before the optional matches, not after: five
            # expansions that cross-multiply are the expensive half, and a trailing
            # LIMIT would pay for the whole archive's expansion to keep one page.
            .with_("m", order_by=Message.id, limit=param("limit"))
            .traverse(Message.sent_from, from_="m")  # ty: ignore[invalid-argument-type]
            .alias("s")
            .traverse(Message.sent_to, from_="m", types=ADDRESSED_TYPES)  # ty: ignore[invalid-argument-type]
            .alias("r")
            .traverse(Message.blind_copied_to, from_="m")  # ty: ignore[invalid-argument-type]
            .alias("b")
            .traverse(Message.in_thread, from_="m")  # ty: ignore[invalid-argument-type]
            .alias("t")
            .traverse(Message.has_attachment, from_="m")  # ty: ignore[invalid-argument-type]
            .alias("f")
            .aggregate(
                collect(col("s", Address.id), distinct=True).as_("senders"),  # ty: ignore[no-matching-overload]
                collect(col("r", Address.id), distinct=True).as_("addressed"),  # ty: ignore[no-matching-overload]
                collect(col("b", Address.id), distinct=True).as_("blind_copied"),  # ty: ignore[no-matching-overload]
                collect(col("t", Thread.id), distinct=True).as_("threads"),  # ty: ignore[no-matching-overload]
                collect(col("f", Attachment.id), distinct=True).as_("attachments"),  # ty: ignore[no-matching-overload]
                group_by=col("m", Message.id).as_("id"),  # ty: ignore[no-matching-overload]
            )
            .order_by("id")
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
            .where(Message.id.is_null() | (Message.id == ""))  # ty: ignore[unresolved-attribute]
            .aggregate(count("*").as_("total"))
        ),
    ),
    CatalogCase(
        name="COUNT_MESSAGES",
        expect=("MATCH (n:Message)", "n.id IS NOT NULL", "count(*) AS total"),
        build=lambda: (
            select(Message)
            .where(Message.id.is_not_null() & (Message.id != ""))  # ty: ignore[unresolved-attribute]
            .aggregate(count("*").as_("total"))
        ),
    ),
    CatalogCase(
        name="MESSAGE_BODIES",
        params=("ids",),
        expect=("MATCH (n:Message)", "n.id IN $ids", "AS body_clean"),
        build=lambda: (
            select(Message)
            .where(Message.id.in_(param("ids")))  # ty: ignore[unresolved-attribute]
            .project(
                col(Message.id).as_("id"),  # ty: ignore[invalid-argument-type]
                col(Message.body_clean).as_("body_clean"),  # ty: ignore[invalid-argument-type]
            )
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
        build=lambda: (
            select(Group)
            .with_("n", limit=param("batch"))
            .delete(detach=True)
            .returning(count("n").as_("removed"))
        ),
    ),
    CatalogCase(
        name="DELETE_TOPICS",
        params=("batch",),
        expect=("MATCH (n:Topic)", "WITH n", "LIMIT $batch", "DETACH DELETE n"),
        build=lambda: (
            select(Topic)
            .with_("n", limit=param("batch"))
            .delete(detach=True)
            .returning(count("n").as_("removed"))
        ),
    ),
    CatalogCase(
        name="DELETE_TEMPLATES",
        params=("batch",),
        expect=("MATCH (n:Template)", "WITH n", "LIMIT $batch", "DETACH DELETE n"),
        build=lambda: (
            select(Template)
            .with_("n", limit=param("batch"))
            .delete(detach=True)
            .returning(count("n").as_("removed"))
        ),
    ),
    CatalogCase(
        name="DELETE_CO_ADDRESSED",
        params=("batch",),
        # DELETE r, never DETACH DELETE: detaching would take both addresses.
        expect=("[r:CO_ADDRESSED]", "WITH r", "LIMIT $batch", "DELETE r"),
        # DELETE r, never DETACH DELETE: detaching would take both addresses
        # down and with them every SENT_TO in the archive.
        build=lambda: (
            select(Address)
            .alias("a")
            .traverse(
                Address.co_addressed,  # ty: ignore[invalid-argument-type]
                edge_alias="r",
                optional=False,
                direction="OUTGOING",
            )
            .alias("b")
            .with_("r", limit=param("batch"))
            .delete("r")
            .returning(count("r").as_("removed"))
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
            unwind(param("rows"))
            .merge(Group, key={Group.id: row("id")}, alias="n")
            .set(
                {
                    Group.size: row("size"),
                    Group.message_count: row("message_count"),
                    Group.first_seen: row("first_seen"),
                    Group.last_seen: row("last_seen"),
                },
                on="n",
            )
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
            .merge_edge("m", "ADDRESSED_GROUP", "g")
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
        # No arrow: the same pair in either order must find the same edge.
        expect=("UNWIND $rows AS row", "MERGE (a)-[r:CO_ADDRESSED]-(b)", "SET r.count"),
        # No arrow, so the same pair handed in either order finds the same edge
        # instead of growing a second one. FalkorDB rejects an undirected MERGE.
        build=lambda: (
            unwind(param("rows"))
            .match(Address, key={Address.id: row("left")}, alias="a")
            .match(Address, key={Address.id: row("right")}, alias="b")
            .merge_edge(
                "a",
                "CO_ADDRESSED",
                "b",
                alias="r",
                edge_model=CoAddressed,
                directed=False,
            )
            .set(
                {
                    CoAddressed.count: row("count"),
                    CoAddressed.first_seen: row("first_seen"),
                    CoAddressed.last_seen: row("last_seen"),
                },
                on="r",
            )
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
            unwind(param("rows"))
            .merge(Topic, key={Topic.id: row("id")}, alias="n")
            .set(
                {
                    Topic.label: row("label"),
                    Topic.method: row("method"),
                    Topic.score: row("score"),
                    Topic.message_count: row("message_count"),
                    Topic.first_seen: row("first_seen"),
                    Topic.last_seen: row("last_seen"),
                },
                on="n",
            )
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
            .merge_edge("m", "ABOUT", "t", alias="r", edge_model=About)
            .set({About.score: row("score"), About.method: row("method")}, on="r")
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
            .merge(Template, key={Template.id: row("id")}, alias="n")
            .set(
                {
                    Template.sample_text: row("sample_text"),
                    Template.occurrences: row("occurrences"),
                    Template.automation_score: row("automation_score"),
                    Template.direction: row("direction"),
                    Template.first_seen: row("first_seen"),
                    Template.last_seen: row("last_seen"),
                },
                on="n",
            )
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
            .merge_edge("m", "INSTANCE_OF", "t", alias="r", edge_model=InstanceOf)
            .set({InstanceOf.distance: row("distance")}, on="r")
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
            select(Message)
            .alias("m")
            .where(Message.id.is_not_null() & (Message.id != ""))  # ty: ignore[unresolved-attribute]
            .traverse(Message.sent_to, from_="m", types=ADDRESSED_TYPES, optional=False)  # ty: ignore[invalid-argument-type]
            .alias("a")
            .traverse(Message.sent_to, from_="m", types=ADDRESSED_TYPES, optional=False)  # ty: ignore[invalid-argument-type]
            .alias("b")
            # Makes an unordered pair appear once instead of twice.
            .where(col("a", Address.id) < col("b", Address.id))  # ty: ignore[no-matching-overload]
            .aggregate(
                count("*").as_("together"),
                group_by=[
                    col("a", Address.id).as_("left_id"),  # ty: ignore[no-matching-overload]
                    col("b", Address.id).as_("right_id"),  # ty: ignore[no-matching-overload]
                ],
            )
            .order_by("together", desc=True)
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
            select(Address)
            .alias("a")
            .traverse(Address.co_addressed, edge_alias="r", optional=False)  # ty: ignore[invalid-argument-type]
            .alias("b")
            .where(col("a", Address.id) < col("b", Address.id))  # ty: ignore[no-matching-overload]
            .where(CoAddressed.count.is_not_null(), on="r")  # ty: ignore[unresolved-attribute]
            .project(
                col("a", Address.id).as_("left_id"),  # ty: ignore[no-matching-overload]
                col("b", Address.id).as_("right_id"),  # ty: ignore[no-matching-overload]
                col("r", CoAddressed.count).as_("together"),  # ty: ignore[no-matching-overload]
                col("r", CoAddressed.first_seen).as_("first_seen"),  # ty: ignore[no-matching-overload]
                col("r", CoAddressed.last_seen).as_("last_seen"),  # ty: ignore[no-matching-overload]
            )
            .order_by("together", desc=True)
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
            .project(
                col(Group.id).as_("id"),  # ty: ignore[invalid-argument-type]
                col(Group.size).as_("size"),  # ty: ignore[invalid-argument-type]
                col(Group.message_count).as_("message_count"),  # ty: ignore[invalid-argument-type]
                col(Group.first_seen).as_("first_seen"),  # ty: ignore[invalid-argument-type]
                col(Group.last_seen).as_("last_seen"),  # ty: ignore[invalid-argument-type]
            )
            .order_by("message_count", desc=True)
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
            .project(
                col(Template.id).as_("id"),  # ty: ignore[invalid-argument-type]
                col(Template.occurrences).as_("occurrences"),  # ty: ignore[invalid-argument-type]
                col(Template.automation_score).as_("automation_score"),  # ty: ignore[invalid-argument-type]
                col(Template.sample_text).as_("sample_text"),  # ty: ignore[invalid-argument-type]
            )
            .order_by("automation_score", desc=True)
            .limit(param("limit"))
        ),
    ),
    CatalogCase(
        name="TOPIC_BREAKDOWN",
        params=("limit",),
        expect=("[r:ABOUT]->", "AS method", "count(", "LIMIT $limit"),
        build=lambda: (
            select(Message)
            .alias("m")
            .traverse(Message.about, edge_alias="r", optional=False)  # ty: ignore[invalid-argument-type]
            .alias("t")
            .aggregate(
                count("*").as_("messages"),
                group_by=[
                    col("t", Topic.id).as_("id"),  # ty: ignore[no-matching-overload]
                    col("t", Topic.label).as_("label"),  # ty: ignore[no-matching-overload]
                    col("r", About.method).as_("method"),  # ty: ignore[no-matching-overload]
                ],
            )
            .order_by("messages", desc=True)
            .limit(param("limit"))
        ),
    ),
    CatalogCase(
        name="COUNT_GROUPS",
        expect=("MATCH (n:Group)", "count(*) AS total"),
        build=lambda: select(Group).aggregate(count("*").as_("total")),
    ),
    CatalogCase(
        name="COUNT_TOPICS",
        expect=("MATCH (n:Topic)", "count(*) AS total"),
        build=lambda: select(Topic).aggregate(count("*").as_("total")),
    ),
    CatalogCase(
        name="COUNT_TEMPLATES",
        expect=("MATCH (n:Template)", "count(*) AS total"),
        build=lambda: select(Template).aggregate(count("*").as_("total")),
    ),
    CatalogCase(
        name="COUNT_CO_ADDRESSED",
        # Directed on purpose: both ends are addresses, so an arrow costs no
        # matches and saves counting every edge twice.
        expect=("[r:CO_ADDRESSED]->", "count(r) AS total"),
        # Directed although the edge is undirected in meaning: both ends carry
        # the same label, so an arrow costs no matches and saves counting each
        # edge twice.
        build=lambda: (
            select(Address)
            .alias("a")
            .traverse(
                Address.co_addressed,  # ty: ignore[invalid-argument-type]
                edge_alias="r",
                optional=False,
                direction="OUTGOING",
            )
            .alias("b")
            .aggregate(count("r").as_("total"))
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
                Message.id.is_not_null()  # ty: ignore[unresolved-attribute]
                & (Message.id != "")
                & Message.body_clean.is_not_null()  # ty: ignore[unresolved-attribute]
                & (Message.body_clean != "")
                & (
                    Message.embedding.is_null()  # ty: ignore[unresolved-attribute]
                    | Message.embedding_model.is_null()  # ty: ignore[unresolved-attribute]
                    | (Message.embedding_model != param("model"))
                )
            )
            .aggregate(count("*").as_("total"))
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
                Message.id.is_not_null()  # ty: ignore[unresolved-attribute]
                & (Message.id > param("after"))
                & Message.body_clean.is_not_null()  # ty: ignore[unresolved-attribute]
                & (Message.body_clean != "")
                & (
                    Message.embedding.is_null()  # ty: ignore[unresolved-attribute]
                    | Message.embedding_model.is_null()  # ty: ignore[unresolved-attribute]
                    | (Message.embedding_model != param("model"))
                )
            )
            .project(
                col(Message.id).as_("id"),  # ty: ignore[invalid-argument-type]
                col(Message.subject).as_("subject"),  # ty: ignore[invalid-argument-type]
                left(col(Message.body_clean), param("max_chars")).as_("body"),  # ty: ignore[invalid-argument-type]
            )
            .order_by(Message.id)
            .limit(param("limit"))
        ),
    ),
    CatalogCase(
        name="WRITE_EMBEDDINGS",
        params=("rows", "model"),
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
            .match(Message, key={Message.id: row("id")}, alias="m")
            .set(
                {
                    Message.embedding: row("vector"),
                    Message.embedding_model: param("model"),
                },
                on="m",
            )
            .returning(count("m").as_("written"))
        ),
    ),
    CatalogCase(
        name="SEMANTIC_NEIGHBOURS",
        # $k is how wide the index search goes; $limit is what the caller sees.
        params=("k", "vector", "model", "limit"),
        expect=(
            "db.idx.vector.queryNodes",
            "$k",
            "YIELD node",
            "node.embedding_model = $model",
            "OPTIONAL MATCH (node)-[:SENT_FROM]->",
            "LIMIT $limit",
        ),
        # $k is how wide the index search goes; $limit is what the caller sees.
        # The procedure cannot be narrowed before the fact, so every row a
        # filter drops has to be paid for up front by $k. Asking for k == limit
        # and then filtering leaves a short page that looks like a small
        # archive.
        build=lambda: (
            VectorQueryBuilder(
                None,
                Message,
                field=Message.embedding,  # ty: ignore[invalid-argument-type]
                vector=param("vector"),
                k=param("k"),
            )
            .alias("node")
            .where(
                Message.id.is_not_null()  # ty: ignore[unresolved-attribute]
                & (Message.id != "")
                & (Message.embedding_model == param("model"))
            )
            .traverse(Message.sent_from, from_="node")  # ty: ignore[invalid-argument-type]
            .alias("s")
            .project(
                col("node", Message.id).as_("id"),  # ty: ignore[no-matching-overload]
                col("node", Message.subject).as_("subject"),  # ty: ignore[no-matching-overload]
                col("node", Message.sent_at).as_("sent_at"),  # ty: ignore[no-matching-overload]
                col("s", Address.id).as_("sender"),  # ty: ignore[no-matching-overload]
                score().as_("distance"),
            )
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
        },
    ),
    CatalogCase(
        name="SEMANTIC_TOPIC_PAIRS",
        params=("model", "k", "max_distance", "limit"),
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
            select(Message)
            .alias("m")
            .where(
                Message.id.is_not_null()  # ty: ignore[unresolved-attribute]
                & (Message.id != "")
                & (Message.embedding_model == param("model"))
            )
            .call(
                "db.idx.vector.queryNodes",
                "Message",
                "embedding",
                param("k"),
                col("m", Message.embedding),  # ty: ignore[no-matching-overload]
                yields=["node", "score"],
            )
            .with_("m", "node", "score")
            .where(
                (col("node", Message.id) > col("m", Message.id))  # ty: ignore[no-matching-overload]
                & (col("node", Message.embedding_model) == param("model"))  # ty: ignore[no-matching-overload]
                & (var("score") <= param("max_distance"))
            )
            .project(
                col("m", Message.id).as_("left"),  # ty: ignore[no-matching-overload]
                col("node", Message.id).as_("right"),  # ty: ignore[no-matching-overload]
                var("score").as_("distance"),
            )
            .order_by("distance")
            .limit(param("limit"))
        ),
        unsupported={
            "neo4j": (
                "call() names a procedure literally, so a statement using one "
                "is exactly as portable as that procedure. Neo4j's is "
                "db.index.vector.queryNodes with a different argument order. "
                "For a portable KNN use session.vector_search(), which asks the "
                "dialect; call() is the escape hatch for when you need a "
                "specific backend's procedure, as a correlated KNN does."
            ),
            "memgraph": (
                "Memgraph's vector procedure is vector_search.search, with a "
                "different name and signature; see the neo4j note."
            ),
            "arcadedb": "ArcadeDB has no CALL … YIELD for arbitrary procedures.",
            "age": "Apache AGE has no CALL … YIELD for arbitrary procedures.",
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
            FulltextQueryBuilder(None, Message, query=param("text"))
            .alias("node")
            .where(Message.id.is_not_null() & (Message.id != ""))  # ty: ignore[unresolved-attribute]
            .traverse(Message.sent_from, from_="node")  # ty: ignore[invalid-argument-type]
            .alias("s")
            .project(
                col("node", Message.id).as_("id"),  # ty: ignore[no-matching-overload]
                col("node", Message.subject).as_("subject"),  # ty: ignore[no-matching-overload]
                col("s", Address.id).as_("sender"),  # ty: ignore[no-matching-overload]
                score().as_("relevance"),
            )
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
        build=lambda: (
            select(Message)
            .where(Message.id.is_not_null() & (Message.id != ""))  # ty: ignore[unresolved-attribute]
            .aggregate(
                count("*").as_("total"),
                count(when(Message.embedding_model == param("model"), 1)).as_(  # ty: ignore[invalid-argument-type]
                    "embedded"
                ),
                count(
                    when(
                        Message.body_clean.is_null()  # ty: ignore[unresolved-attribute]
                        | (Message.body_clean == ""),
                        1,
                    )
                ).as_("unembeddable"),
            )
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
            .where(
                Message.embedding.is_not_null() | Message.embedding_model.is_not_null()  # ty: ignore[unresolved-attribute]
            )
            .set({Message.embedding: None, Message.embedding_model: None})
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
