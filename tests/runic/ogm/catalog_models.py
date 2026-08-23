"""Domain models mirroring the ``mailarc-analytics`` statement catalogue.

Shared by the catalogue-parity suites (unit and live).  The labels and property
names are the real ones from that project so a parity assertion reads like the
Cypher constant it is checked against.

Relation fields carry the relationship types the catalogue traverses.  Where a
statement walks an alternation (``[:SENT_TO|COPIED_TO]``) the relation is
declared with the full list; single-type backends of that declaration are
covered by :data:`Message.sent_to` / :data:`Message.copied_to`.
"""

from __future__ import annotations

from datetime import datetime

from runic.ogm.core.descriptors import Field, Relation
from runic.ogm.core.models import Edge, Node
from runic.ogm.core.types import Vector

# ---------------------------------------------------------------------------
# Ground truth — written by the importer
# ---------------------------------------------------------------------------


class Account(Node, labels=["Account"]):
    """An address this archive imports from."""

    id: str = Field(primary_key=True)
    address: str | None = Field(default=None)


class Address(Node, labels=["Address"]):
    """A mail address. The canonical key is ``id``, not ``address``."""

    id: str = Field(primary_key=True)
    co_addressed: list[Address] = Relation(
        relationship="CO_ADDRESSED",
        direction="BOTH",
        target="Address",
        edge_model="CoAddressed",
    )


class Thread(Node, labels=["Thread"]):
    id: str = Field(primary_key=True)


class Attachment(Node, labels=["Attachment"]):
    id: str = Field(primary_key=True)


class Message(Node, labels=["Message"]):
    id: str = Field(primary_key=True)
    subject: str | None = Field(default=None)
    subject_norm: str | None = Field(default=None)
    sent_at: datetime | None = Field(default=None)
    participant_key: str | None = Field(default=None)
    simhash: int | None = Field(default=None)
    refs: list[str] = Field(default_factory=list)
    body_clean: str | None = Field(default=None)
    embedding: Vector | None = Field(default=None, index_type="VECTOR")
    embedding_model: str | None = Field(default=None)

    sent_from: Address | None = Relation(
        relationship="SENT_FROM", direction="OUTGOING", target="Address"
    )
    sent_to: list[Address] = Relation(
        relationship="SENT_TO", direction="OUTGOING", target="Address"
    )
    copied_to: list[Address] = Relation(
        relationship="COPIED_TO", direction="OUTGOING", target="Address"
    )
    blind_copied_to: list[Address] = Relation(
        relationship="BLIND_COPIED_TO", direction="OUTGOING", target="Address"
    )
    in_thread: Thread | None = Relation(
        relationship="IN_THREAD", direction="OUTGOING", target="Thread"
    )
    has_attachment: list[Attachment] = Relation(
        relationship="HAS_ATTACHMENT", direction="OUTGOING", target="Attachment"
    )
    addressed_group: Group | None = Relation(
        relationship="ADDRESSED_GROUP", direction="OUTGOING", target="Group"
    )
    about: list[Topic] = Relation(
        relationship="ABOUT",
        direction="OUTGOING",
        target="Topic",
        edge_model="About",
    )
    instance_of: list[Template] = Relation(
        relationship="INSTANCE_OF",
        direction="OUTGOING",
        target="Template",
        edge_model="InstanceOf",
    )


# ---------------------------------------------------------------------------
# Derived — rebuilt from ground truth, dropped and rewritten on every rebuild
# ---------------------------------------------------------------------------


class Group(Node, labels=["Group"]):
    id: str = Field(primary_key=True)
    size: int | None = Field(default=None)
    message_count: int | None = Field(default=None)
    first_seen: datetime | None = Field(default=None)
    last_seen: datetime | None = Field(default=None)


class Topic(Node, labels=["Topic"]):
    id: str = Field(primary_key=True)
    label: str | None = Field(default=None)
    method: str | None = Field(default=None)
    score: float | None = Field(default=None)
    message_count: int | None = Field(default=None)
    first_seen: datetime | None = Field(default=None)
    last_seen: datetime | None = Field(default=None)


class Template(Node, labels=["Template"]):
    id: str = Field(primary_key=True)
    sample_text: str | None = Field(default=None)
    occurrences: int | None = Field(default=None)
    automation_score: float | None = Field(default=None)
    direction: str | None = Field(default=None)
    first_seen: datetime | None = Field(default=None)
    last_seen: datetime | None = Field(default=None)


# ---------------------------------------------------------------------------
# Edge models — the derived edges that carry properties
# ---------------------------------------------------------------------------


class CoAddressed(Edge, type="CO_ADDRESSED"):
    """Undirected in meaning; both endpoints are ``Address``."""

    count: int | None = Field(default=None)
    first_seen: datetime | None = Field(default=None)
    last_seen: datetime | None = Field(default=None)


class About(Edge, type="ABOUT"):
    score: float | None = Field(default=None)
    method: str | None = Field(default=None)


class InstanceOf(Edge, type="INSTANCE_OF"):
    distance: int | None = Field(default=None)
