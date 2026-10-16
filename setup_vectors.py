import os

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

engine = create_engine(os.environ["DATABASE_URL"])

with engine.begin() as connection:
    connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

    connection.execute(text("""
        CREATE TABLE IF NOT EXISTS feedback_vectors (
            feedback_id TEXT PRIMARY KEY,
            feedback_text TEXT NOT NULL,
            embedding VECTOR(768) NOT NULL,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb
        )
    """))

print("PostgreSQL vector table is ready.")

engine.dispose()