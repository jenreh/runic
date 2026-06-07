"""Example 10 — Query builder: aggregations.

Demonstrates:
  - count("*") — total rows
  - count(field, distinct=True) — distinct value count
  - avg(field) — average
  - sum_(field) — sum
  - min_(field) / max_(field) — min/max
  - collect(field) — collect values into a list
  - .aggregate(*exprs, group_by="alias") — grouped aggregation
  - .all_rows() — returns list[dict] for mixed-type results
  - .scalar() — single aggregation value
  - distinct() — DISTINCT in RETURN clause

Run against FalkorDB (embedded):
    uv run python examples/orm/10_query_builder_aggregation.py

Run against FalkorDB (live server):
    FALKORDB_HOST=localhost FALKORDB_PORT=6379 uv run python examples/orm/10_query_builder_aggregation.py

Run against ArcadeDB (via Bolt):
    RUNIC_BACKEND=arcadedb ARCADEDB_HOST=localhost ARCADEDB_DATABASE=runic_examples \\
        uv run python examples/orm/10_query_builder_aggregation.py
"""

from __future__ import annotations

import logging
import os
from typing import Any

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

from runic.orm import (  # noqa: E402
    Edge,
    Field,
    Node,
    Relation,
    Session,
    avg,
    collect,
    count,
    max_,
    min_,
    select,
    sum_,
)
from runic.orm.driver import GraphDriver  # noqa: E402
from runic.orm.driver.factory import create_driver  # noqa: E402
from runic.orm.driver.falkordb import FalkorDBDriver  # noqa: E402

# ---------------------------------------------------------------------------
# Models: e-commerce order graph
# ---------------------------------------------------------------------------


class Customer(Node, labels=["Customer"]):
    id: str = Field(primary_key=True)
    name: str = Field()
    region: str = Field()


class OrderEdge(Edge, type="PLACED"):
    """Edge: customer placed an order."""

    amount: float = Field()
    status: str = Field(default="pending")


class Item(Node, labels=["Item"]):
    id: str = Field(primary_key=True)
    name: str = Field()
    category: str = Field()
    price: float = Field()

    orders: list[Any] = Relation(
        relationship="PLACED",
        direction="INCOMING",
        target="Customer",
        edge_model=OrderEdge,
    )


class Order(Node, labels=["Order"]):
    id: str = Field(primary_key=True)
    amount: float = Field()
    status: str = Field(default="pending")
    region: str = Field()


# ---------------------------------------------------------------------------
# Connection helper
# ---------------------------------------------------------------------------


