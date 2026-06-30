# Reflection

AI HalalCheck Agent demonstrates a practical AI agent workflow while keeping
the final halal decision grounded in explicit rules and verifiable evidence.

The project now has two access paths. Streamlit provides a beginner-friendly
interface for normal users and admins. FastAPI provides a lightweight backend
for programmatic checks, integrations, and future automation. Both paths reuse
the same files: `agents.py`, `halal_rules.py`, `product_lookup.py`,
`database.py`, and `config.py`.

Using Pydantic request and response schemas in `api.py` makes the backend easier
to test and safer to extend. The API endpoints are simple on purpose:

- `GET /health`
- `POST /check-product`
- `GET /product-status/{barcode}`
- `POST /manufacturer-response`

The most important design decision is that the app does not pretend to be a
certification authority. `Halal Certified` only applies when an official
certificate is available. Manufacturer confirmation can be useful evidence, but
`Manufacturer Confirmed Suitable` is not the same as `Halal Certified`.

The MVP also keeps email safe. `EMAIL_MODE=draft` means no real emails are sent.
Instead, the system creates human-reviewable manufacturer inquiry drafts and
user notification drafts.

The next natural extensions are MCP tools, n8n workflows, real Gmail sending
after review and consent, LangGraph orchestration, ChromaDB or FAISS retrieval,
and cloud deployment.
