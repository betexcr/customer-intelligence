import json
import os

import ollama
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

DATABASE_URL = os.environ["DATABASE_URL"]
OLLAMA_HOST = "http://127.0.0.1:11434"

engine = create_engine(DATABASE_URL)

ollama_client = ollama.Client(
    host=OLLAMA_HOST,
    timeout=120
)


def embed(text_to_embed: str) -> list[float]:
    """Generate a 768-dimensional embedding using Ollama."""
    response = ollama_client.embed(
        model=os.environ["EMBED_MODEL"],
        input=text_to_embed,
    )
    return response["embeddings"][0]


def main():
    # Read feedback records from PostgreSQL.
    with engine.connect() as connection:
        rows = connection.execute(
            text("""
                SELECT
                    feedback_id,
                    feedback_text,
                    order_id,
                    customer_id,
                    product_id,
                    product,
                    category,
                    sentiment,
                    rating
                FROM feedback
                ORDER BY feedback_id
            """)
        ).mappings().all()
    test_response = ollama_client.embed(
        model=os.environ["EMBED_MODEL"],
        input="Customer feedback connection test",
    )

    print(
        "Ollama connected successfully.",
        f"Embedding dimensions: {len(test_response['embeddings'][0])}",
    )
    print(f"Found {len(rows)} feedback records.")

    if not rows:
        print("No feedback records found.")
        return

    # Generate embeddings and store them in PostgreSQL.
    with engine.begin() as connection:
        for index, row in enumerate(rows, start=1):
            feedback_text = str(row["feedback_text"]).strip()

            if not feedback_text:
                print(
                    f"Skipping empty feedback: "
                    f"{row['feedback_id']}"
                )
                continue

            vector = embed(feedback_text)

            if len(vector) != 768:
                raise ValueError(
                    f"Expected 768 dimensions, got {len(vector)}"
                )

            metadata = {
                "order_id": str(row["order_id"]),
                "customer_id": str(row["customer_id"]),
                "product_id": str(row["product_id"]),
                "product": str(row["product"]),
                "category": str(row["category"]),
                "sentiment": str(row["sentiment"]),
                "rating": int(row["rating"]),
            }

            connection.execute(
                text("""
                    INSERT INTO feedback_vectors (
                        feedback_id,
                        feedback_text,
                        embedding,
                        metadata
                    )
                    VALUES (
                        :feedback_id,
                        :feedback_text,
                        CAST(:embedding AS vector),
                        CAST(:metadata AS jsonb)
                    )
                    ON CONFLICT (feedback_id)
                    DO UPDATE SET
                        feedback_text = EXCLUDED.feedback_text,
                        embedding = EXCLUDED.embedding,
                        metadata = EXCLUDED.metadata
                """),
                {
                    "feedback_id": str(row["feedback_id"]),
                    "feedback_text": feedback_text,
                    "embedding": json.dumps(vector),
                    "metadata": json.dumps(metadata),
                },
            )

            if index % 25 == 0 or index == len(rows):
                print(f"Processed {index}/{len(rows)} records")

    print("All feedback embeddings stored successfully.")


if __name__ == "__main__":
    try:
        main()
    finally:
        engine.dispose()