"""Example 7 — Query builder: basics.

Demonstrates every foundational feature of the fluent QueryBuilder API:
  - Equality, inequality, numeric comparisons
  - String predicates: contains(), startswith(), endswith(), matches()
  - Null checks: is_null(), is_not_null()
  - Membership: in_(), not_in_()
  - Boolean composition: & (AND), | (OR), ~ (NOT)
  - order_by(), limit(), skip(), distinct()
  - Session execution: session.scalars(), session.scalar(), session.count(),
    session.all_rows(), session.all_with_edges()
  - Projection: project() → session.all_rows()
  - build() — inspect generated Cypher without executing

Run against FalkorDB (embedded):
    uv run python examples/orm/07_query_builder_basics.py

Run against FalkorDB (live server):
    FALKORDB_HOST=localhost FALKORDB_PORT=6379 uv run python examples/orm/07_query_builder_basics.py

Run against ArcadeDB (via Bolt):
    RUNIC_BACKEND=arcadedb ARCADEDB_HOST=localhost ARCADEDB_DATABASE=runic_examples \\
        uv run python examples/orm/07_query_builder_basics.py
"""

from __future__ import annotations

import logging
import os
from typing import Any

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

from runic.ogm import (  # noqa: E402
    Field,
    Node,
    Session,
    avg,
    count,
    max_,
    min_,
    select,
    sum_,
)
from runic.ogm.driver import GraphDriver  # noqa: E402
from runic.ogm.driver.factory import create_driver  # noqa: E402
from runic.ogm.driver.falkordb import FalkorDBDriver  # noqa: E402

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


