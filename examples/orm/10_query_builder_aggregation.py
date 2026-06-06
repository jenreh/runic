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

Run:
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
    sum_,
)

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


def _connect() -> Any:
    host = os.getenv("FALKORDB_HOST", "")
    if host:
        from falkordb import FalkorDB

        db = FalkorDB(host=host, port=int(os.getenv("FALKORDB_PORT", "6379")))
    else:
        from redislite import FalkorDB  # type: ignore[no-redef]

        db = FalkorDB(protocol=2)
    return db.select_graph("example_qb_aggregation")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def run() -> None:
    graph = _connect()

    # --- Seed ---
    with Session(graph) as session:
        orders = [
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
    with Session(graph) as session:
        total = session.query(Order).count()
        log.info("count(*): %d", total)

    # --- count(*) with filter ---
    with Session(graph) as session:
        completed = session.query(Order).where(Order.status == "completed").count()
        log.info("count completed: %d", completed)

    # --- count(DISTINCT field) ---
    with Session(graph) as session:
        distinct_regions = (
            session.query(Order)
            .aggregate(count(Order.region, distinct=True).as_("regions"))
            .scalar()
        )
        log.info("count(DISTINCT region): %s", distinct_regions)

    # --- avg() ---
    with Session(graph) as session:
        avg_amount = (
            session.query(Order)
            .where(Order.status == "completed")
            .aggregate(avg(Order.amount).as_("avg_amount"))
            .scalar()
        )
        log.info("avg amount (completed): %.2f", avg_amount or 0.0)

    # --- sum_() ---
    with Session(graph) as session:
        total_revenue = (
            session.query(Order)
            .where(Order.status == "completed")
            .aggregate(sum_(Order.amount).as_("revenue"))
            .scalar()
        )
        log.info("sum amount (completed): %.2f", total_revenue or 0.0)

    # --- min_() and max_() ---
    with Session(graph) as session:
        min_amount = (
            session.query(Order)
            .aggregate(min_(Order.amount).as_("min_amount"))
            .scalar()
        )
        max_amount = (
            session.query(Order)
            .aggregate(max_(Order.amount).as_("max_amount"))
            .scalar()
        )
        log.info("min=%.2f, max=%.2f", min_amount or 0.0, max_amount or 0.0)

    # --- Multiple aggregations in one query via all_rows() ---
    with Session(graph) as session:
        summary = (
            session.query(Order)
            .where(Order.status == "completed")
            .aggregate(
                count("*").as_("total"),
                avg(Order.amount).as_("avg"),
                sum_(Order.amount).as_("revenue"),
                min_(Order.amount).as_("min"),
                max_(Order.amount).as_("max"),
            )
            .all_rows()
        )
        log.info("Multi-agg summary: %s", summary)

    # --- Grouped aggregation: totals per region ---
    with Session(graph) as session:
        by_region = (
            session.query(Order)
            .alias("o")
            .aggregate(
                count("*").as_("total"),
                sum_(Order.amount).as_("revenue"),
                avg(Order.amount).as_("avg"),
                group_by="o",
            )
            .all_rows()
        )
        log.info(
            "Aggregation by alias (no projection on group key): %d rows", len(by_region)
        )

    # --- collect() — gather values into a list ---
    with Session(graph) as session:
        ids_by_status = (
            session.query(Order)
            .alias("o")
            .aggregate(
                collect(Order.id).as_("order_ids"),
                group_by="o",
            )
            .all_rows()
        )
        log.info("collect() returned %d rows", len(ids_by_status))

    # --- collect(distinct=True) ---
    with Session(graph) as session:
        unique_statuses = (
            session.query(Order)
            .aggregate(collect(Order.status, distinct=True).as_("statuses"))
            .scalar()
        )
        log.info("collect(DISTINCT status): %s", unique_statuses)

    # --- distinct() on RETURN clause ---
    with Session(graph) as session:
        regions = session.query(Order).project(Order.region).distinct().scalars()
        log.info("DISTINCT regions via project+distinct: %s", sorted(regions))

    # --- scalar(): single aggregation value ---
    with Session(graph) as session:
        pending_total = (
            session.query(Order)
            .where(Order.status == "pending")
            .aggregate(sum_(Order.amount).as_("pending_total"))
            .scalar()
        )
        log.info("pending total amount: %.2f", pending_total or 0.0)

    # --- build() — inspect aggregation Cypher ---
    with Session(graph) as session:
        cypher, params = (
            session.query(Order)
            .alias("o")
            .where(Order.status == "completed")
            .aggregate(
                count("*").as_("total"),
                sum_(Order.amount).as_("revenue"),
            )
            .build()
        )
        log.info("Aggregation Cypher:\n%s\nparams: %s", cypher, params)


if __name__ == "__main__":
    run()
