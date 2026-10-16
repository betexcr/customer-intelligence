import json
import os
from decimal import Decimal
from typing import Any

import ollama
from dotenv import load_dotenv
from sqlalchemy import text

from analytics import (
    engine,
    get_business_overview,
    get_top_products,
    get_customer_value,
    get_return_analysis,
    get_feedback_summary,
    get_product_feedback,
    get_product_profitability,
    get_product_risk_analysis,
    get_product_complaint_themes,
    query_database,
)

load_dotenv()

CHAT_MODEL = os.environ["CHAT_MODEL"]
EMBED_MODEL = os.environ["EMBED_MODEL"]
OLLAMA_HOST = "http://127.0.0.1:11434"

MAX_TOOL_ROUNDS = 8
MAX_FEEDBACK_RESULTS = 5

client = ollama.Client(host=OLLAMA_HOST)


def json_serializer(value: Any) -> Any:
    """Convert database values to JSON-compatible values."""

    if isinstance(value, Decimal):
        return float(value)

    if hasattr(value, "isoformat"):
        return value.isoformat()

    raise TypeError(f"Cannot serialize {type(value).__name__}")


def search_feedback(
    question: str,
    limit: int = MAX_FEEDBACK_RESULTS,
    product_id: str | None = None,
    sentiment: str | None = None,
) -> list[dict]:
    """Retrieve semantically relevant feedback with optional filters."""

    if not question.strip():
        raise ValueError("A non-empty feedback query is required.")

    embedding = client.embed(
        model=EMBED_MODEL,
        input=question,
    )[
        "embeddings"
    ][0]

    filters = []
    params = {
        "embedding": str(embedding),
        "limit": max(1, min(limit, 10)),
    }

    if product_id:
        filters.append("metadata->>'product_id' = :product_id")
        params["product_id"] = product_id

    if sentiment:
        filters.append("LOWER(metadata->>'sentiment') = :sentiment")
        params["sentiment"] = sentiment.lower()

    where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""

    sql = f"""
        SELECT
            feedback_id,
            feedback_text,
            metadata,
            1 - (
                embedding <=> CAST(:embedding AS vector)
            ) AS similarity
        FROM feedback_vectors
        {where_clause}
        ORDER BY embedding <=> CAST(:embedding AS vector)
        LIMIT :limit
    """

    return query_database(sql, params)


