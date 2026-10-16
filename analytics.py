import os

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

engine = create_engine(os.environ["DATABASE_URL"])


def query_database(sql: str, params: dict | None = None) -> list[dict]:
    """Execute a read-only analytics query."""

    with engine.connect() as connection:
        with connection.begin():
            connection.execute(text("SET TRANSACTION READ ONLY"))

            results = (
                connection.execute(
                    text(sql),
                    params or {},
                )
                .mappings()
                .all()
            )

    return [dict(row) for row in results]


def get_business_overview() -> dict:
    """Calculate overall sales and profitability."""

    sql = """
        SELECT
            COUNT(*) AS sales_lines,
            COUNT(DISTINCT order_id) AS orders,
            COUNT(DISTINCT customer_id) AS customers,
            COALESCE(SUM(quantity), 0) AS units_sold,
            ROUND(COALESCE(SUM(line_total), 0)::numeric, 2) AS revenue,
            ROUND(COALESCE(SUM(line_cost), 0)::numeric, 2) AS cost,
            ROUND(
                (
                    COALESCE(SUM(line_total), 0)
                    - COALESCE(SUM(line_cost), 0)
                )::numeric,
                2
            ) AS gross_profit,
            ROUND(
                (
                    100.0
                    * (
                        COALESCE(SUM(line_total), 0)
                        - COALESCE(SUM(line_cost), 0)
                    )
                    / NULLIF(SUM(line_total), 0)
                )::numeric,
                2
            ) AS gross_margin_pct
        FROM order_items
    """

    results = query_database(sql)
    return results[0]


def get_top_products(limit: int = 5) -> list[dict]:
    """Rank products by revenue."""

    sql = """
        SELECT
            product_id,
            product_name,
            product_category,
            SUM(quantity) AS units_sold,
            ROUND(SUM(line_total)::numeric, 2) AS revenue,
            ROUND(SUM(line_total - line_cost)::numeric, 2) AS gross_profit
        FROM order_items
        GROUP BY product_id, product_name, product_category
        ORDER BY SUM(line_total) DESC
        LIMIT :limit
    """

    return query_database(sql, {"limit": limit})


def get_product_profitability(limit: int = 12) -> list[dict]:
    """Rank products by gross profit and calculate their margins."""

    sql = """
        SELECT
            product_id,
            product_name,
            product_category,
            SUM(quantity) AS units_sold,
            ROUND(SUM(line_total)::numeric, 2) AS revenue,
            ROUND(SUM(line_cost)::numeric, 2) AS cost,
            ROUND(
                (
                    SUM(line_total) - SUM(line_cost)
                )::numeric,
                2
            ) AS gross_profit,
            ROUND(
                (
                    100.0 * (
                        SUM(line_total) - SUM(line_cost)
                    ) / NULLIF(SUM(line_total), 0)
                )::numeric,
                2
            ) AS gross_margin_pct
        FROM order_items
        GROUP BY
            product_id,
            product_name,
            product_category
        ORDER BY
            SUM(line_total) - SUM(line_cost) DESC
        LIMIT :limit
    """

    return query_database(sql, {"limit": limit})


def get_customer_value(limit: int = 10) -> list[dict]:
    """Rank customers by recorded sales revenue."""

    sql = """
        SELECT
            oi.customer_id,
            c.customer_name,
            c.customer_segment,
            c.loyalty_tier,
            COUNT(DISTINCT oi.order_id) AS orders,
            ROUND(SUM(oi.line_total)::numeric, 2) AS revenue,
            ROUND(
                SUM(oi.line_total - oi.line_cost)::numeric,
                2
            ) AS gross_profit
        FROM order_items AS oi
        LEFT JOIN customers AS c
            ON c.customer_id = oi.customer_id
        GROUP BY
            oi.customer_id,
            c.customer_name,
            c.customer_segment,
            c.loyalty_tier
        ORDER BY SUM(oi.line_total) DESC
        LIMIT :limit
    """

    return query_database(sql, {"limit": limit})


def get_return_analysis() -> dict:
    """Analyze recorded returns and returned sales lines."""

    sql = """
        SELECT
            (SELECT COUNT(*) FROM returns)
                AS recorded_return_records,
            (SELECT COALESCE(SUM(quantity), 0) FROM returns)
                AS recorded_return_units,
            (SELECT COUNT(*) FROM order_items WHERE returned IS TRUE)
                AS returned_sales_lines,
            (SELECT COUNT(*) FROM order_items)
                AS total_sales_lines,
            ROUND(
                (
                    100.0 * (
                        SELECT COUNT(*)
                        FROM order_items
                        WHERE returned IS TRUE
                    )
                    / NULLIF(
                        (SELECT COUNT(*) FROM order_items),
                        0
                    )
                )::numeric,
                2
            ) AS returned_line_pct
    """

    results = query_database(sql)
    return results[0]


def get_feedback_summary() -> list[dict]:
    """Summarize feedback by sentiment."""

    sql = """
        SELECT
            sentiment,
            COUNT(*) AS feedback_count,
            ROUND(AVG(rating)::numeric, 2) AS average_rating
        FROM feedback
        GROUP BY sentiment
        ORDER BY feedback_count DESC
    """

    return query_database(sql)


