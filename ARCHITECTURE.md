# Architecture

AI HalalCheck Agent is built as a small modular MVP. The same core agent logic
is reused by both the Streamlit UI and the FastAPI backend.

## Main Components

- `app.py`: Streamlit UI for product checks, history, and admin response
  review.
- `api.py`: FastAPI backend for API access to the product-check workflow.
- `agents.py`: Modular workflow functions for product lookup, ingredient
  analysis, halal decision logic, manufacturer inquiry drafts, response
  analysis, and user communication.
- `halal_rules.py`: Rule-based ingredient and E-code checker.
- `product_lookup.py`: Open Food Facts barcode lookup.
- `database.py`: SQLite schema, database initialization, and seed data loading.
- `rag_engine.py`: Simple keyword-based knowledge retrieval for explanations.
- `email_service.py`: Human-reviewable email draft generation. Real sending is
  disabled by default.
- `config.py`: Environment variable loading from `.env`.

## User Interfaces

The Streamlit UI is the main human-facing workflow. It supports barcode input,
manual product details, ingredient analysis, AI/local explanations, check
history, pending inquiry review, and manufacturer response review.

The FastAPI backend exposes the same workflow for programmatic use. It uses
Pydantic request and response schemas to validate inputs and keep API responses
structured.

## FastAPI Endpoints

- `GET /health`: Confirms the backend is running.
- `POST /check-product`: Runs barcode lookup, manual fallback, ingredient
  analysis, decision logic, explanation generation, stored confirmation reuse,
  and manufacturer inquiry draft creation when needed.
- `GET /product-status/{barcode}`: Returns the latest locally known status for
  a barcode.
- `POST /manufacturer-response`: Accepts a manufacturer response, analyzes it,
  stores it in SQLite, updates the inquiry status, and creates a draft user
  notification if a user email exists.

The API uses these Pydantic schemas:

- `ProductCheckRequest`
- `ProductCheckResponse`
- `ManufacturerResponseRequest`
- `ManufacturerResponseResult`

## Data Flow

1. A user enters a barcode or manual product details.
2. The product lookup agent checks local SQLite first and then Open Food Facts
   when a barcode is available.
3. Ingredient rules classify detected ingredients as acceptable, doubtful, not
   halal, or unknown.
4. The decision agent applies final status logic.
5. The communication agent generates a local or optional LLM-assisted
   explanation.
6. If verification is needed, the manufacturer inquiry agent creates or reuses
   a draft inquiry.
7. An admin can paste a manufacturer response through Streamlit or FastAPI.
8. The response is analyzed, stored, and reused later only when the barcode,
   doubtful ingredient, and ingredient list still match.

## Safety Rules

The system must never mark a product as `Halal Certified` unless an official
halal certificate is available. `Manufacturer Confirmed Suitable` is not the
same as `Halal Certified`.

`EMAIL_MODE=draft` is the default. In the MVP, no real emails are sent by
Streamlit or FastAPI.

## Run Commands

Streamlit:

```bash
py -m streamlit run app.py
```

FastAPI:

```bash
py -m uvicorn api:app --reload
```

FastAPI docs:

```text
http://127.0.0.1:8000/docs
```

## Future Extensions

Future versions can add MCP tools, n8n automation, reviewed Gmail sending,
LangGraph agent orchestration, ChromaDB or FAISS retrieval, and cloud
deployment.
