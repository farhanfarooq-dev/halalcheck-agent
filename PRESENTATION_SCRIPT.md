# Presentation Script

## 3-5 Minute Demo

Hi, today I am presenting AI HalalCheck Agent. It is a bootcamp MVP for checking
whether a food product appears halal-suitable, while clearly separating
decision support from official halal certification.

First I will open the Streamlit app. The first page is Product Check. Here I can
enter a barcode, product name, brand, ingredient list, manufacturer email,
optional customer email, language, and whether an official halal certificate is
available. If I enter a barcode, the product lookup agent tries Open Food Facts.
If barcode data is missing, the app still works with manual input. There is
also an optional ingredient-label image upload. When OpenAI vision support is
configured, the app extracts the ingredient list into the editable Ingredients
field, and the normal halal check still runs on that text rather than directly
on the image.

For the demo, I will check a product with a doubtful ingredient such as E471.
The ingredient analysis uses explicit rules for common E-codes and ingredients
including gelatin, E471, carmine, alcohol, pork, lard, enzymes, emulsifiers, and
flavouring. The decision agent returns a status such as `No Concern Found`,
`Doubtful / Needs Verification`, `Not Halal`, `Unknown`, `Manufacturer
Confirmed Suitable`, or `Halal Certified`.

The important safety rule is that the system never claims `Halal Certified`
unless an official certificate is available. A manufacturer answer can lead to
`Manufacturer Confirmed Suitable`, but that is still not the same as an
official certificate.

Next I will show the explanation. The app can use OpenAI or Gemini if keys are
configured, but the default demo mode is local explanation, so the project works
without exposing API secrets. Email is also safe by default:
`EMAIL_MODE=draft`. The app creates a manufacturer inquiry draft. If Gmail OAuth is configured and
`EMAIL_MODE=approval`, the user can review the recipient, subject, and body,
then click Approve and Send. In the default demo mode, no real email is sent.

Now I will open the History page. This shows previous product checks stored in
SQLite. The database tracks product checks, manufacturer inquiries,
manufacturer responses, and notification drafts.

Then I will open Admin Response Review. Here an admin can sync Gmail replies or
paste a manufacturer reply, such as a statement that E471 is plant-based. The app analyzes the
response, stores it, updates the inquiry, and creates a draft notification for
the user if a customer email was provided.

One useful workflow feature is stored confirmation reuse. If the same barcode,
doubtful ingredient, and ingredient list appear again, the app can reuse the
stored manufacturer confirmation. If the ingredients change, it requires a new
review instead of trusting old evidence.

The project also includes a FastAPI backend. I will open
`http://127.0.0.1:8000/docs` to show the generated Swagger documentation. The
backend exposes four endpoints:

- `GET /health`
- `POST /check-product`
- `GET /product-status/{barcode}`
- `POST /manufacturer-response`
- `POST /manufacturer-inquiry/send`
- `POST /gmail/sync-replies`

The backend reuses the same workflow as Streamlit: barcode lookup, manual
fallback, ingredient analysis, explanation generation, inquiry draft creation,
response analysis, and stored confirmation reuse.

For project completeness, the repo includes 46 passing automated tests, Docker
support, Docker Compose support, `.env.example`, and documentation for local
Python, Streamlit, FastAPI, tests, and container runs.

The main run commands are:

```bash
py -m streamlit run app.py
py -m uvicorn api:app --reload
py -m pytest
docker compose up --build
```

The main limitations are that halal suitability still needs human judgment,
Open Food Facts data can be incomplete, and real email sending is intentionally
disabled for the MVP. Future improvements could add reviewed email sending,
stronger retrieval, LangGraph orchestration, MCP tools, n8n workflows, and
cloud deployment.