def get_product_risk_analysis(limit: int = 12) -> list[dict]:
    """Combine product profitability, negative feedback, and returns."""

    sql = """
        WITH product_sales AS (
            SELECT
                product_id,
                SUM(quantity) AS units_sold,
                SUM(line_total) AS revenue,
                SUM(line_cost) AS cost
            FROM order_items
            GROUP BY product_id
        ),
        negative_feedback AS (
            SELECT
                metadata->>'product_id' AS product_id,
                COUNT(*) AS negative_feedback_count,
                ROUND(
                    AVG((metadata->>'rating')::numeric),
                    2
                ) AS average_negative_rating
            FROM feedback_vectors
            WHERE LOWER(metadata->>'sentiment') = 'negative'
            GROUP BY metadata->>'product_id'
        ),
        product_returns AS (
            SELECT
                product_id,
                COUNT(*) AS return_records,
                SUM(quantity) AS returned_units
            FROM returns
            GROUP BY product_id
        )
        SELECT
            p.product_id,
            p.product_name,
            p.category,
            COALESCE(s.units_sold, 0) AS units_sold,
            ROUND(COALESCE(s.revenue, 0)::numeric, 2) AS revenue,
            ROUND(COALESCE(s.cost, 0)::numeric, 2) AS cost,
            ROUND(
                (
                    COALESCE(s.revenue, 0)
                    - COALESCE(s.cost, 0)
                )::numeric,
                2
            ) AS gross_profit,
            COALESCE(f.negative_feedback_count, 0)
                AS negative_feedback_count,
            f.average_negative_rating,
            COALESCE(r.return_records, 0) AS return_records,
            COALESCE(r.returned_units, 0) AS returned_units,
            ROUND(
                100.0 * COALESCE(r.returned_units, 0)
                / NULLIF(s.units_sold, 0),
                2
            ) AS returned_unit_pct
        FROM products p
        LEFT JOIN product_sales s
            ON s.product_id = p.product_id
        LEFT JOIN negative_feedback f
            ON f.product_id = p.product_id
        LEFT JOIN product_returns r
            ON r.product_id = p.product_id
        ORDER BY
            COALESCE(f.negative_feedback_count, 0) DESC,
            COALESCE(r.return_records, 0) DESC,
            COALESCE(s.revenue, 0) DESC
        LIMIT :limit
    """

    return query_database(
        sql,
        {"limit": max(1, min(limit, 12))},
    )


def get_negative_feedback_by_product(limit: int = 5) -> list[dict]:
    """Rank products by negative feedback count."""

    sql = """
        SELECT
            metadata->>'product_id' AS product_id,
            metadata->>'product' AS product_name,
            COUNT(*) AS negative_feedback_count,
            ROUND(AVG((metadata->>'rating')::numeric), 2)
                AS average_negative_rating
        FROM feedback_vectors
        WHERE LOWER(metadata->>'sentiment') = 'negative'
        GROUP BY
            metadata->>'product_id',
            metadata->>'product'
        ORDER BY
            negative_feedback_count DESC,
            average_negative_rating ASC,
            product_name ASC
        LIMIT :limit
    """

    return query_database(
        sql,
        {"limit": max(1, min(limit, 12))},
    )


def get_product_complaint_themes(product_id: str) -> list[dict]:
    """Aggregate negative customer feedback by category."""

    sql = """
        SELECT
            category,
            COUNT(*) AS complaint_count,
            ROUND(AVG(rating)::numeric, 2) AS average_rating,
            ROUND(
                COUNT(*) * 100.0 /
                NULLIF(SUM(COUNT(*)) OVER (), 0),
                2
            ) AS percentage
        FROM feedback
        WHERE product_id = :product_id
          AND LOWER(sentiment) = 'negative'
        GROUP BY category
        ORDER BY complaint_count DESC, category
    """

    return query_database(sql, {"product_id": product_id})

def get_product_feedback(
    product_id: str | None = None,
) -> list[dict]:
    """Compare product sales with customer feedback."""

    params = {}
    sales_filter = ""
    feedback_filter = ""

    if product_id is not None:
        sales_filter = "WHERE product_id = :product_id"
        feedback_filter = "WHERE product_id = :product_id"
        params["product_id"] = product_id

    sql = f"""
        WITH product_sales AS (
            SELECT
                product_id,
                product_name,
                SUM(quantity) AS units_sold,
                ROUND(SUM(line_total)::numeric, 2) AS revenue
            FROM order_items
            {sales_filter}
            GROUP BY product_id, product_name
        ),
        product_feedback AS (
            SELECT
                product_id,
                COUNT(*) AS feedback_count,
                ROUND(AVG(rating)::numeric, 2) AS average_rating,
                COUNT(*) FILTER (
                    WHERE LOWER(sentiment) = 'negative'
                ) AS negative_feedback
            FROM feedback
            {feedback_filter}
            GROUP BY product_id
        )
        SELECT
            ps.product_id,
            ps.product_name,
            ps.units_sold,
            ps.revenue,
            COALESCE(pf.feedback_count, 0) AS feedback_count,
            pf.average_rating,
            COALESCE(pf.negative_feedback, 0) AS negative_feedback
        FROM product_sales AS ps
        LEFT JOIN product_feedback AS pf
            ON pf.product_id = ps.product_id
        ORDER BY ps.revenue DESC
    """

    return query_database(sql, params)


def main() -> None:
    reports = [
        ("BUSINESS OVERVIEW", get_business_overview),
        ("TOP PRODUCTS", get_top_products),
        ("TOP CUSTOMERS", get_customer_value),
        ("RETURN ANALYSIS", get_return_analysis),
        ("FEEDBACK SUMMARY", get_feedback_summary),
        ("PRODUCT SALES AND FEEDBACK", get_product_feedback),
        ("PRODUCT PROFITABILITY", get_product_profitability),
    ]

    for title, report_function in reports:
        print(f"\n{'=' * 65}")
        print(title)
        print("=" * 65)

        results = report_function()

        if isinstance(results, dict):
            print(results)
        else:
            for row in results:
                print(row)


if __name__ == "__main__":
    try:
        main()
    finally:
        engine.dispose()
