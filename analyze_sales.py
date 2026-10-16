import os

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

engine = create_engine(os.environ["DATABASE_URL"])

query = text("""
    WITH product_sales AS (
        SELECT
            product_id,
            COUNT(DISTINCT order_id) AS orders_count,
            SUM(quantity) AS units_sold,
            SUM(quantity * unit_price) AS gross_sales
        FROM order_items
        GROUP BY product_id
    ),
    product_feedback AS (
        SELECT
            product_id,
            COUNT(*) AS feedback_count,
            AVG(rating) AS average_rating,
            COUNT(*) FILTER (
                WHERE sentiment = 'Negative'
            ) AS negative_feedback
        FROM feedback
        GROUP BY product_id
    )
    SELECT
        p.product_id,
        p.product_name,
        p.category,
        COALESCE(s.orders_count, 0) AS orders_count,
        COALESCE(s.units_sold, 0) AS units_sold,
        ROUND(s.gross_sales::numeric, 2) AS gross_sales,
        ROUND(f.average_rating::numeric, 2) AS average_rating,
        COALESCE(f.feedback_count, 0) AS feedback_count,
        COALESCE(f.negative_feedback, 0) AS negative_feedback
    FROM products p
    LEFT JOIN product_sales s
        ON p.product_id = s.product_id
    LEFT JOIN product_feedback f
        ON p.product_id = f.product_id
    ORDER BY s.gross_sales DESC NULLS LAST;
""")

with engine.connect() as connection:
    df = pd.read_sql(query, connection)
    
print("\n=== PRODUCT SALES AND FEEDBACK ===")
print(df.to_string(index=False))

engine.dispose()