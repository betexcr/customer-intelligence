import os

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

engine = create_engine(os.environ["DATABASE_URL"])

tables = [
    "customers",
    "products",
    "orders",
    "sales",
    "order_items",
    "feedback",
    "returns",
]

with engine.connect() as connection:
    print("\n=== DATABASE VERIFICATION===")
    
    for table in tables:
        count = connection.execute(
            text(f'SELECT COUNT(*) FROM "{table}"')
        ).scalar_one()
        
        print("\n=== AVAILABLE TABLE COLUMNS ===")
        
        for table in tables:
            columns = connection.execute(
                text("""
                     SELECT column_name, data_type
                     FROM information_schema.columns
                     WHERE table_schema = 'public'
                        AND table_name = :table
                    ORDER BY ordinal_position
                     """),
                {"table": table}
            ).fetchall()
            
            print(f"\n{table}:")
            for column_name, data_type in columns:
                print(f" {column_name:<25} {data_type}")
                
engine.dispose()