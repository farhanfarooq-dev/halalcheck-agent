# AI HalalCheck Agent

AI HalalCheck Agent is a bootcamp MVP for checking whether food products are
halal-suitable. It combines a Streamlit user interface, a lightweight FastAPI
backend, SQLite storage, barcode lookup, rule-based ingredient analysis,
manufacturer confirmation handling, and optional AI/RAG explanations.

This project is decision support only. It does not issue official halal
certification.

## Metrics

- 39 automated tests passed.
- 4 FastAPI endpoints.
- Streamlit UI with Product Check, History, and Admin Response Review pages.
- SQLite workflow for product checks, manufacturer inquiries, responses, and
  notifications.

## Current Features

- Streamlit UI for product checks, history, and admin response review.
- FastAPI backend for programmatic product checks and manufacturer response
  handling.
- Pydantic request and response schemas for API validation.
- Open Food Facts barcode lookup with manual input fallback.
- Rule-based ingredient and E-code checker.
- Local SQLite database for products, checks, inquiries, responses, and draft
  user notifications.
- Optional OpenAI/Gemini explanation mode with safe local fallback.
- Human-reviewable manufacturer inquiry email drafts.

## API Endpoints

The FastAPI backend provides these endpoints:

- `GET /health`
- `POST /check-product`
- `GET /product-status/{barcode}`
- `POST /manufacturer-response`

The main Pydantic schemas are:

- `ProductCheckRequest`
- `ProductCheckResponse`
- `ManufacturerResponseRequest`
- `ManufacturerResponseResult`

## Environment Variables

Copy `.env.example` to `.env` before running locally:

```bash
cd halalcheck-agent
copy .env.example .env
```

On macOS/Linux:

```bash
cp .env.example .env
```

Keep real API keys and email credentials only in `.env`. `.env` must not be
committed or copied into Docker images. The committed `.env.example` contains
safe placeholders only.

Important MVP defaults:

```env
LLM_PROVIDER=local
EMAIL_MODE=draft
DATABASE_PATH=data/halalcheck.db
```

`EMAIL_MODE=draft` is the default. In this MVP, no real emails are sent. The
app and API create human-reviewable manufacturer inquiry drafts and user
notification drafts only.

## Run Locally With Python

Create and activate a virtual environment:

```bash
cd halalcheck-agent
py -m venv .venv
.venv\Scripts\activate
py -m pip install -r requirements.txt
```

On macOS/Linux, use:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Initialize SQLite seed data:

```bash
py database.py
```

On macOS/Linux:

```bash
python database.py
```

## Run The Streamlit UI

Start Streamlit:

```bash
py -m streamlit run app.py
```

Open:

```text
http://localhost:8501
```

Streamlit is the main user interface for product checks, barcode lookup,
manual ingredient entry, check history, and admin response review.

## Run The FastAPI Backend

Start FastAPI:

```bash
py -m uvicorn api:app --reload
```

The API runs at:

```text
http://127.0.0.1:8000
```

## Open FastAPI Docs

Open the interactive Swagger documentation at:

```text
http://127.0.0.1:8000/docs
```

Example API requests:

```bash
curl http://127.0.0.1:8000/health
```

```bash
curl -X POST http://127.0.0.1:8000/check-product ^
  -H "Content-Type: application/json" ^
  -d "{\"product_name\":\"Demo Biscuit\",\"ingredients\":\"Sugar, E471\",\"manufacturer_email\":\"quality@example.com\",\"user_email\":\"customer@example.com\",\"language\":\"en\"}"
```

```bash
curl http://127.0.0.1:8000/product-status/1234567890123
```

```bash
curl -X POST http://127.0.0.1:8000/manufacturer-response ^
  -H "Content-Type: application/json" ^
  -d "{\"inquiry_id\":1,\"response_text\":\"The E471 used in this product is plant-based.\"}"
```

## Run Tests

```bash
py -m pytest
```

Expected submission result:

```text
39 passed
```

## Run With Docker

Build the image:

```bash
docker build -t halalcheck-agent .
```

Run FastAPI:

```bash
docker run --rm -p 8000:8000 --env EMAIL_MODE=draft halalcheck-agent
```

Run Streamlit:

```bash
docker run --rm -p 8501:8501 --env EMAIL_MODE=draft halalcheck-agent streamlit run app.py --server.address 0.0.0.0 --server.port 8501
```

## Run With Docker Compose

Start both services:

```bash
docker compose up --build
```

Open:

```text
Streamlit: http://localhost:8501
FastAPI docs: http://localhost:8000/docs
```

Stop the services:

```bash
docker compose down
```

Compose keeps `EMAIL_MODE=draft` by default and stores SQLite data in a named
Docker volume.

## Future Extensions

Planned future improvements include MCP integration, n8n workflows, real Gmail
sending after review and consent, LangGraph orchestration, ChromaDB or FAISS
for stronger retrieval, and cloud deployment.