def _create_driver() -> GraphDriver:
    backend = os.getenv("RUNIC_BACKEND", "falkordb")
    if backend == "falkordb":
        host = os.getenv("FALKORDB_HOST", "")
        if host:
            from falkordb import FalkorDB

            db = FalkorDB(host=host, port=int(os.getenv("FALKORDB_PORT", "6379")))
        else:
            from redislite import FalkorDB  # type: ignore[no-redef]

            db = FalkorDB(protocol=2)
        return FalkorDBDriver(db.select_graph("example_qb_aggregation"))
    if backend == "arcadedb":
        return create_driver(
            "arcadedb",
            host=os.getenv("ARCADEDB_HOST", "localhost"),
            port=int(os.getenv("ARCADEDB_PORT", "7687")),
            database=os.getenv("ARCADEDB_DATABASE", "runic_examples"),
            username=os.getenv("ARCADEDB_USERNAME", "root"),
            password=os.getenv("ARCADEDB_PASSWORD", "playwithdata"),
        )
    raise ValueError(
        f"Unknown RUNIC_BACKEND: {backend!r}. Supported: 'falkordb', 'arcadedb'"
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def run() -> None:
    driver = _create_driver()

    # --- Seed ---
    with Session(driver) as session:
        orders: list[Order] = [
            Order(id="o1", amount=120.0, status="completed", region="EU"),
            Order(id="o2", amount=85.5, status="completed", region="EU"),
            Order(id="o3", amount=340.0, status="completed", region="US"),
            Order(id="o4", amount=60.0, status="pending", region="US"),
            Order(id="o5", amount=200.0, status="completed", region="APAC"),
            Order(id="o6", amount=75.0, status="cancelled", region="EU"),
            Order(id="o7", amount=500.0, status="completed", region="US"),
            Order(id="o8", amount=30.0, status="pending", region="APAC"),
            Order(id="o9", amount=410.0, status="completed", region="US"),
            Order(id="o10", amount=95.0, status="completed", region="EU"),
        ]
        session.add_all(orders)
        session.commit()
        log.info("Created %d orders", len(orders))

    # --- count(*) — total rows ---
    with Session(driver) as session:
        total: int = session.count(select(Order))
        log.info("count(*): %d", total)

    # --- count(*) with filter ---
    with Session(driver) as session:
        completed: int = session.count(select(Order).where(Order.status == "completed"))
        log.info("count completed: %d", completed)

    # --- count(DISTINCT field) ---
    with Session(driver) as session:
        rows_dr = session.all_rows(
            select(Order).aggregate(count(Order.region, distinct=True).as_("regions"))
        )
        distinct_regions: int | None = rows_dr[0]["regions"] if rows_dr else None
        log.info("count(DISTINCT region): %s", distinct_regions)

    # --- avg() ---
    with Session(driver) as session:
        rows_avg = session.all_rows(
            select(Order)
            .where(Order.status == "completed")
            .aggregate(avg(Order.amount).as_("avg_amount"))
        )
        avg_amount: float | None = rows_avg[0]["avg_amount"] if rows_avg else None
        log.info("avg amount (completed): %.2f", avg_amount or 0.0)

    # --- sum_() ---
    with Session(driver) as session:
        rows_rev = session.all_rows(
            select(Order)
            .where(Order.status == "completed")
            .aggregate(sum_(Order.amount).as_("revenue"))
        )
        total_revenue: float | None = rows_rev[0]["revenue"] if rows_rev else None
        log.info("sum amount (completed): %.2f", total_revenue or 0.0)

    # --- min_() and max_() ---
    with Session(driver) as session:
        rows_min = session.all_rows(
            select(Order).aggregate(min_(Order.amount).as_("min_amount"))
        )
        min_amount: float | None = rows_min[0]["min_amount"] if rows_min else None
        rows_max = session.all_rows(
            select(Order).aggregate(max_(Order.amount).as_("max_amount"))
        )
        max_amount: float | None = rows_max[0]["max_amount"] if rows_max else None
        log.info("min=%.2f, max=%.2f", min_amount or 0.0, max_amount or 0.0)

    # --- Multiple aggregations in one query via all_rows() ---
    with Session(driver) as session:
        summary: list[dict[str, Any]] = session.all_rows(
            select(Order)
            .where(Order.status == "completed")
            .aggregate(
                count("*").as_("total"),
                avg(Order.amount).as_("avg"),
                sum_(Order.amount).as_("revenue"),
                min_(Order.amount).as_("min"),
                max_(Order.amount).as_("max"),
            )
        )
        log.info("Multi-agg summary: %s", summary)

    # --- Grouped aggregation: totals per region ---
    with Session(driver) as session:
        by_region: list[dict[str, Any]] = session.all_rows(
            select(Order)
            .alias("o")
            .aggregate(
                count("*").as_("total"),
                sum_(Order.amount).as_("revenue"),
                avg(Order.amount).as_("avg"),
                group_by="o",
            )
        )
        log.info(
            "Aggregation by alias (no projection on group key): %d rows", len(by_region)
        )

    # --- collect() — gather values into a list ---
    with Session(driver) as session:
        ids_by_status: list[dict[str, Any]] = session.all_rows(
            select(Order)
            .alias("o")
            .aggregate(
                collect(Order.id).as_("order_ids"),
                group_by="o",
            )
        )
        log.info("collect() returned %d rows", len(ids_by_status))

    # --- collect(distinct=True) ---
    with Session(driver) as session:
        rows_cs = session.all_rows(
            select(Order).aggregate(
                collect(Order.status, distinct=True).as_("statuses")
            )
        )
        unique_statuses: list[str] | None = rows_cs[0]["statuses"] if rows_cs else None
        log.info("collect(DISTINCT status): %s", unique_statuses)

    # --- distinct() on RETURN clause ---
    with Session(driver) as session:
        rows_reg = session.all_rows(select(Order).project(Order.region).distinct())
        regions: list[str] = [r["n.region"] for r in rows_reg]
        log.info("DISTINCT regions via project+distinct: %s", sorted(regions))

    # --- all_rows(): single aggregation value ---
    with Session(driver) as session:
        rows_pt = session.all_rows(
            select(Order)
            .where(Order.status == "pending")
            .aggregate(sum_(Order.amount).as_("pending_total"))
        )
        pending_total: float | None = rows_pt[0]["pending_total"] if rows_pt else None
        log.info("pending total amount: %.2f", pending_total or 0.0)

    # --- build() — inspect aggregation Cypher ---
    cypher: str
    params: dict[str, Any]
    cypher, params = (
        select(Order)
        .alias("o")
        .where(Order.status == "completed")
        .aggregate(
            count("*").as_("total"),
            sum_(Order.amount).as_("revenue"),
        )
        .build()
    )
    log.info("Aggregation Cypher:\n%s\nparams: %s", cypher, params)

    driver.close()


if __name__ == "__main__":
    run()
