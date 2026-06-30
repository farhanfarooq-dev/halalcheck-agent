# Reflection

AI HalalCheck Agent demonstrates a practical AI agent workflow while keeping
the final halal decision grounded in explicit rules and verifiable evidence.

## What Was Built

The project now has two access paths. Streamlit provides a beginner-friendly
interface for normal users and admins, with Product Check, History, and Admin
Response Review pages. FastAPI provides a lightweight backend for programmatic
checks, integrations, and future automation. Both paths reuse the same files:
`agents.py`, `halal_rules.py`, `product_lookup.py`, `database.py`, and
`config.py`.

The MVP includes barcode lookup through Open Food Facts, manual product entry,
rule-based ingredient and E-code checks, local or optional LLM-assisted
explanations, manufacturer inquiry drafts, manufacturer response review, stored
confirmation reuse, SQLite persistence, tests, Docker support, and Docker
Compose support.

Using Pydantic request and response schemas in `api.py` makes the backend easier
to test and safer to extend. The API endpoints are simple on purpose:

- `GET /health`
- `POST /check-product`
- `GET /product-status/{barcode}`
- `POST /manufacturer-response`

## Challenges

One challenge was balancing AI behavior with conservative halal decision logic.
The app needs helpful explanations, but the final status should still come from
traceable rules and evidence. Another challenge was modeling manufacturer
confirmation safely: a response can be useful, but it should only be reused
when the barcode, doubtful ingredient, and ingredient list still match.

The project also needed a safe email workflow. Real email sending is useful in
future versions, but for the MVP the better bootcamp choice is draft generation
with human review.

## Limitations

The most important design decision is that the app does not pretend to be a
certification authority. `Halal Certified` only applies when an official
certificate is available. Manufacturer confirmation can be useful evidence, but
`Manufacturer Confirmed Suitable` is not the same as `Halal Certified`.

The MVP also keeps email safe. `EMAIL_MODE=draft` means no real emails are sent.
Instead, the system creates human-reviewable manufacturer inquiry drafts and
user notification drafts.

Other limitations are incomplete third-party barcode data, limited rule coverage
for complex ingredient sourcing, simple keyword retrieval, and local SQLite
storage rather than a production database.

## Metrics

- 34 automated tests passed.
- 4 FastAPI endpoints.
- Streamlit UI with Product Check, History, and Admin Response Review pages.
- SQLite workflow for product checks, manufacturer inquiries, responses, and
  notifications.

## Future Improvements

The next natural extensions are MCP tools, n8n workflows, reviewed Gmail
sending after explicit consent, LangGraph orchestration, ChromaDB or FAISS
retrieval, richer admin audit trails, production authentication, and cloud
deployment.
