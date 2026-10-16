import os

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

DATABASE_URL = os.environ.get("DATABASE_URL")
engine = create_engine(DATABASE_URL)

datasets = {
    "customers": "customers.csv",
    "products": "products.csv",
    "orders": "orders.csv",
    "sales": "sales.csv",
    "order_items": "order_items.csv",
    "feedback": "feedback.csv",
    "returns": "returns.csv",
}

with engine.begin() as connection:
    connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))

for table_name, filename in datasets.items():
    df = pd.read_csv(filename)

    df.to_sql(
        name=table_name,
        con=engine,
        if_exists="replace",
        index=False,
        chunksize=500,
        method="multi",
    )

    print(f"Loaded {len(df)} rows into {table_name}")

engine.dispose()
