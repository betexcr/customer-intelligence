import os

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

engine = create_engine(os.environ["DATABASE_URL"])

with engine.connect() as connection:
    result = connection.execute(
        text("""
            SELECT extname
            FROM pg_extension
            WHERE extname = 'vector'     
        """)
    ).scalar_one_or_none()
    
    if result:
        print("pgvector is installed")
    else:
        print("pgvector is not installed")
        
engine.dispose()