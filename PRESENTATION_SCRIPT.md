# Presentation Script

Today I am presenting AI HalalCheck Agent, a multilingual food product checking
app that combines rule-based ingredient analysis, optional AI explanations,
database workflows, manufacturer confirmation handling, a Streamlit UI, and a
FastAPI backend.

The user can start in the Streamlit interface by entering a barcode, product
name, brand, ingredients, manufacturer email, optional customer email, language,
and whether an official halal certificate is available. The app checks the
barcode through Open Food Facts when possible and falls back to manual input
when needed.

The ingredient analysis uses explicit rules for common E-codes and ingredients
such as gelatin, E471, carmine, alcohol, pork, lard, enzymes, emulsifiers, and
flavouring. The decision logic then returns a clear preliminary status, such as
`No Concern Found`, `Doubtful / Needs Verification`, `Not Halal`, `Unknown`,
`Manufacturer Confirmed Suitable`, or `Halal Certified`.

The system is careful about certification wording. `Halal Certified` is only
used when an official halal certificate is available. `Manufacturer Confirmed
Suitable` is useful manufacturer evidence, but it is not the same as `Halal
Certified`.

The project also includes a FastAPI backend. It uses Pydantic request and
response schemas for validation and exposes four endpoints:

- `GET /health`
- `POST /check-product`
- `GET /product-status/{barcode}`
- `POST /manufacturer-response`

The backend reuses the same agent workflow as Streamlit: barcode lookup, manual
fallback, ingredient analysis, local or AI-assisted explanation, stored
manufacturer confirmation reuse, duplicate inquiry prevention, and manufacturer
response analysis.

To run the Streamlit UI:

```bash
py -m streamlit run app.py
```

To run the FastAPI backend:

```bash
py -m uvicorn api:app --reload
```

The FastAPI documentation is available at:

```text
http://127.0.0.1:8000/docs
```

For email safety, the MVP keeps `EMAIL_MODE=draft`. No real emails are sent.
Manufacturer inquiry emails and user notifications are created as drafts for
human review.

Future extensions could include MCP integration, n8n automation, real Gmail
sending after review and consent, LangGraph orchestration, ChromaDB or FAISS
for stronger retrieval, and cloud deployment.
