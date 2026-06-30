# AI HalalCheck Agent

AI HalalCheck Agent is a bootcamp MVP for checking whether food products are
halal-suitable. It combines a Streamlit user interface, a lightweight FastAPI
backend, SQLite storage, barcode lookup, rule-based ingredient analysis,
manufacturer confirmation handling, and optional AI/RAG explanations.

This project is decision support only. It does not issue official halal
certification.

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

## Initialize The Database

```bash
cd halalcheck-agent
py database.py
```

## Environment Variables

Copy `.env.example` to `.env` for local secrets and configuration:

```bash
copy .env.example .env
```

Put real API keys and email credentials only in `.env`. Do not commit `.env`.

Example local email configuration:

```env
EMAIL_MODE=draft
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=halalcheckde@gmail.com
SMTP_PASSWORD=your_app_password_here
FROM_EMAIL=halalcheckde@gmail.com
SENDER_DISPLAY_NAME=Your Name
REPLY_TO_EMAIL=your_reply_email@example.com
```

`EMAIL_MODE=draft` is the default. In the MVP, no real emails are sent. The app
and API create human-reviewable drafts only.

The manufacturer email address must be entered by the user for each product.
The user/customer email address must also be entered by the user if they want a
notification draft.

Use a human sender display name such as your own name in
`SENDER_DISPLAY_NAME`. This makes manufacturer inquiries look like normal
customer messages and can improve the chance of receiving a helpful reply. The
displayed sender is built from `SENDER_DISPLAY_NAME <FROM_EMAIL>`, and
`REPLY_TO_EMAIL` can be set when replies should go to a different address.

## Run The Streamlit UI

```bash
cd halalcheck-agent
py -m streamlit run app.py
```

Streamlit is the main user interface for product checks, barcode lookup,
manual ingredient entry, check history, and admin response review.

## Run The FastAPI Backend

```bash
cd halalcheck-agent
py -m uvicorn api:app --reload
```

Open the interactive FastAPI docs at:

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

## Future Extensions

Planned future improvements include MCP integration, n8n workflows, real Gmail
sending after review and consent, LangGraph orchestration, ChromaDB or FAISS
for stronger retrieval, and cloud deployment.
