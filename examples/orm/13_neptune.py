"""Example 13 — Amazon Neptune Database with runic.ogm.

Demonstrates:
  - Connecting to Neptune Database via create_driver("neptune", ...)
  - IAM (SigV4) authentication — the default — and how to disable it
  - Session-based create / read / update / delete
  - QueryBuilder: .where(), .order_by(), .limit(), .count()

Prerequisites:
  - A Neptune Database cluster reachable from this machine. Neptune is
    VPC-only: run this in-VPC, over a VPN, or through a bastion/tunnel.
  - With IAM database authentication enabled (the default here), AWS
    credentials must be resolvable via the standard chain (env vars,
    ~/.aws/config, instance role) and the IAM principal needs
    ``neptune-db:connect`` on the cluster.
  - The ``neptune`` extra:  uv add "runic-py[neptune]"

Run:
    NEPTUNE_ENDPOINT=my-cluster.cluster-xxxx.eu-central-1.neptune.amazonaws.com \\
        AWS_REGION=eu-central-1 \\
        uv run python examples/orm/13_neptune.py
"""

from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

from runic.ogm import Field, Node, Repository, Session, select  # noqa: E402
from runic.ogm.driver import GraphDriver  # noqa: E402
from runic.ogm.driver.factory import create_driver  # noqa: E402

# ---------------------------------------------------------------------------
# Model definitions
# ---------------------------------------------------------------------------


class Language(Node, labels=["Language"]):
    """ISO language node."""

    id: str
    title: str
    code: str = Field(unique=True)


# ---------------------------------------------------------------------------
# Driver factory
# ---------------------------------------------------------------------------


def _create_driver() -> GraphDriver:
    return create_driver(
        "neptune",
        endpoint=os.environ["NEPTUNE_ENDPOINT"],
        port=int(os.getenv("NEPTUNE_PORT", "8182")),
        # IAM auth is the default; set NEPTUNE_USE_IAM=false for clusters
        # with IAM database authentication disabled.
        use_iam_auth=os.getenv("NEPTUNE_USE_IAM", "true").lower() == "true",
        region=os.getenv("AWS_REGION"),
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def run() -> None:
    driver = _create_driver()

    # Clean slate
    with Session(driver) as session:
        for lang in session.scalars(select(Language)):
            session.delete(lang)
        session.commit()

    # --- CREATE ---
    with Session(driver) as session:
        languages: list[Language] = [
            Language(id="en", title="English", code="en"),
            Language(id="de", title="German", code="de"),
            Language(id="fr", title="French", code="fr"),
        ]
        session.add_all(languages)
        session.commit()
        log.info("Created %d languages", len(languages))

    # --- READ ---
    with Session(driver) as session:
        repo = Repository(session, Language)
        for lang in repo.find_all():
            log.info("  %s — %s (%s)", lang.id, lang.title, lang.code)

    # --- UPDATE ---
    with Session(driver) as session:
        en: Language | None = session.get(Language, "en")
        assert en is not None
        en.title = "English (UK)"
        session.commit()
        log.info("Updated title to: %s", en.title)

    # --- DELETE ---
    with Session(driver) as session:
        fr: Language | None = session.get(Language, "fr")
        assert fr is not None
        session.delete(fr)
        session.commit()
        log.info("Deleted French")

    # --- QueryBuilder ---
    with Session(driver) as session:
        total: int = session.count(select(Language))
        ordered: list[Language] = session.scalars(
            select(Language).order_by(Language.code).limit(2)
        )
        log.info("Count: %d, ordered codes: %s", total, [r.code for r in ordered])

    driver.close()


if __name__ == "__main__":
    run()
