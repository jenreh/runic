"""Example 7 — Query builder: basics.

Demonstrates every foundational feature of the fluent QueryBuilder API:
  - Equality, inequality, numeric comparisons
  - String predicates: contains(), startswith(), endswith(), matches()
  - Null checks: is_null(), is_not_null()
  - Membership: in_(), not_in_()
  - Boolean composition: & (AND), | (OR), ~ (NOT)
  - order_by(), limit(), skip(), distinct()
  - Terminal methods: all(), one(), count(), scalar(), scalars()
  - Projection: project() → all_rows() / scalars()
  - build() — inspect generated Cypher without executing

Run:
    uv run python examples/orm/07_query_builder_basics.py
"""

from __future__ import annotations

import logging
import os
from typing import Any

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

from runic.orm import Field, Node, Session, avg, count, max_, min_, sum_  # noqa: E402

# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


class Product(Node, labels=["Product"]):
    id: str = Field(primary_key=True)
    name: str = Field()
    category: str = Field()
    price: float = Field()
    stock: int = Field(default=0)
    active: bool = Field(default=True)
    description: str | None = Field(default=None)
    sku: str | None = Field(default=None)


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
    return db.select_graph("example_qb_basics")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def run() -> None:
    graph = _connect()

    # --- Seed ---
    with Session(graph) as session:
        products = [
            Product(
                id="p1",
                name="Graph Database Book",
                category="books",
                price=49.99,
                stock=100,
                active=True,
                sku="BOOK-001",
            ),
            Product(
                id="p2",
                name="Graph Analytics Course",
                category="courses",
                price=199.00,
                stock=0,
                active=True,
                sku="COURSE-001",
            ),
            Product(
                id="p3",
                name="Advanced Cypher Guide",
                category="books",
                price=39.99,
                stock=50,
                active=True,
                sku="BOOK-002",
            ),
            Product(
                id="p4",
                name="Legacy Tutorial",
                category="books",
                price=19.99,
                stock=10,
                active=False,
            ),
            Product(
                id="p5",
                name="FalkorDB Starter Kit",
                category="hardware",
                price=299.00,
                stock=5,
                active=True,
                sku="HW-001",
            ),
        ]
        session.add_all(products)
        session.commit()
        log.info("Created %d products", len(products))

    # --- Equality filter ---
    with Session(graph) as session:
        books = session.query(Product).where(Product.category == "books").all()
        log.info("category == 'books': %s", [p.name for p in books])

    # --- Inequality filter ---
    with Session(graph) as session:
        not_books = session.query(Product).where(Product.category != "books").all()
        log.info("category != 'books': %s", [p.name for p in not_books])

    # --- Numeric comparison: greater-than ---
    with Session(graph) as session:
        expensive = (
            session.query(Product)
            .where(Product.price > 100.0)
            .order_by(Product.price, desc=True)
            .all()
        )
        log.info("price > 100: %s", [(p.name, p.price) for p in expensive])

    # --- Numeric comparison: less-than-or-equal ---
    with Session(graph) as session:
        cheap = session.query(Product).where(Product.price <= 40.0).all()
        log.info("price <= 40: %s", [p.name for p in cheap])

    # --- String predicate: contains() ---
    with Session(graph) as session:
        graph_products = (
            session.query(Product)
            .where(Product.name.contains("Graph"))  # type: ignore[attr-defined]
            .all()
        )
        log.info("name.contains('Graph'): %s", [p.name for p in graph_products])

    # --- String predicate: startswith() ---
    with Session(graph) as session:
        adv = (
            session.query(Product)
            .where(Product.name.startswith("Advanced"))  # type: ignore[attr-defined]
            .all()
        )
        log.info("name.startswith('Advanced'): %s", [p.name for p in adv])

    # --- String predicate: endswith() ---
    with Session(graph) as session:
        kits = (
            session.query(Product)
            .where(Product.name.endswith("Kit"))  # type: ignore[attr-defined]
            .all()
        )
        log.info("name.endswith('Kit'): %s", [p.name for p in kits])

    # --- String predicate: matches() (regex) — requires live FalkorDB v4+ ---
    # NOTE: =~ regex is not supported by the embedded redislite backend.
    # Uncomment when running against a live FalkorDB instance:
    # with Session(graph) as session:
    #     regex_match = (
    #         session.query(Product)
    #         .where(Product.name.matches(".*Graph.*"))  # type: ignore[attr-defined]
    #         .all()
    #     )
    #     log.info("name.matches('.*Graph.*'): %s", [p.name for p in regex_match])

    # --- Null check: is_null() ---
    with Session(graph) as session:
        no_sku = (
            session.query(Product)
            .where(Product.sku.is_null())  # type: ignore[attr-defined]
            .all()
        )
        log.info("sku IS NULL: %s", [p.name for p in no_sku])

    # --- Null check: is_not_null() ---
    with Session(graph) as session:
        has_sku = (
            session.query(Product)
            .where(Product.sku.is_not_null())  # type: ignore[attr-defined]
            .all()
        )
        log.info("sku IS NOT NULL: %s", [p.name for p in has_sku])

    # --- Membership: in_() ---
    with Session(graph) as session:
        selected = (
            session.query(Product)
            .where(Product.id.in_(["p1", "p3", "p5"]))  # type: ignore[attr-defined]
            .order_by(Product.id)
            .all()
        )
        log.info("id in ['p1','p3','p5']: %s", [p.id for p in selected])

    # --- Membership: not_in_() ---
    with Session(graph) as session:
        excluded = (
            session.query(Product)
            .where(Product.category.not_in_(["hardware"]))  # type: ignore[attr-defined]
            .order_by(Product.id)
            .all()
        )
        log.info("category not_in ['hardware']: %s", [p.id for p in excluded])

    # --- Boolean AND: & operator ---
    with Session(graph) as session:
        active_books = (
            session.query(Product)
            .where(
                (Product.category == "books")  # type: ignore[operator]
                & (Product.active == True)  # noqa: E712
            )
            .all()
        )
        log.info("category='books' AND active=True: %s", [p.name for p in active_books])

    # --- Boolean OR: | operator ---
    with Session(graph) as session:
        books_or_courses = (
            session.query(Product)
            .where(
                (Product.category == "books")  # type: ignore[operator]
                | (Product.category == "courses")
            )
            .all()
        )
        log.info(
            "category='books' OR 'courses': %s", [p.name for p in books_or_courses]
        )

    # --- Boolean NOT: ~ operator ---
    with Session(graph) as session:
        not_active = (
            session.query(Product)
            .where(~(Product.active == True))  # noqa: E712
            .all()
        )
        log.info("NOT active=True: %s", [p.name for p in not_active])

    # --- Three-condition compound: & chained ---
    with Session(graph) as session:
        in_stock_books = (
            session.query(Product)
            .where(
                (Product.category == "books")  # type: ignore[operator]
                & (Product.active == True)  # noqa: E712
                & (Product.stock > 0)
            )
            .all()
        )
        log.info("books AND active AND stock>0: %s", [p.name for p in in_stock_books])

    # --- order_by ASC (default) ---
    with Session(graph) as session:
        by_price_asc = session.query(Product).order_by(Product.price).all()
        log.info("ORDER BY price ASC: %s", [p.price for p in by_price_asc])

    # --- order_by DESC ---
    with Session(graph) as session:
        by_price_desc = session.query(Product).order_by(Product.price, desc=True).all()
        log.info("ORDER BY price DESC: %s", [p.price for p in by_price_desc])

    # --- limit() ---
    with Session(graph) as session:
        top2 = session.query(Product).order_by(Product.price, desc=True).limit(2).all()
        log.info("LIMIT 2 by price desc: %s", [p.name for p in top2])

    # --- skip() + limit() (manual pagination) ---
    with Session(graph) as session:
        page2 = session.query(Product).order_by(Product.id).skip(2).limit(2).all()
        log.info("SKIP 2 LIMIT 2: %s", [p.id for p in page2])

    # --- distinct() ---
    with Session(graph) as session:
        cats = session.query(Product).project(Product.category).distinct().scalars()
        log.info("DISTINCT categories: %s", sorted(cats))

    # --- Terminal: count() ---
    with Session(graph) as session:
        total = session.query(Product).count()
        log.info("count(*): %d", total)

    # --- Terminal: count() with filter ---
    with Session(graph) as session:
        active_count = (
            session.query(Product)
            .where(Product.active == True)  # noqa: E712
            .count()
        )
        log.info("count where active=True: %d", active_count)

    # --- Terminal: one() ---
    with Session(graph) as session:
        p = session.query(Product).where(Product.id == "p1").one()
        log.info("one() p1: %s", p and p.name)

    # --- Terminal: one() — no match returns None ---
    with Session(graph) as session:
        missing = session.query(Product).where(Product.id == "NOPE").one()
        log.info("one() no match: %s", missing)

    # --- Terminal: scalar() — first column of first row ---
    with Session(graph) as session:
        lowest_price = (
            session.query(Product)
            .aggregate(min_(Product.price).as_("min_price"))
            .scalar()
        )
        log.info("scalar() min price: %s", lowest_price)

    # --- Terminal: scalars() — first column of every row ---
    with Session(graph) as session:
        all_ids = (
            session.query(Product).order_by(Product.id).project(Product.id).scalars()
        )
        log.info("scalars() all ids: %s", all_ids)

    # --- project() → all_rows() — multi-field projection as dicts ---
    with Session(graph) as session:
        rows = (
            session.query(Product)
            .where(Product.active == True)  # noqa: E712
            .order_by(Product.price)
            .project(Product.name, Product.price)
            .all_rows()
        )
        log.info("project all_rows: %s", rows)

    # --- build() — inspect generated Cypher without executing ---
    with Session(graph) as session:
        cypher, params = (
            session.query(Product)
            .where(
                (Product.category == "books")  # type: ignore[operator]
                & (Product.price < 50.0)
            )
            .order_by(Product.price)
            .limit(5)
            .build()
        )
        log.info("build() Cypher:\n%s\nparams: %s", cypher, params)

    # --- Multiple .where() calls are AND-combined ---
    with Session(graph) as session:
        multi_where = (
            session.query(Product)
            .where(Product.category == "books")
            .where(Product.active == True)  # noqa: E712
            .where(Product.stock > 0)
            .all()
        )
        log.info(
            "multi .where() (books, active, in-stock): %s",
            [p.name for p in multi_where],
        )

    # --- Aggregation: avg, sum, max ---
    with Session(graph) as session:
        avg_price = (
            session.query(Product)
            .aggregate(avg(Product.price).as_("avg_price"))
            .scalar()
        )
        total_stock = (
            session.query(Product)
            .aggregate(sum_(Product.stock).as_("total_stock"))
            .scalar()
        )
        max_price = (
            session.query(Product)
            .aggregate(max_(Product.price).as_("max_price"))
            .scalar()
        )
        log.info(
            "avg price=%.2f, total stock=%s, max price=%s",
            avg_price or 0.0,
            total_stock,
            max_price,
        )

    # --- count(DISTINCT field) ---
    with Session(graph) as session:
        distinct_cats = (
            session.query(Product)
            .aggregate(count(Product.category, distinct=True).as_("n"))
            .scalar()
        )
        log.info("count(DISTINCT category): %s", distinct_cats)


if __name__ == "__main__":
    run()
