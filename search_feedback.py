from dotenv import load_dotenv
from sqlalchemy import create_engine, text
import ollama
import os

load_dotenv()

engine = create_engine(os.environ["DATABASE_URL"])
ollama_client = ollama.Client(host="http://127.0.0.1:11434")

query = input("Search customer feedback: ").strip()

if not query:
    raise SystemExit("Please enter a search query.")

embedding = ollama_client.embed(
    model=os.environ["EMBED_MODEL"],
    input=query,
)["embeddings"][0]

sql = text("""
    SELECT
        fv.feedback_id,
        fv.feedback_text,
        fv.metadata,
        1 - (fv.embedding <=> CAST(:embedding AS vector)) AS similarity
    FROM feedback_vectors AS fv
    ORDER BY fv.embedding <=> CAST(:embedding AS vector)
    LIMIT 5
""")

with engine.connect() as connection:
    results = connection.execute(
        sql,
        {"embedding": str(embedding)},
    ).mappings().all()

print("\nMost relevant feedback:\n")

for result in results:
    print(f"Feedback ID: {result['feedback_id']}")
    print(f"Feedback: {result['feedback_text']}")
    print(f"Metadata: {result['metadata']}")
    print(f"Similarity: {result['similarity']:.3f}")
    print("-" * 60)

engine.dispose()