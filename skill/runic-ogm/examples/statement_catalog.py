"""A statement catalogue: every query the layer runs, named and parameterised.

The shape a query layer takes when something else can reach it — an HTTP
handler, a background job, a model answering questions through a tool. A
statement is a module-level constant or it does not exist, and caller input
arrives as a bound parameter, so it can change which rows come back but never
what a statement does.

Run this file to see the Cypher each statement compiles to::

    python statement_catalog.py
"""

from __future__ import annotations

from datetime import datetime
from types import MappingProxyType
from typing import Any, Final

from runic.ogm import (
    Edge,
    Field,
    Node,
    QueryBuilder,
    Relation,
    col,
    collect,
    count,
    encode_rows,
    left,
    param,
    row,
    score,
    select,
    unwind,
    when,
)

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class Address(Node, labels=["Address"]):
    id: str = Field(primary_key=True)


class Topic(Node, labels=["Topic"]):
    id: str = Field(primary_key=True)
    label: str | None = Field(default=None)
    message_count: int | None = Field(default=None)
    first_seen: datetime | None = Field(default=None)


class About(Edge, type="ABOUT"):
    score: float | None = Field(default=None)


class Message(Node, labels=["Message"]):
    id: str = Field(primary_key=True)
    subject: str | None = Field(default=None)
    body: str | None = Field(default=None)
    sent_at: datetime | None = Field(default=None)
    embedding_model: str | None = Field(default=None)

    sent_to: list[Address] = Relation(
        relationship="SENT_TO", direction="OUTGOING", target="Address"
    )
    about: list[Topic] = Relation(
        relationship="ABOUT", direction="OUTGOING", target="Topic", edge_model="About"
    )


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

MESSAGE_PAGE: Final = (
    select(Message)
    # A cursor, not an offset: SKIP re-matches and re-sorts every preceding row,
    # so paging a whole label costs O(n²/page).
    .where(Message.id > param("after"))  # ty: ignore[unresolved-attribute]
    .project(
        col(Message.id).as_("id"),
        col(Message.subject).as_("subject"),
        # Truncate in the store: the body is uncapped and a page is hundreds
        # of them.
        left(col(Message.body), param("max_chars")).as_("body"),
    )
    # Paging without an order is undefined; two runs may return different pages.
    .order_by(Message.id)
    .limit(param("limit"))
)
"""One page of messages, cut to length. Binds: after, max_chars, limit."""


MESSAGE_RECIPIENTS: Final = (
    select(Message)
    .alias("m")
    .where(Message.id > param("after"))  # ty: ignore[unresolved-attribute]
    # The page is taken BEFORE the expansion. A trailing LIMIT would expand
    # every message in the graph and then discard all but this page.
    .with_("m", order_by=Message.id, limit=param("limit"))
    .traverse(Message.sent_to, from_="m")  # ty: ignore[invalid-argument-type]
    .alias("r")
    .aggregate(
        collect(col("r", Address.id), distinct=True).as_("recipients"),
        group_by=col("m", Message.id).as_("id"),
    )
)
"""Each message with its recipients, one row per message. Binds: after, limit."""


TOPIC_SIZES: Final = (
    select(Message)
    .alias("m")
    # optional=False because the edge property is a filter, not a decoration:
    # on an OPTIONAL MATCH a WHERE nullifies rows instead of dropping them.
    .traverse(Message.about, edge_alias="r", optional=False)  # ty: ignore[invalid-argument-type]
    .alias("t")
    .where(About.score >= param("min_score"), on="r")
    .aggregate(
        count("*").as_("messages"),
        group_by=[col("t", Topic.id).as_("id"), col("t", Topic.label).as_("label")],
    )
    .order_by("messages", desc=True)
    .limit(param("limit"))
)
"""Topics by size. Binds: min_score, limit."""


EMBEDDING_COVERAGE: Final = (
    select(Message)
    .where(Message.id.is_not_null())  # ty: ignore[unresolved-attribute]
    # Several counts over ONE scan, which also guarantees they are counted over
    # the same population. Asked as separate queries they can drift apart.
    .aggregate(
        count("*").as_("total"),
        count(when(Message.embedding_model == param("model"), 1)).as_("embedded"),
    )
)
"""How much of the corpus the current model has embedded. Binds: model."""


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------

