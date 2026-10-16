# Customer Intelligence

A local customer intelligence and analytics assistant that combines PostgreSQL reporting with an Ollama-powered language model and semantic search over customer feedback.

The project analyzes sales, customers, products, orders, order items, returns, and feedback. It can answer business questions using read-only SQL analytics, compare product performance, investigate complaints, and retrieve relevant customer comments through vector similarity search.

## Features

- Business overview: sales lines, orders, customers, units, revenue, cost, gross profit, and gross margin.
- Product analytics: top products, units sold, revenue, gross profit, and gross margin.
- Customer value ranking based on recorded sales revenue.
- Return analysis using recorded return records, returned units, and sales lines marked as returned.
- Feedback summaries by sentiment and average rating.
- Product-level feedback and complaint themes.
- Product risk analysis combining negative feedback, returns, sales, and profitability.
- Product comparison ranked by negative feedback percentage, with return percentage and gross profit as tie-breakers.
- Semantic search over customer comments using Ollama embeddings and PostgreSQL `pgvector`.
- Read-only SQL execution for analytics queries.

## Technology

- Python 3.14+
- PostgreSQL 17 with `pgvector`
- SQLAlchemy and Psycopg
- Ollama for local chat and embedding models
- pandas for CSV data loading
- `uv` for Python project and dependency management

## Prerequisites

Install the following before setup:

1. Python 3.14 or newer.
2. [`uv`](https://docs.astral.sh/uv/).
3. Docker Desktop (or Docker Engine with Compose).
4. [Ollama](https://ollama.com/) running locally.

Pull the models configured for this project:

```powershell
ollama pull qwen2.5:3b
ollama pull nomic-embed-text
```

The chat and embedding models can be changed through `.env`.

## Setup

Run these commands from the project root (`customer-intelligence`).

### 1. Install Python dependencies

```powershell
uv sync
```

### 2. Configure environment variables

Copy the example file:

```powershell
Copy-Item .env.example .env
```

The example configuration is:

```dotenv
DATABASE_URL=postgresql+psycopg://app:local_dev_password@localhost:5432/customer_intelligence
OLLAMA_HOST=http://127.0.0.1:11434
CHAT_MODEL=qwen2.5:3b
EMBED_MODEL=nomic-embed-text
```

These values are intended for local development. Do not use the example database password in a publicly accessible or production environment. Keep `.env` out of version control.

### 3. Start PostgreSQL with pgvector

```powershell
docker compose up -d
```

Check container status:

```powershell
docker compose ps
```

The Compose service uses the `pgvector/pgvector:pg17` image and exposes PostgreSQL on port `5432`. Its data is stored in the `postgres_data` Docker volume.

### 4. Load the CSV datasets

```powershell
uv run python .\load_data.py
```

This loads the project CSV files into PostgreSQL:

- `customers.csv`
- `products.csv`
- `orders.csv`
- `sales.csv`
- `order_items.csv`
- `feedback.csv`
- `returns.csv`

**Warning:** `load_data.py` uses `if_exists="replace"` for these tables. Running it again replaces the existing tables with the CSV contents. Back up any data you need before rerunning it.

### 5. Create the vector table

```powershell
uv run python .\setup_vectors.py
```

This enables the PostgreSQL `vector` extension and creates `feedback_vectors` with a 768-dimensional vector column.

### 6. Generate feedback embeddings

Make sure Ollama is running, then execute:

```powershell
uv run python .\embed_feedback.py
```

This embeds each feedback comment with the configured embedding model and stores the vectors and searchable metadata in PostgreSQL. The configured model must produce 768-dimensional embeddings; `nomic-embed-text` is the default.

### 7. Verify the data (optional)

The repository includes helper scripts for inspecting and validating the loaded data and vector setup:

```powershell
uv run python .\verify_data.py
uv run python .\inspect_database.py
uv run python .\check_vector.py
```

Run these individually as needed.

## Run the assistant

With PostgreSQL running, the CSV data loaded, feedback embeddings generated, and Ollama available:

```powershell
uv run python .\customer_assistant.py
```

Ask questions in the interactive prompt, for example:

```text
What is our overall gross profit and margin?
Which products generate the most revenue?
Compare all products by negative feedback percentage, returns, gross profit, and gross margin.
Which products have the highest returned-unit percentage?
What are customers complaining about with the Mouse?
Search feedback for shipping delays and unclear tracking updates.
```

Type `exit` or `quit` to stop the assistant.

## Other scripts

| Script | Purpose |
|---|---|
| `analytics.py` | Read-only SQL analytics functions and reporting entry point |
| `customer_assistant.py` | Interactive language-model assistant with approved analytics tools |
| `load_data.py` | Loads CSV datasets into PostgreSQL |
| `setup_vectors.py` | Enables pgvector and creates the feedback vector table |
| `embed_feedback.py` | Creates and upserts embeddings for customer feedback |
| `search_feedback.py` | Standalone semantic search over feedback |
| `analyze_feedback.py` | Feedback analysis utility |
| `analyze_sales.py` | Sales analysis utility |
| `inspect_database.py` | Database inspection utility |
| `verify_data.py` | Data validation utility |
| `check_vector.py` | Vector setup/check utility |
| `main.py` | Minimal project entry point |

## How product metrics are calculated

- **Revenue:** Sum of recorded `order_items.line_total`.
- **Cost:** Sum of recorded `order_items.line_cost`.
- **Gross profit:** Revenue minus cost; operating expenses are not included.
- **Gross margin:** Gross profit divided by revenue, expressed as a percentage.
- **Negative feedback percentage:** Negative feedback records divided by all feedback records for the product.
- **Returned-unit percentage:** Recorded returned units divided by units sold.

These measures are useful investigation signals, not proof of root cause. In particular, the project does not assume that negative feedback caused a return unless the data directly establishes that relationship. Feedback percentages are based on the available feedback records and should not automatically be interpreted as representative of every customer.

## Database access

Open a PostgreSQL shell inside the container:

```powershell
docker exec -it customer-intelligence-db psql -U app -d customer_intelligence
```

Exit `psql` with:

```sql
\q
```

Stop PostgreSQL when finished:

```powershell
docker compose down
```

The named Docker volume preserves database files when the container is stopped or removed. To remove the volume and its data as well, use `docker compose down -v`—this is destructive.

## Troubleshooting

- **Database connection error:** Confirm Docker is running and `docker compose ps` shows PostgreSQL as healthy. Verify `DATABASE_URL` in `.env`.
- **Ollama connection error:** Confirm Ollama is running and reachable at `http://127.0.0.1:11434`.
- **Model not found:** Run `ollama pull qwen2.5:3b` and `ollama pull nomic-embed-text`, or pull the model names configured in `.env`.
- **Embedding dimension mismatch:** Use an embedding model that returns 768 dimensions, or update the vector schema and embedding implementation together.
- **No semantic search results:** Confirm the feedback data was loaded, `setup_vectors.py` was run, and `embed_feedback.py` completed successfully.
- **Missing environment variable:** Ensure `.env` exists in the project root and contains the required `DATABASE_URL`, `CHAT_MODEL`, and `EMBED_MODEL` values.

## Security and limitations

- Intended for local development and analysis, not configured as a production service.
- The assistant exposes an allowlist of analytics tools and uses read-only database queries for analytics.
- The local database credentials are development credentials only. Use secrets management, least-privilege database roles, backups, and appropriate access controls before deploying in a shared environment.
- LLM responses should be checked against the underlying metrics when making important business decisions.