def compare_products() -> str:
    """Compare product feedback, profitability, and returns."""

    # Retrieve existing analytics.
    sales_feedback = get_product_feedback()
    profitability = get_product_profitability(limit=12)
    risk_analysis = get_product_risk_analysis(limit=12)

    # Count all negative feedback records per product.
    negative_feedback = query_database(
        """
        SELECT
            product_id,
            COUNT(*) AS negative_count
        FROM feedback
        WHERE LOWER(sentiment) = 'negative'
        GROUP BY product_id
        """
    )

    # Index results by product ID for reliable joins.
    feedback_by_id = {
        row["product_id"]: row
        for row in sales_feedback
    }

    profit_by_id = {
        row["product_id"]: row
        for row in profitability
    }

    risk_by_id = {
        row["product_id"]: row
        for row in risk_analysis
    }

    negative_by_id = {
        row["product_id"]: row["negative_count"]
        for row in negative_feedback
    }

    product_ids = set(feedback_by_id)

    if not product_ids:
        return "No product analytics are available."

    rows = []

    for product_id in product_ids:
        feedback = feedback_by_id.get(product_id, {})
        profit = profit_by_id.get(product_id, {})
        risk = risk_by_id.get(product_id, {})

        feedback_count = int(feedback.get("feedback_count") or 0)
        negative_count = int(
            negative_by_id.get(product_id, 0)
        )

        units_sold = int(feedback.get("units_sold") or 0)
        returned_units = int(risk.get("returned_units") or 0)

        # Negative feedback as a percentage of all feedback.
        negative_pct = (
            negative_count / feedback_count * 100
            if feedback_count
            else 0.0
        )

        # Use the existing return metric where available.
        returned_unit_pct = risk.get("returned_unit_pct")

        if returned_unit_pct is None:
            returned_unit_pct = (
                returned_units / units_sold * 100
                if units_sold
                else 0.0
            )

        rows.append({
            "product_id": product_id,
            "product_name": feedback.get(
                "product_name",
                profit.get("product_name", product_id),
            ),
            "units_sold": units_sold,
            "feedback_count": feedback_count,
            "negative_count": negative_count,
            "negative_pct": negative_pct,
            "average_rating": feedback.get("average_rating"),
            "revenue": profit.get("revenue"),
            "gross_profit": profit.get("gross_profit"),
            "gross_margin_pct": profit.get("gross_margin_pct"),
            "return_records": risk.get("return_records", 0),
            "returned_units": returned_units,
            "returned_unit_pct": float(returned_unit_pct),
        })

    # Prioritize by negative feedback volume, then return percentage.
    # Rank by negative feedback percentage, then return percentage.
    rows.sort(
        key=lambda row: (
            -row["negative_pct"],
            -row["returned_unit_pct"],
            -float(row["gross_profit"] or 0),
        )
    )

    lines = [
        "PRODUCT COMPARISON",
        "Ranked by negative feedback percentage, then return percentage and gross profit.",
        "",
        (
            f"{'Product':<18} {'Units':>6} {'Feedback':>9} "
            f"{'Negative':>9} {'Neg %':>7} {'Rating':>7} "
            f"{'Gross Profit':>14} {'Margin':>8} {'Return %':>9}"
        ),
        "-" * 103,
    ]

    for row in rows:
        rating = (
            f"{row['average_rating']:.2f}"
            if row["average_rating"] is not None
            else "N/A"
        )

        gross_profit = row["gross_profit"]
        gross_profit_text = (
            f"${gross_profit:,.2f}"
            if gross_profit is not None
            else "N/A"
        )

        margin = row["gross_margin_pct"]
        margin_text = (
            f"{margin:.2f}%"
            if margin is not None
            else "N/A"
        )

        lines.append(
            f"{row['product_name']:<18} "
            f"{row['units_sold']:>6} "
            f"{row['feedback_count']:>9} "
            f"{row['negative_count']:>9} "
            f"{row['negative_pct']:>6.2f}% "
            f"{rating:>7} "
            f"{gross_profit_text:>14} "
            f"{margin_text:>8} "
            f"{row['returned_unit_pct']:>8.2f}%"
        )

    # Identify the products with the highest negative feedback percentage.
    highest_negative_pct = max(
        rows,
        key=lambda row: row["negative_pct"],
    )

    highest_negative_count = max(
        rows,
        key=lambda row: row["negative_count"],
    )
    highest_return = max(
        rows,
        key=lambda row: row["returned_unit_pct"],
    )

    lines.extend([
        "",
        "OBSERVATIONS",
        (
            f"- Highest negative feedback percentage: "
            f"{highest_negative_pct['product_name']} "
            f"({highest_negative_pct['negative_pct']:.2f}%)."
        ),
        (
            f"- Highest negative feedback count: "
            f"{highest_negative_count['product_name']} "
            f"({highest_negative_count['negative_count']} records)."
        ),
        (
            f"- Highest returned-unit percentage: "
            f"{highest_return['product_name']} "
            f"({highest_return['returned_unit_pct']:.2f}%)."
        ),
        "",
        "METRIC DEFINITIONS",
        "- Negative % = negative feedback / all feedback for that product.",
        "- Return % = returned units / units sold.",
        "- Gross profit excludes operating expenses.",
        "- Rankings identify investigation candidates, not proven root causes.",
    ])

    return "\n".join(lines)