MERGE_TOPICS: Final = (
    unwind(param("rows"))
    # MERGE, not CREATE: a derived label carries no unique constraint, so a
    # second run of a CREATE job silently doubles every node. Only the KEY goes
    # in the pattern — a changed property would make MERGE miss the node.
    .merge(Topic, key={Topic.id: row("id")}, alias="t")
    .set(
        {
            Topic.label: row("label"),
            Topic.message_count: row("message_count"),
            Topic.first_seen: row("first_seen"),
        },
        on="t",
    )
)
"""Upsert topics. Binds: rows (run through encode_rows first)."""


LINK_TOPICS: Final = (
    unwind(param("rows"))
    # MATCH and not MERGE on the endpoints: a row naming a node that is not
    # there is a caller-ordering bug, and merging would replace it with an empty
    # node carrying nothing but a key.
    .match(Message, key={Message.id: row("message_id")}, alias="m")
    .match(Topic, key={Topic.id: row("topic_id")}, alias="t")
    .merge_edge("m", "ABOUT", "t", alias="r", edge_model=About)
    .set({About.score: row("score")}, on="r")
)
"""Attach messages to topics. Binds: rows."""


DELETE_TOPICS: Final = (
    select(Topic)
    # Batched: one unbounded delete over a large graph is a single long stall on
    # a store something else is also reading. Loop until removed is zero.
    .with_("n", limit=param("batch"))
    .delete(detach=True)
    .returning(count("n").as_("removed"))
)
"""Drop a batch of topics and their edges. Binds: batch."""


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


def similar_messages(session: Any) -> QueryBuilder[Message]:
    """Nearest neighbours of a query vector.

    Built through the session because a search needs the backend's dialect to
    know which procedure to name.

    ``k`` and ``limit`` are different numbers on purpose: a procedure cannot be
    narrowed before the fact, so every row the ``where()`` drops has already
    been paid for by ``k``. Asking for ``k == limit`` returns a short page that
    looks exactly like a small corpus.
    """
    return (
        session.vector_search(
            Message,
            field=Message.embedding_model,
            vector=param("vector"),
            k=param("k"),
        )
        .where(Message.embedding_model == param("model"))
        .project(
            col(Message.id).as_("id"),
            col(Message.subject).as_("subject"),
            # A distance: lower is closer, on every backend.
            score().as_("distance"),
        )
        .limit(param("limit"))
    )


# ---------------------------------------------------------------------------
# The catalogue
# ---------------------------------------------------------------------------

CATALOG: Final[Any] = MappingProxyType(
    {
        "MESSAGE_PAGE": MESSAGE_PAGE,
        "MESSAGE_RECIPIENTS": MESSAGE_RECIPIENTS,
        "TOPIC_SIZES": TOPIC_SIZES,
        "EMBEDDING_COVERAGE": EMBEDDING_COVERAGE,
        "MERGE_TOPICS": MERGE_TOPICS,
        "LINK_TOPICS": LINK_TOPICS,
        "DELETE_TOPICS": DELETE_TOPICS,
    }
)
"""Every statement, by name.

Written out rather than scraped off the module, so adding a statement without
listing it is visible in a diff — and so one test can bind every statement's
parameters and run the lot against a real backend, which is the only way a
statement ever gets checked rather than merely read.
"""


def usage(session: Any) -> None:
    """How a caller runs these."""
    # Reads. Every execution method takes bindings as a second argument.
    session.all_rows(MESSAGE_PAGE, {"after": "", "max_chars": 2000, "limit": 500})
    session.all_rows(EMBEDDING_COVERAGE, {"model": "text-embedding-3-small"})

    # Writes. encode_rows applies the field converters that a $rows payload
    # would otherwise skip — a datetime in there reaches the driver as an
    # object it has no encoding for.
    payload = [{"id": "t1", "label": "billing", "first_seen": datetime.now()}]
    session.all_rows(MERGE_TOPICS, {"rows": encode_rows(Topic, payload)})

    # Batched delete: loop until nothing is left.
    while session.all_rows(DELETE_TOPICS, {"batch": 10_000})[0]["removed"]:
        pass


if __name__ == "__main__":
    for name, statement in CATALOG.items():
        cypher, _ = statement.build()
        print(f"# {name}  binds: {statement.parameter_names() or '(none)'}")  # noqa: T201
        print(cypher, end="\n\n")  # noqa: T201
