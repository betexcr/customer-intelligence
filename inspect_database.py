import os

from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect, text

load_dotenv()

engine = create_engine(os.environ["DATABASE_URL"])


def main():
    inspector = inspect(engine)
    tables = inspector.get_table_names()

    print("DATABASE SCHEMA")
    print("=" * 60)

    with engine.connect() as connection:
        for table in tables:
            columns = inspector.get_columns(table)

            count_query = text(
                f'SELECT COUNT(*) FROM "{table}"'
            )
            row_count = connection.execute(count_query).scalar_one()

            print(f"\nTable: {table}")
            print(f"Rows: {row_count}")
            print("-" * 40)

            for column in columns:
                print(
                    f"  {column['name']:<25} "
                    f"{column['type']}"
                )

    print("\nSchema inspection complete.")
    engine.dispose()


if __name__ == "__main__":
    main()