# Explicit allowlist: the model cannot execute arbitrary SQL or Python.
TOOL_FUNCTIONS = {
    "get_business_overview": get_business_overview,
    "get_top_products": get_top_products,
    "get_customer_value": get_customer_value,
    "get_return_analysis": get_return_analysis,
    "get_feedback_summary": get_feedback_summary,
    "get_product_feedback": get_product_feedback,
    "get_product_profitability": get_product_profitability,
    "get_product_complaint_themes": get_product_complaint_themes,
    "get_product_risk_analysis": get_product_risk_analysis,
    "compare_products": compare_products,
    "search_customer_feedback": search_feedback
}

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "compare_products",
            "description": (
                "Compare all products by negative feedback, average rating, "
                "sales volume, gross profitability, and returned-unit percentage."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_product_complaint_themes",
            "description": (
                "Get counts, percentages, and average ratings for negative "
                "feedback categories for a specific product."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "product_id": {
                        "type": "string",
                        "description": "Product ID, such as PROD-007.",
                    }
                },
                "required": ["product_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_business_overview",
            "description": (
                "Get overall business performance, including revenue, "
                "cost, gross profit, margin, orders, customers, and units."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_product_profitability",
            "description": (
                "Analyze profitability across all products, including "
                "revenue, cost, gross profit, and gross margin. Use this "
                "to identify the least profitable products, lowest margins, "
                "and products operating at a gross loss."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Number of products to return, from 1 to 12.",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_product_risk_analysis",
            "description": (
                "Analyze product business risk using negative customer feedback, "
                "average negative ratings, return records, returned units, "
                "returned-unit percentages, revenue, cost, and gross profit. "
                "Use this when asked which products pose the highest risk, "
                "combine customer complaints with returns, or prioritize "
                "products for investigation."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Number of products to return, from 1 to 12.",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_top_products",
            "description": (
                "Rank products by revenue and return units sold, "
                "revenue, and gross profit. Use for product sales "
                "performance and best-selling product questions."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Number of products to return, from 1 to 12.",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_customer_value",
            "description": (
                "Rank customers by recorded sales revenue. Returns "
                "customer segment, loyalty tier, order count, revenue, "
                "and gross profit."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Number of customers to return, from 1 to 60.",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_return_analysis",
            "description": (
                "Get recorded return counts, returned units, returned "
                "sales lines, total sales lines, and returned-line percentage."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_feedback_summary",
            "description": (
                "Summarize customer feedback by sentiment, including "
                "feedback counts and average ratings."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_product_feedback",
            "description": (
                "Retrieve product sales and customer feedback metrics, including "
                "units sold, revenue, feedback count, average rating, and negative "
                "feedback. Optionally filter by exact product ID."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "product_id": {
                        "type": "string",
                        "description": (
                            "Optional exact product ID, such as PROD-007 for Mouse. "
                            "Omit to retrieve metrics for all products."
                        ),
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_customer_feedback",
            "description": (
                "Search customer comments by meaning. Use to investigate "
                "complaints, product problems, delivery experiences, "
                "customer satisfaction, or reasons behind ratings."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "Semantic search query describing the customer feedback "
                            "or complaint to find."
                        ),
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of comments to return, from 1 to 10.",
                    },
                    "product_id": {
                        "type": "string",
                        "description": (
                            "Optional exact product ID filter, such as PROD-005."
                        ),
                    },
                    "sentiment": {
                        "type": "string",
                        "enum": ["positive", "negative", "neutral"],
                        "description": "Optional exact sentiment filter.",
                    },
                },
                "required": ["query"],
            },
        },
    },
]


def format_product_profitability(
    products: list[dict],
    requested_count: int = 5,
) -> str:
    """Generate an accurate profitability summary without LLM arithmetic."""

    if not products:
        return "No product profitability data is available."

    # Normalize values and independently sort by gross profit.
    ordered = sorted(
        products,
        key=lambda product: float(product["gross_profit"]),
    )

    count = min(5, len(ordered))
    least_profitable = ordered[:count]

    loss_products = [
        product for product in ordered if float(product["gross_profit"]) < 0
    ]

    lines = ["Products with the lowest gross profit:"]

    for product in least_profitable:
        profit = float(product["gross_profit"])
        margin = float(product["gross_margin_pct"])

        lines.append(
            f"- {product['product_name']} "
            f"({product['product_id']}): "
            f"gross profit ${profit:,.2f}, "
            f"gross margin {margin:.2f}%."
        )

    lines.append("")

    if loss_products:
        lines.append("Products with negative gross profit:")

        for product in loss_products:
            lines.append(
                f"- {product['product_name']} "
                f"({product['product_id']}): "
                f"${float(product['gross_profit']):,.2f}."
            )
    else:
        lines.append(
            f"No products have negative gross profit "
            f"among the {len(ordered)} products analyzed."
        )

    return "\n".join(lines)


def execute_tool(name: str, arguments: dict) -> Any:
    """Validate and execute an approved tool."""

    function = TOOL_FUNCTIONS.get(name)

    if function is None:
        raise ValueError(f"Tool is not allowed: {name}")

    if name in {
        "get_top_products",
        "get_customer_value",
        "get_product_profitability",
        "get_product_risk_analysis",
    }:
        default_limit = {
            "get_top_products": 5,
            "get_customer_value": 10,
            "get_product_profitability": 12,
            "get_product_risk_analysis": 12,
        }[name]

        maximum = {
            "get_top_products": 12,
            "get_customer_value": 60,
            "get_product_profitability": 12,
            "get_product_risk_analysis": 12,
        }[name]

        limit = arguments.get("limit", default_limit)

        if not isinstance(limit, int) or isinstance(limit, bool):
            raise ValueError("limit must be an integer.")

        arguments = {"limit": max(1, min(limit, maximum))}

    elif name == "search_customer_feedback":
        query = arguments.get("query")

        if not isinstance(query, str) or not query.strip():
            raise ValueError("A non-empty feedback query is required.")

        limit = arguments.get("limit", MAX_FEEDBACK_RESULTS)

        if not isinstance(limit, int) or isinstance(limit, bool):
            raise ValueError("limit must be an integer.")

        product_id = arguments.get("product_id")
        sentiment = arguments.get("sentiment")

        if product_id is not None:
            if not isinstance(product_id, str):
                raise ValueError("product_id must be a string.")

            product_id = product_id.strip()

            if not product_id:
                raise ValueError("product_id cannot be empty.")

        if sentiment is not None:
            if not isinstance(sentiment, str):
                raise ValueError("sentiment must be a string.")

            sentiment = sentiment.strip().lower()

            if sentiment not in {"positive", "negative", "neutral"}:
                raise ValueError("sentiment must be positive, negative, or neutral.")

        return search_feedback(
            question=query.strip(),
            limit=max(1, min(limit, 10)),
            product_id=product_id,
            sentiment=sentiment,
        )
    elif name == "get_product_feedback":
        product_id = arguments.get("product_id")

        if product_id is not None:
            if not isinstance(product_id, str) or not product_id.strip():
                raise ValueError("product_id must be a non-empty string.")

            product_id = product_id.strip()

        arguments = {"product_id": product_id}
    elif name == "get_product_complaint_themes":
        product_id = arguments.get("product_id")

        if not isinstance(product_id, str) or not product_id.strip():
            raise ValueError("A valid product_id is required.")

        arguments = {"product_id": product_id.strip()}
    elif name == "compare_products":
        arguments = {}
    else:
        arguments = {}

    # Execute the approved tool.
    result = function(**arguments)

    if name == "get_product_profitability":
        print("\n[DEBUG] Raw profitability results:")
        for row in result:
            print(row)

        print(f"[DEBUG] Products returned: {len(result)}")

        requested_count = arguments.get("limit", 12)

        return format_product_profitability(
            result,
            requested_count=requested_count,
        )

    return result


SYSTEM_PROMPT = """
You are a customer intelligence analyst working with real business data.

You have tools for:
- Overall business metrics
- Product sales and profitability
- Product risk analysis
- Customer value
- Returns
- Feedback summaries and product feedback
- Semantic customer feedback search

GENERAL RULES

1. Call the tools needed to answer the user's actual question.
2. For numerical business claims, use tool results rather than guessing.
3. For explanations of customer problems, retrieve relevant feedback.
4. For recommendations, combine business metrics and feedback when useful.
5. Do not claim that a sample of feedback represents all customers.
6. Distinguish measured facts from your interpretations.
7. If the evidence is insufficient, say so.
8. Do not invent metrics or claim a tool returned information it did not.
9. You cannot execute arbitrary SQL, code, or other unlisted operations.
10. Provide concise answers and practical recommendations.
11. Never invent industry averages, benchmarks, thresholds, or comparisons
    that are not explicitly provided by the available data.
12. Treat database tool results as the source of truth. Do not contradict
    numerical results or infer unsupported financial facts.

PROFITABILITY ANALYSIS RULES

1. Distinguish low gross profit from a gross loss.
   A product has a gross loss only when gross_profit is negative.
   If gross_profit is positive, the product is gross-profitable,
   regardless of its gross margin percentage.

2. Never conclude that a product is operating at a loss based only
   on its gross margin percentage.

3. When asked which products generate the least gross profit,
   identify products with the lowest gross_profit values.
   Do not substitute gross margin for gross profit.

4. When asked whether any products operate at a loss, inspect the
   gross_profit values for all products returned by the profitability
   tool. Explicitly state whether any have negative gross profit.
   If the results do not cover all products, do not claim that none
   are operating at a loss.

PRODUCT RISK ANALYSIS RULES

1. When asked about product risk, which products need investigation,
   or which products combine complaints and returns, call
   get_product_risk_analysis.

2. Evaluate these metrics when relevant:
   - Negative feedback count
   - Average negative feedback rating
   - Return record count
   - Returned units
   - Returned-unit percentage
   - Revenue and gross profit

3. Do not interpret the report's ordering as a formal risk score.
   The report is ordered by negative feedback count, return records,
   and revenue.

4. Explain which measured metrics support each recommendation.
   Do not invent risk scores, thresholds, or industry benchmarks.

5. High revenue or gross profit indicates financial exposure,
   not proof of a product defect.

6. Do not assume that negative feedback caused a return.
   Treat complaints and returns as separate signals unless the data
   directly establishes a relationship.

7. Do not assume that a high complaint count automatically makes
   a product the riskiest. Consider the available metrics together.

CUSTOMER FEEDBACK ANALYSIS RULES

1. When the user asks what frustrates customers, what customers complain
   about, why customers are dissatisfied, or what problems products have,
   call search_customer_feedback to retrieve actual customer comments.

2. Do not rely exclusively on get_feedback_summary for questions about
   specific customer complaints. Aggregate sentiment counts do not explain
   what customers are experiencing.

3. For general questions about customer frustrations, search for relevant
   negative feedback using a descriptive semantic query. Retrieve up to
   10 relevant comments when appropriate.

4. When discussing a specific product, use get_product_feedback for
   aggregate metrics and search_customer_feedback for actual comments.

5. Distinguish customer-reported problems from verified business facts.
   A complaint is evidence that a customer reported a problem, not proof
   that every customer experiences it.

6. Never invent customer quotes, product complaints, causes of returns,
   or explanations for negative ratings. Use only retrieved evidence.

7. When recommending an action, connect it to specific feedback or
   measured business metrics. Clearly identify recommendations as
   inferences rather than established facts.

8. If feedback retrieval returns no relevant comments, say so instead
   of inventing examples.
   
9. Never generate customer quotes from general knowledge or infer what a
   customer might have said. Every quoted customer comment must match the
   feedback_text of a record returned by search_customer_feedback exactly.

10. When presenting retrieved comments, preserve their original wording.
    Do not rewrite a comment inside quotation marks.

11. If retrieved comments do not mention a specific technical defect,
    do not claim that customers reported that defect.
    
CUSTOMER FEEDBACK EVIDENCE RULES

- Never invent, paraphrase as a direct quote, or reconstruct customer comments.
- Every quoted comment must exactly match a feedback_text returned by
  search_customer_feedback.
- Preserve the original wording of quoted comments.
- If the retrieved comments do not mention a technical defect, do not claim
  that customers reported that defect.
- Distinguish semantic-search results from a complete list of complaints.
- Do not claim that complaints caused returns unless the data establishes
  that connection.
- If a question requests sales, feedback, profitability, and returns,
  retrieve evidence for all four before answering.
- If evidence for a requested category is missing, explicitly disclose that.
- Never substitute a general profitability report for a product-specific
  answer.
"""


def investigate_product(product_name: str) -> str:
    """Gather verified product sales, feedback, profitability, and returns."""

    # Resolve the product against the database.
    products = query_database(
        """
        SELECT product_id, product_name
        FROM products
        WHERE LOWER(product_name) = LOWER(:product_name)
        """,
        {"product_name": product_name},
    )

    if not products:
        return f"No product found matching '{product_name}'."

    product = products[0]
    product_id = product["product_id"]
    canonical_name = product["product_name"]
    complaint_themes = get_product_complaint_themes(product_id)
    # Gather product-specific evidence.
    sales_feedback = get_product_feedback(product_id)
    negative_comments = query_database(
        """
        SELECT DISTINCT ON (category, feedback_text)
            feedback_id,
            feedback_text,
            rating,
            category
        FROM feedback
        WHERE product_id = :product_id
        AND LOWER(sentiment) = 'negative'
        ORDER BY category, feedback_text, rating ASC, feedback_id
        LIMIT 20
        """,
        {"product_id": product_id},
    )
    profitability = get_product_profitability(limit=12)
    risk_analysis = get_product_risk_analysis(limit=12)

    # Select this product's financial results.
    financial = next(
        (row for row in profitability if row["product_id"] == product_id),
        None,
    )

    # Select this product's return and risk results.
    risk = next(
        (row for row in risk_analysis if row["product_id"] == product_id),
        None,
    )

    # get_product_feedback returns a list of product-level records.
    feedback_metrics = next(
        (row for row in sales_feedback if row["product_id"] == product_id),
        None,
    )

    lines = [
        f"Product investigation: {canonical_name} ({product_id})",
        "",
        "SALES AND CUSTOMER FEEDBACK",
    ]

    if feedback_metrics:
        lines.extend(
            [
                f"Units sold: {feedback_metrics['units_sold']}",
                f"Revenue: ${feedback_metrics['revenue']:,.2f}",
                f"Feedback count: {feedback_metrics['feedback_count']}",
                f"Average rating: {feedback_metrics['average_rating']}",
                f"Negative feedback count: {feedback_metrics['negative_feedback']}",
            ]
        )
    else:
        lines.append("Product-level feedback metrics unavailable.")

    lines.extend(["", "PROFITABILITY"])

    if financial:
        lines.extend(
            [
                f"Revenue: ${financial['revenue']:,.2f}",
                f"Cost: ${financial['cost']:,.2f}",
                f"Gross profit: ${financial['gross_profit']:,.2f}",
                f"Gross margin: {financial['gross_margin_pct']}%",
            ]
        )
    else:
        lines.append("Product-specific profitability unavailable.")

    lines.extend(["", "RETURNS"])

    if risk:
        # Keep these field names aligned with get_product_risk_analysis().
        for field in (
            "return_records",
            "returned_units",
            "returned_unit_pct",
        ):
            if field in risk:
                lines.append(f"{field}: {risk[field]}")
        if not any(
            field in risk
            for field in (
                "return_records",
                "returned_units",
                "returned_unit_pct",
            )
        ):
            lines.append("Return metrics require mapping to the actual result fields.")
    else:
        lines.append("Product-specific return metrics unavailable.")

    lines.extend(["", "NEGATIVE FEEDBACK BY CATEGORY"])

    if complaint_themes:
        for theme in complaint_themes:
            lines.append(
                f"- {theme['category']}: "
                f"{theme['complaint_count']} complaints "
                f"({theme['percentage']}%); "
                f"average rating {theme['average_rating']}"
            )
    else:
        lines.append("No negative feedback categories found.")

    lines.extend(["", "ACTUAL NEGATIVE CUSTOMER COMMENTS"])

    if negative_comments:
        for comment in negative_comments:
            lines.append(
                f"- [{comment['feedback_id']}] "
                f"Category: {comment['category']}; "
                f"Rating: {comment['rating']}; "
                f"{comment['feedback_text']}"
            )
    else:
        lines.append("No negative customer comments found.")

    lines.extend([
        "",
        "INTERPRETATION RULES",
        "- Quote comments exactly as stored.",
        "- Do not invent product defects or customer statements.",
        "- Do not claim complaints caused returns without supporting evidence.",
        "- Distinguish measured results from recommendations.",
    ])

    return "\n".join(lines)


def answer_question(question: str) -> str:
    """Run a bounded tool-calling loop and produce a grounded answer."""
    question_lower = question.lower()

    comprehensive_terms = (
        "complaint",
        "customer comment",
        "unhappy",
        "dissatisfied",
    )

    financial_terms = (
        "sales",
        "profitability",
        "gross profit",
        "returns",
        "returned",
    )
    question_lower = question.lower()

    comparison_terms = (
        "compare products",
        "compare all products",
        "across products",
        "between products",
        "which products",
        "product comparison",
        "highest return rate",
        "highest returned-unit",
    )

    if any(term in question_lower for term in comparison_terms):
        return compare_products()
    
    if any(term in question_lower for term in comprehensive_terms) and any(
        term in question_lower for term in financial_terms
    ):
        products = query_database(
            "SELECT product_name FROM products ORDER BY LENGTH(product_name) DESC"
        )

        for row in products:
            name = row["product_name"]

            if name.lower() in question_lower:
                return investigate_product(name)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]

    executed_tools = 0
    profitability_result = None
    executed_calls = set()

    question_lower = question.lower()

    # Only use the deterministic profitability response for questions
    # exclusively about profitability, not multi-part investigations.
    profitability_only = any(
        term in question_lower
        for term in (
            "gross profit",
            "gross margin",
            "profitability",
            "least profitable",
            "most profitable",
        )
    ) and not any(
        term in question_lower
        for term in (
            "feedback",
            "complaint",
            "unhappy",
            "customer comments",
            "returns",
            "returned",
            "sales",
        )
    )

    for _ in range(MAX_TOOL_ROUNDS):
        response = client.chat(
            model=CHAT_MODEL,
            messages=messages,
            tools=TOOLS,
            options={
                "temperature": 0.1,
                "num_ctx": 8192,
            },
        )

        message = response["message"]
        tool_calls = message.get("tool_calls") or []

        if not tool_calls:
            content = message.get("content", "").strip()

            if profitability_result is not None and profitability_only:
                return profitability_result

            return content

        messages.append(message)

        remaining = MAX_TOOL_ROUNDS - executed_tools

        if remaining <= 0:
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "Tool execution limit reached. Answer now using only "
                        "the evidence already collected. Do not request more tools."
                    ),
                }
            )
            continue

        for tool_call in tool_calls:
            if executed_tools >= MAX_TOOL_ROUNDS:
                break

            function_info = tool_call["function"]
            name = function_info["name"]
            arguments = function_info.get("arguments") or {}

            # Avoid executing identical calls repeatedly.
            call_key = (
                name,
                json.dumps(arguments, sort_keys=True, default=str),
            )

            if call_key in executed_calls:
                messages.append(
                    {
                        "role": "tool",
                        "name": name,
                        "content": json.dumps(
                            {
                                "error": (
                                    "Duplicate tool call skipped. Use the evidence "
                                    "already returned instead of repeating this call."
                                )
                            }
                        ),
                    }
                )
                continue

            executed_calls.add(call_key)

            print(f"[Tool] {name}({json.dumps(arguments)})")

            try:
                if name == "get_product_profitability":
                    arguments["limit"] = 12

                result = execute_tool(name, arguments)

                if name == "get_product_profitability":
                    if not isinstance(result, str):
                        raise TypeError("Expected formatted profitability text.")
                    profitability_result = result

                messages.append(
                    {
                        "role": "tool",
                        "name": name,
                        "content": json.dumps(
                            result,
                            default=json_serializer,
                        ),
                    }
                )

            except Exception as error:
                messages.append(
                    {
                        "role": "tool",
                        "name": name,
                        "content": json.dumps({"error": str(error)}),
                    }
                )

            executed_tools += 1

    # Request a final synthesis, without exposing a new tool-calling round.
    messages.append(
        {
            "role": "user",
            "content": (
                "Provide your final answer using only the evidence already "
                "returned by the tools. Do not request additional tools. "
                "Never invent customer comments, financial figures, or return "
                "metrics. Explicitly state when requested evidence is missing."
            ),
        }
    )

    response = client.chat(
        model=CHAT_MODEL,
        messages=messages,
        options={
            "temperature": 0.1,
            "num_ctx": 8192,
        },
    )

    content = response["message"].get("content", "").strip()

    if profitability_result is not None and profitability_only:
        return profitability_result

    return content


def main() -> None:
    print("Customer Intelligence Assistant")
    print(f"Model: {CHAT_MODEL}")
    print("Tool calling enabled.")
    print("Type 'exit' to quit.\n")

    try:
        while True:
            question = input("You: ").strip()

            if question.lower() in {"exit", "quit"}:
                break

            if not question:
                continue

            try:
                answer = answer_question(question)
                print(f"\nAssistant:\n{answer}\n")

            except Exception as error:
                print(f"\nError: {error}\n")

    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
