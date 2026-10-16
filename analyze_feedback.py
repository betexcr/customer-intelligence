import os

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

engine = create_engine(os.environ["DATABASE_URL"])

query = text("""
    SELECT
        product,
        category,
        COUNT(*) as feedback_count,
        ROUND(AVG(rating)::numeric,2) AS average_rating,
        
        COUNT (*) FILTER (
            WHERE sentiment='Positive'
        ) AS positive_count,
    
        COUNT (*) FILTER (
            WHERE sentiment='Neutral'
        ) AS neutral_count,    
        
        
        COUNT (*) FILTER (
            WHERE sentiment='Negative'
        ) AS negative_count
        
    FROM feedback
    
    GROUP BY product, category
    
    ORDER BY negative_count DESC, feedback_count DESC;
""")

with engine.connect() as connection:
    df = pd.read_sql(query, connection)
    
print("\n=== CUSTOMER FEEDBACK ANALYSIS ===")
print(df.to_string(index=False))

print("\n=== OVERALL METRICS ===")

with engine.connect() as connection:
    overall = pd.read_sql(
        text("""
            SELECT
                COUNT(*) AS total_feedback,
                ROUND(AVG(rating)::numeric, 2) AS average_rating,
                COUNT(*) FILTER(
                    WHERE sentiment = 'Negative'
                ) AS negative_feedback
            FROM feedback;
        """),
        connection
    )
    
print(overall.to_string(index=False))

print("\n=== LOWEST RATED PRODUCTS ===")

product_summary = (
    df.groupby("product")
    .agg(
        total_feedback=("feedback_count", "sum"),
        average_rating=("average_rating", "mean"),
        negative_feedback=("negative_count", "sum"),
    ).sort_values("average_rating")
)
    
print(product_summary.to_string())

engine.dispose()