# AI HalalCheck Agent

AI HalalCheck Agent is a bootcamp MVP for checking whether food products are
halal-suitable. It combines a Streamlit user interface, a lightweight FastAPI
backend, SQLite storage, barcode lookup, rule-based ingredient analysis,
manufacturer confirmation handling, and optional AI/RAG explanations.

This project is decision support only. It does not issue official halal
certification.

## Metrics

- 46 automated tests passed.
- 6 FastAPI endpoints: 4 core endpoints and 2 optional Gmail workflow endpoints.
- Streamlit UI with Product Check, History, and Admin Response Review pages.
- SQLite workflow for product checks, manufacturer inquiries, responses, and
  notifications.

## Current Features

- Streamlit UI for product checks, history, and admin response review.
- FastAPI backend for programmatic product checks and manufacturer response
  handling.
- Pydantic request and response schemas for API validation.
- Open Food Facts barcode lookup with manual input fallback.
- Optional ingredient-label image extraction for Streamlit when OpenAI vision
  support is configured.
- Rule-based ingredient and E-code checker.
- Local SQLite database for products, checks, inquiries, responses, and draft
  user notifications.
- Optional OpenAI/Gemini explanation mode with safe local fallback.
- Human-reviewable manufacturer inquiry email drafts.
- Optional Gmail approval workflow for sending reviewed manufacturer inquiries
  and syncing replies.

## API Endpoints

The FastAPI backend provides these endpoints:

- `GET /health`
- `POST /check-product`
- `GET /product-status/{barcode}`
- `POST /manufacturer-response`
- `POST /manufacturer-inquiry/send`
- `POST /gmail/sync-replies`

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
GMAIL_SENDER_EMAIL=halalcheckde@gmail.com
```

`EMAIL_MODE=draft` is the default. In this MVP, no real emails are sent. The
app and API create human-reviewable manufacturer inquiry drafts and user
notification drafts only.

Optional ingredient-label image extraction is available in Streamlit only when
`LLM_PROVIDER=openai` and `OPENAI_API_KEY` are set locally. The extracted text is
placed into the editable Ingredients field; the halal check still analyzes only
the final ingredient text, not the image directly.

Optional Gmail sending uses human approval. Keep `EMAIL_MODE=draft` for demos.
To test real Gmail sending locally, set `EMAIL_MODE=approval`,
`GMAIL_SENDER_EMAIL`, `GMAIL_CREDENTIALS_PATH`, and `GMAIL_TOKEN_PATH` in your
local `.env`. Never commit Gmail credentials or token files.

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
manual ingredient entry, optional ingredient-label image extraction, check
history, and admin response review.

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


## Gmail Manufacturer Inquiry Workflow

The Gmail workflow is optional and human-in-the-loop.

Draft mode test:

```bash
EMAIL_MODE=draft
py -m streamlit run app.py
```

Then check a product with doubtful ingredients. The app shows the manufacturer
inquiry draft, possible email candidates, and the confirmed recipient field. No
Gmail email is sent in draft mode.

Approved send test:

```env
EMAIL_MODE=approval
GMAIL_SENDER_EMAIL=halalcheckde@gmail.com
GMAIL_CREDENTIALS_PATH=secrets/gmail_credentials.json
GMAIL_TOKEN_PATH=secrets/gmail_token.json
```

Run Streamlit, review the draft, confirm/edit the recipient email, then click
`Approve and Send`. The app stores the Gmail message id and thread id when Gmail
returns them. Local credential and token files must stay out of Git.

Reply sync test:

In Admin Response Review, click `Sync manufacturer replies from Gmail`. The sync
matches replies by Gmail thread when available and stores the manufacturer
response without deleting Gmail messages. For bootcamp/demo testing, the pytest
suite uses mocked Gmail replies so no real email is sent.

## Public Testing / Deployment Notes

For a public family test, use a free hosting option such as Streamlit Community
Cloud, Render free web service, or the Docker/Docker Compose instructions in
this README. Hosting platforms usually provide a free public URL; a permanent
custom domain is separate and may not be free.

Set secrets through the hosting platform's environment/secret settings. Never
upload `.env`, Gmail credential JSON, or Gmail token JSON files. If Gmail OAuth
is too complex for the hosted demo, keep `EMAIL_MODE=draft` and demonstrate the
local or Docker workflow.

## Run Tests

```bash
py -m pytest
```

Expected submission result:

```text
46 passed
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