def _create_driver() -> GraphDriver:
    backend = os.getenv("RUNIC_BACKEND", "falkordb")
    if backend == "falkordb":
        host = os.getenv("FALKORDB_HOST", "")
        if host:
            return create_driver(
                "falkordb",
                host=host,
                port=int(os.getenv("FALKORDB_PORT", "6379")),
                graph="example_qb_basics",
            )
        from redislite import FalkorDB  # type: ignore[import-untyped]

        db = FalkorDB(protocol=2)
        return FalkorDBDriver(db.select_graph("example_qb_basics"))
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
        products: list[Product] = [
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
    with Session(driver) as session:
        books: list[Product] = session.scalars(
            select(Product).where(Product.category == "books")
        )
        log.info("category == 'books': %s", [p.name for p in books])

    # --- Inequality filter ---
    with Session(driver) as session:
        not_books: list[Product] = session.scalars(
            select(Product).where(Product.category != "books")
        )
        log.info("category != 'books': %s", [p.name for p in not_books])

    # --- Numeric comparison: greater-than ---
    with Session(driver) as session:
        expensive: list[Product] = session.scalars(
            select(Product)
            .where(Product.price > 100.0)
            .order_by(Product.price, desc=True)
        )
        log.info("price > 100: %s", [(p.name, p.price) for p in expensive])

    # --- Numeric comparison: less-than-or-equal ---
    with Session(driver) as session:
        cheap: list[Product] = session.scalars(
            select(Product).where(Product.price <= 40.0)
        )
        log.info("price <= 40: %s", [p.name for p in cheap])

    # --- String predicate: contains() ---
    with Session(driver) as session:
        graph_products: list[Product] = session.scalars(
            select(Product).where(Product.name.contains("Graph"))  # type: ignore[attr-defined]
        )
        log.info("name.contains('Graph'): %s", [p.name for p in graph_products])

    # --- String predicate: startswith() ---
    with Session(driver) as session:
        adv: list[Product] = session.scalars(
            select(Product).where(Product.name.startswith("Advanced"))  # type: ignore[attr-defined]
        )
        log.info("name.startswith('Advanced'): %s", [p.name for p in adv])

    # --- String predicate: endswith() ---
    with Session(driver) as session:
        kits: list[Product] = session.scalars(
            select(Product).where(Product.name.endswith("Kit"))  # type: ignore[attr-defined]
        )
        log.info("name.endswith('Kit'): %s", [p.name for p in kits])

    # --- String predicate: matches() (regex) — requires live FalkorDB v4+ ---
    # NOTE: =~ regex is not supported by the embedded redislite backend.
    # Uncomment when running against a live FalkorDB instance:
    # with Session(driver) as session:
    #     regex_match = session.scalars(
    #         select(Product).where(Product.name.matches(".*Graph.*"))  # type: ignore[attr-defined]
    #     )
    #     log.info("name.matches('.*Graph.*'): %s", [p.name for p in regex_match])

    # --- Null check: is_null() ---
    with Session(driver) as session:
        no_sku: list[Product] = session.scalars(
            select(Product).where(Product.sku.is_null())  # type: ignore[attr-defined]
        )
        log.info("sku IS NULL: %s", [p.name for p in no_sku])

    # --- Null check: is_not_null() ---
    with Session(driver) as session:
        has_sku: list[Product] = session.scalars(
            select(Product).where(Product.sku.is_not_null())  # type: ignore[attr-defined]
        )
        log.info("sku IS NOT NULL: %s", [p.name for p in has_sku])

    # --- Membership: in_() ---
    with Session(driver) as session:
        selected: list[Product] = session.scalars(
            select(Product)
            .where(Product.id.in_(["p1", "p3", "p5"]))  # type: ignore[attr-defined]
            .order_by(Product.id)
        )
        log.info("id in ['p1','p3','p5']: %s", [p.id for p in selected])

    # --- Membership: not_in_() ---
    with Session(driver) as session:
        excluded: list[Product] = session.scalars(
            select(Product)
            .where(Product.category.not_in_(["hardware"]))  # type: ignore[attr-defined]
            .order_by(Product.id)
        )
        log.info("category not_in ['hardware']: %s", [p.id for p in excluded])

    # --- Boolean AND: & operator ---
    with Session(driver) as session:
        active_books: list[Product] = session.scalars(
            select(Product).where(
                (Product.category == "books")  # type: ignore[operator]
                & (Product.active == True)  # noqa: E712
            )
        )
        log.info("category='books' AND active=True: %s", [p.name for p in active_books])

    # --- Boolean OR: | operator ---
    with Session(driver) as session:
        books_or_courses: list[Product] = session.scalars(
            select(Product).where(
                (Product.category == "books")  # type: ignore[operator]
                | (Product.category == "courses")
            )
        )
        log.info(
            "category='books' OR 'courses': %s", [p.name for p in books_or_courses]
        )

    # --- Boolean NOT: ~ operator ---
    with Session(driver) as session:
        not_active: list[Product] = session.scalars(
            select(Product).where(~(Product.active == True))  # noqa: E712
        )
        log.info("NOT active=True: %s", [p.name for p in not_active])

    # --- Three-condition compound: & chained ---
    with Session(driver) as session:
        in_stock_books: list[Product] = session.scalars(
            select(Product).where(
                (Product.category == "books")  # type: ignore[operator]
                & (Product.active == True)  # noqa: E712
                & (Product.stock > 0)
            )
        )
        log.info("books AND active AND stock>0: %s", [p.name for p in in_stock_books])

    # --- order_by ASC (default) ---
    with Session(driver) as session:
        by_price_asc: list[Product] = session.scalars(
            select(Product).order_by(Product.price)
        )
        log.info("ORDER BY price ASC: %s", [p.price for p in by_price_asc])

    # --- order_by DESC ---
    with Session(driver) as session:
        by_price_desc: list[Product] = session.scalars(
            select(Product).order_by(Product.price, desc=True)
        )
        log.info("ORDER BY price DESC: %s", [p.price for p in by_price_desc])

    # --- limit() ---
    with Session(driver) as session:
        top2: list[Product] = session.scalars(
            select(Product).order_by(Product.price, desc=True).limit(2)
        )
        log.info("LIMIT 2 by price desc: %s", [p.name for p in top2])

    # --- skip() + limit() (manual pagination) ---
    with Session(driver) as session:
        page2: list[Product] = session.scalars(
            select(Product).order_by(Product.id).skip(2).limit(2)
        )
        log.info("SKIP 2 LIMIT 2: %s", [p.id for p in page2])

    # --- distinct() ---
    with Session(driver) as session:
        rows_cats = session.all_rows(
            select(Product).project(Product.category).distinct()
        )
        cats: list[str] = [r["n.category"] for r in rows_cats]
        log.info("DISTINCT categories: %s", sorted(cats))

    # --- Terminal: count() ---
    with Session(driver) as session:
        total: int = session.count(select(Product))
        log.info("count(*): %d", total)

    # --- Terminal: count() with filter ---
    with Session(driver) as session:
        active_count: int = session.count(
            select(Product).where(Product.active == True)  # noqa: E712
        )
        log.info("count where active=True: %d", active_count)

    # --- Terminal: scalar() — first entity or None ---
    with Session(driver) as session:
        p: Product | None = session.scalar(select(Product).where(Product.id == "p1"))
        log.info("one() p1: %s", p and p.name)

    # --- Terminal: scalar() — no match returns None ---
    with Session(driver) as session:
        missing: Product | None = session.scalar(
            select(Product).where(Product.id == "NOPE")
        )
        log.info("one() no match: %s", missing)

    # --- Aggregate: min() — single aggregation value via all_rows() ---
    with Session(driver) as session:
        rows_min = session.all_rows(
            select(Product).aggregate(min_(Product.price).as_("min_price"))
        )
        lowest_price: float | None = rows_min[0]["min_price"] if rows_min else None
        log.info("scalar() min price: %s", lowest_price)

    # --- Projection: project() → all_rows(), extract first column ---
    with Session(driver) as session:
        rows_ids = session.all_rows(
            select(Product).order_by(Product.id).project(Product.id)
        )
        all_ids: list[str] = [r["n.id"] for r in rows_ids]
        log.info("scalars() all ids: %s", all_ids)

    # --- project() → all_rows() — multi-field projection as dicts ---
    with Session(driver) as session:
        rows: list[dict[str, Any]] = session.all_rows(
            select(Product)
            .where(Product.active == True)  # noqa: E712
            .order_by(Product.price)
            .project(Product.name, Product.price)
        )
        log.info("project all_rows: %s", rows)

    # --- build() — inspect generated Cypher without executing ---
    cypher: str
    params: dict[str, Any]
    cypher, params = (
        select(Product)
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
    with Session(driver) as session:
        multi_where: list[Product] = session.scalars(
            select(Product)
            .where(Product.category == "books")
            .where(Product.active == True)  # noqa: E712
            .where(Product.stock > 0)
        )
        log.info(
            "multi .where() (books, active, in-stock): %s",
            [p.name for p in multi_where],
        )

    # --- Aggregation: avg, sum, max ---
    with Session(driver) as session:
        rows_avg = session.all_rows(
            select(Product).aggregate(avg(Product.price).as_("avg_price"))
        )
        avg_price: float | None = rows_avg[0]["avg_price"] if rows_avg else None
        rows_sum = session.all_rows(
            select(Product).aggregate(sum_(Product.stock).as_("total_stock"))
        )
        total_stock: int | None = rows_sum[0]["total_stock"] if rows_sum else None
        rows_max = session.all_rows(
            select(Product).aggregate(max_(Product.price).as_("max_price"))
        )
        max_price: float | None = rows_max[0]["max_price"] if rows_max else None
        log.info(
            "avg price=%.2f, total stock=%s, max price=%s",
            avg_price or 0.0,
            total_stock,
            max_price,
        )

    # --- count(DISTINCT field) ---
    with Session(driver) as session:
        rows_dc = session.all_rows(
            select(Product).aggregate(
                count(Product.category, distinct=True).as_("distinct_cats")
            )
        )
        distinct_cats: int | None = rows_dc[0]["distinct_cats"] if rows_dc else None
        log.info("count(DISTINCT category): %s", distinct_cats)

    driver.close()


if __name__ == "__main__":
    run()
