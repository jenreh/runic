"""The 37 statements of the ``mailarc-analytics`` catalogue, as parity cases.

Each :class:`CatalogCase` names one Cypher constant from that project's
``queries/catalog.py`` and records what runic must be able to express to
replace it.  While a statement is not yet expressible, ``build`` is ``None`` and
``gaps`` names the capabilities that block it — the suite reports those as
expected failures, so the count of built statements is the burn-down chart for
this work package.

Parity is **semantic, not textual**: runic will not emit byte-identical Cypher
(parameter naming, clause spacing and alias choice all differ).  ``expect``
therefore holds the Cypher fragments that must appear, not a whole statement.

Gap identifiers (G1…G19) are defined in the plan and repeated here so a failing
case explains itself:

=====  =========================================================================
G1     Projection aliasing (``AS name``) and expression projection
G2     Named bound parameters, including ``LIMIT $limit``
G3     Field-to-field comparison (``a.id < b.id``)
G4     Reverse list membership (``$token IN m.refs``)
G5     Relationship type alternation (``[:SENT_TO|COPIED_TO]``)
G6     Traversal from an explicit source alias (fan-out)
G7     Rich ``WITH`` — ``ORDER BY`` / ``LIMIT`` inside, repeatable
G8     Conditional aggregation (``count(CASE WHEN … THEN 1 END)``)
G9     ``collect(DISTINCT alias.prop)`` over a traversal alias
G10    ``DELETE`` / ``DETACH DELETE`` over a matched set
G11    ``UNWIND $rows`` + node ``MERGE`` + ``SET``
G12    ``UNWIND`` + multi-pattern ``MATCH`` + edge ``MERGE`` + ``SET``
G13    Undirected ``MERGE``
G14    Bulk ``SET`` over a matched set
G15    Edge-rooted / anonymous-endpoint patterns
G16    Index-backed KNN, score exposure, ``$k`` distinct from ``$limit``
G17    Fulltext score exposure
G18    Correlated ``CALL`` after a ``MATCH``
G19    Runtime index DDL and index introspection
=====  =========================================================================
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from runic.ogm import select
from runic.ogm.query.expressions import collect, count
from runic.ogm.query.values import col, left, param, when
from tests.runic.ogm.catalog_models import (
    About,
    Account,
    Address,
    Attachment,
    CoAddressed,
    Group,
    Message,
    Template,
    Thread,
    Topic,
)

__all__ = ["CATALOG_CASES", "CatalogCase", "expressible", "unexpressible"]


#: "Addressed" is defined as the walk over both types; matching them in two
#: separate patterns would double-count a message that used both.
ADDRESSED_TYPES = ["SENT_TO", "COPIED_TO"]

DEFAULT_PARAM_VALUES: Mapping[str, Any] = {
    # Cursors and paging. The cursor starts at "" so it is the exact complement
    # of the "no canonical id" filter, and the two still add up to every node.
    "after": "",
    "limit": 10,
    "batch": 100,
    "ids": ["m1", "m2"],
    # Thresholds
    "min_size": 2,
    "min_messages": 5,
    "direction": "sent",
    "max_distance": 0.35,
    # Semantic phase
    "model": "test-embedder",
    "max_chars": 2000,
    "k": 20,
    "vector": [0.0, 0.0, 0.0, 0.0],
    "text": "invoice",
    # Vector index options — the migration's own constants.
    "dimension": 4,
    "similarity": "cosine",
    "m": 16,
    "ef_construction": 200,
    "ef_runtime": 10,
}
"""Representative binding for each parameter name the catalogue uses."""


@dataclass(frozen=True)
class CatalogCase:
    """One catalogue statement and what runic must do to express it."""

    name: str
    """The constant's name in the source catalogue."""

    params: tuple[str, ...] = ()
    """Parameter names the statement binds. Checked once ``param()`` exists."""

    expect: tuple[str, ...] = ()
    """Cypher fragments that must appear in the built statement."""

    build: Callable[[], Any] | None = None
    """Returns the runic statement, or ``None`` while not yet expressible."""

    gaps: tuple[str, ...] = field(default_factory=tuple)
    """Capability gaps blocking this statement. Empty once ``build`` is set."""

    unsupported: Mapping[str, str] = field(default_factory=dict)
    """Backends that reject this statement, mapped to why.

    Not a licence to skip: a statement lands here only when the backend cannot
    express it for a reason that is recorded and understood.  The live suite
    reports the reason rather than silently passing.
    """

    sample_params: Mapping[str, Any] = field(default_factory=dict)
    """Per-statement bindings that differ from :data:`DEFAULT_PARAM_VALUES`.

    ``$rows`` is always per-statement: a group row and an edge row share a
    parameter name and nothing else.
    """

    @property
    def is_expressible(self) -> bool:
        return self.build is not None

    def bind(self) -> dict[str, Any]:
        """Representative values for every parameter this statement declares.

        Used by the live suite to run each statement against a real backend —
        the only way a statement ever gets checked rather than merely read.
        """
        values: dict[str, Any] = {}
        for name in self.params:
            if name in self.sample_params:
                values[name] = self.sample_params[name]
            elif name in DEFAULT_PARAM_VALUES:
                values[name] = DEFAULT_PARAM_VALUES[name]
            else:
                raise KeyError(
                    f"{self.name}: no sample value for ${name}; add one to "
                    f"DEFAULT_PARAM_VALUES or the case's sample_params"
                )
        return values

    def reason(self) -> str:
        return f"{self.name}: needs {', '.join(self.gaps) or 'nothing'}"


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
        gaps=("G7", "G10"),
    ),
    CatalogCase(
        name="DELETE_TOPICS",
        params=("batch",),
        expect=("MATCH (n:Topic)", "WITH n", "LIMIT $batch", "DETACH DELETE n"),
        gaps=("G7", "G10"),
    ),
    CatalogCase(
        name="DELETE_TEMPLATES",
        params=("batch",),
        expect=("MATCH (n:Template)", "WITH n", "LIMIT $batch", "DETACH DELETE n"),
        gaps=("G7", "G10"),
    ),
    CatalogCase(
        name="DELETE_CO_ADDRESSED",
        params=("batch",),
        # DELETE r, never DETACH DELETE: detaching would take both addresses.
        expect=("[r:CO_ADDRESSED]", "WITH r", "LIMIT $batch", "DELETE r"),
        gaps=("G7", "G10", "G15"),
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
        gaps=("G11",),
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
        gaps=("G12",),
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
        gaps=("G12", "G13"),
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
        gaps=("G11",),
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
        gaps=("G12",),
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
        gaps=("G11",),
    ),
    CatalogCase(
        name="MERGE_INSTANCE_OF",
        params=("rows",),
        sample_params={
            "rows": [{"message_id": "m1", "template_id": "tpl1", "distance": 2}]
        },
        expect=("UNWIND $rows AS row", "MERGE (m)-[r:INSTANCE_OF]->", "SET r.distance"),
        gaps=("G12",),
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
            "MATCH (n:Message {id: row.id})",
            "SET n.embedding = vecf32(row.vector)",
            "count(n) AS written",
        ),
        gaps=("G12", "G14"),
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
        gaps=("G1", "G2", "G6", "G7", "G16"),
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
        gaps=("G1", "G2", "G3", "G7", "G16", "G18"),
    ),
    CatalogCase(
        name="FULLTEXT_MESSAGES",
        params=("text", "limit"),
        expect=(
            "db.idx.fulltext.queryNodes",
            "$text",
            "score AS relevance",
            "ORDER BY relevance DESC",
            "LIMIT $limit",
        ),
        gaps=("G1", "G2", "G6", "G7", "G17"),
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
        gaps=("G14",),
    ),
    CatalogCase(
        name="CREATE_VECTOR_INDEX",
        params=("dimension", "similarity", "m", "ef_construction", "ef_runtime"),
        expect=("CREATE VECTOR INDEX", "Message", "embedding", "$dimension"),
        gaps=("G19",),
    ),
    CatalogCase(
        name="DROP_VECTOR_INDEX",
        expect=("DROP VECTOR INDEX", "Message", "embedding"),
        gaps=("G19",),
    ),
    CatalogCase(
        name="VECTOR_INDEX_OPTIONS",
        expect=("DB.INDEXES()", "options"),
        gaps=("G19",),
    ),
]

CATALOG_CASES: tuple[CatalogCase, ...] = (
    *_READS,
    *_DELETES,
    *_MERGES,
    *_ANALYSES,
    *_SEMANTIC,
)
"""Every catalogue statement, in source order.

Written out rather than scraped, for the reason the catalogue itself gives:
adding a statement without listing it is then visible in a diff.
"""


def expressible() -> tuple[CatalogCase, ...]:
    """Cases runic can build today."""
    return tuple(c for c in CATALOG_CASES if c.is_expressible)


def unexpressible() -> tuple[CatalogCase, ...]:
    """Cases still blocked on a capability gap."""
    return tuple(c for c in CATALOG_CASES if not c.is_expressible)


# Account is imported for the ACCOUNT_ADDRESSES case, which is not yet buildable.
_ = Account
