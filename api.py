"""Lightweight FastAPI backend for the AI HalalCheck Agent."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager, closing
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

import config
import email_service
from gmail_workflow import approve_and_send_inquiry, sync_manufacturer_replies
from agents import (
    analyze_manufacturer_response,
    halal_decision_agent,
    ingredient_analysis_agent,
    manufacturer_inquiry_agent,
    product_lookup_agent,
    user_communication_agent,
    _product_manual_hash,
)
from database import DB_PATH, get_connection, initialize_database


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Ensure SQLite tables exist when the API server starts."""
    initialize_database(DB_PATH)
    yield


app = FastAPI(
    title="AI HalalCheck Agent API",
    version=config.APP_VERSION,
    lifespan=lifespan,
)


class ProductCheckRequest(BaseModel):
    """Input for checking one product."""

    barcode: str | None = None
    product_name: str | None = None
    brand: str | None = None
    ingredients: str | None = None
    manufacturer_email: str | None = None
    user_email: str | None = None
    language: str = Field(default="en", description="Use 'en' or 'de'.")
    official_certificate_available: bool = False


class ProductCheckResponse(BaseModel):
    """Structured product check result."""

    product_id: int | None
    product: dict[str, Any]
    analysis: dict[str, Any]
    decision: dict[str, str]
    manufacturer_inquiry: dict[str, Any]
    communication: dict[str, Any]
    email_mode: str


class ManufacturerResponseRequest(BaseModel):
    """Input for storing and analyzing a manufacturer response."""

    response_text: str
    inquiry_id: int | None = None
    barcode: str | None = None
    product_name: str | None = None
    brand: str | None = None
    ingredients_text: str | None = None
    doubtful_ingredient: str | None = None
    manufacturer_email: str | None = None


class ManufacturerResponseResult(BaseModel):
    """Stored manufacturer response analysis result."""

    inquiry_id: int
    stored: bool
    analyzed_status: str
    analysis_notes: str
    notification_draft: dict[str, str] | None = None
    email_mode: str


class ManufacturerInquirySendRequest(BaseModel):
    """Human-approved Gmail send request for one inquiry."""

    inquiry_id: int
    recipient_email: str


class GmailSyncResult(BaseModel):
    """Result from syncing manufacturer replies."""

    status: str
    count: int
    matched_replies: list[dict[str, Any]]


@app.get("/health")
def health_check() -> dict[str, str]:
    """Simple health check for local development and deployment probes."""
    return {
        "status": "ok",
        "app_name": config.APP_NAME,
        "email_mode": config.EMAIL_MODE,
    }


@app.post("/check-product", response_model=ProductCheckResponse)
def check_product(request: ProductCheckRequest) -> ProductCheckResponse:
    """Run the same product-check workflow used by the Streamlit MVP."""
    initialize_database(DB_PATH)
    language = _normalize_language(request.language)

    product = product_lookup_agent(
        barcode=request.barcode,
        product_name=request.product_name,
        brand=request.brand,
        ingredients=request.ingredients,
        manufacturer_email=request.manufacturer_email,
        official_certificate_available=request.official_certificate_available,
        db_path=DB_PATH,
    )
    product_id = _save_product(product, DB_PATH)
    product["id"] = product_id

    analysis = ingredient_analysis_agent(product)
    decision = halal_decision_agent(product, analysis, db_path=DB_PATH)
    inquiry = manufacturer_inquiry_agent(product, decision, analysis, db_path=DB_PATH)
    communication = user_communication_agent(
        product,
        decision,
        analysis,
        language=language,
    )

    _save_product_check(
        product_id=product_id,
        user_email=request.user_email or "",
        language=language,
        final_status=decision["status"],
        explanation=communication["explanation"],
        detected_concerns=analysis["detected_concerns"],
        result_source=decision.get("result_source", ""),
        db_path=DB_PATH,
    )

    return ProductCheckResponse(
        product_id=product_id,
        product=product,
        analysis=analysis,
        decision=decision,
        manufacturer_inquiry=inquiry,
        communication=communication,
        email_mode=config.EMAIL_MODE,
    )


@app.get("/product-status/{barcode}", response_model=ProductCheckResponse)
def product_status(barcode: str) -> ProductCheckResponse:
    """Return the latest known local status for a barcode."""
    initialize_database(DB_PATH)
    product = _find_product_by_barcode(barcode, DB_PATH)
    if not product:
        raise HTTPException(status_code=404, detail="Product barcode not found locally.")

    analysis = ingredient_analysis_agent(product)
    decision = halal_decision_agent(product, analysis, db_path=DB_PATH)
    communication = user_communication_agent(product, decision, analysis)
    latest_check = _latest_product_check(int(product["id"]), DB_PATH)

    return ProductCheckResponse(
        product_id=int(product["id"]),
        product={**product, "latest_check": latest_check},
        analysis=analysis,
        decision=decision,
        manufacturer_inquiry={
            "required": False,
            "status": "not_created_by_status_endpoint",
            "message": "This endpoint reports status only and does not create inquiries.",
        },
        communication=communication,
        email_mode=config.EMAIL_MODE,
    )



@app.post("/manufacturer-inquiry/send")
def send_manufacturer_inquiry(
    request: ManufacturerInquirySendRequest,
) -> dict[str, str]:
    """Send a reviewed manufacturer inquiry only after human approval."""
    initialize_database(DB_PATH)
    inquiry = _fetch_inquiry(request.inquiry_id, DB_PATH)
    if not inquiry:
        raise HTTPException(status_code=404, detail="Manufacturer inquiry not found.")
    result = approve_and_send_inquiry(
        inquiry_id=request.inquiry_id,
        recipient_email=request.recipient_email,
        subject=str(inquiry.get("email_subject") or ""),
        body=str(inquiry.get("email_body") or ""),
        db_path=DB_PATH,
    )
    if result["status"] not in {"sent", "draft"}:
        raise HTTPException(status_code=400, detail=result["message"])
    return result


@app.post("/gmail/sync-replies", response_model=GmailSyncResult)
def gmail_sync_replies() -> GmailSyncResult:
    """Sync manufacturer replies from Gmail when configured."""
    initialize_database(DB_PATH)
    result = sync_manufacturer_replies(DB_PATH)
    return GmailSyncResult(**result)


@app.post("/manufacturer-response", response_model=ManufacturerResponseResult)
def manufacturer_response(
    request: ManufacturerResponseRequest,
) -> ManufacturerResponseResult:
    """Analyze and store a manufacturer response without sending email."""
    initialize_database(DB_PATH)
    if not request.response_text.strip():
        raise HTTPException(status_code=422, detail="response_text is required.")

    inquiry = _find_or_create_inquiry_for_response(request, DB_PATH)
    requested_ingredients = _requested_ingredients_from_inquiry(inquiry)
    analysis = analyze_manufacturer_response(request.response_text, requested_ingredients)
    notification_draft = _store_manufacturer_response(
        inquiry=inquiry,
        response_text=request.response_text,
        analyzed_status=analysis["analyzed_status"],
        analysis_notes=analysis["analysis_notes"],
        confirmed_ingredients=analysis.get("confirmed_ingredients", []),
        unresolved_ingredients=analysis.get("unresolved_ingredients", []),
        db_path=DB_PATH,
    )

    return ManufacturerResponseResult(
        inquiry_id=int(inquiry["id"]),
        stored=True,
        analyzed_status=analysis["analyzed_status"],
        analysis_notes=analysis["analysis_notes"],
        notification_draft=notification_draft,
        email_mode=config.EMAIL_MODE,
    )


def _normalize_language(language: str) -> str:
    return "de" if language.lower().startswith("de") else "en"


def _save_product(product: dict[str, Any], db_path: Path) -> int:
    """Insert or update a product and return its database id."""
    with closing(get_connection(db_path)) as connection:
        barcode = product.get("barcode")
        manual_hash = _product_manual_hash(product)
        product["manual_product_hash"] = manual_hash
        product["product_identity_key"] = barcode or manual_hash

        if barcode:
            existing = connection.execute(
                "SELECT id FROM products WHERE barcode = ?;",
                (barcode,),
            ).fetchone()
        else:
            existing = connection.execute(
                "SELECT id FROM products WHERE manual_product_hash = ?;",
                (manual_hash,),
            ).fetchone()

        if existing:
            connection.execute(
                """
                UPDATE products
                SET name = ?, brand = ?, ingredients = ?, manufacturer_email = ?,
                    source = ?, official_certificate_available = ?,
                    manual_product_hash = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?;
                """,
                (
                    product.get("name") or "Manual product",
                    product.get("brand") or "",
                    product.get("ingredients") or "",
                    product.get("manufacturer_email") or "",
                    product.get("source") or "manual",
                    int(bool(product.get("official_certificate_available"))),
                    manual_hash,
                    existing["id"],
                ),
            )
            connection.commit()
            return int(existing["id"])

        cursor = connection.execute(
            """
            INSERT INTO products (
                barcode,
                name,
                brand,
                ingredients,
                manual_product_hash,
                manufacturer_email,
                source,
                official_certificate_available
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                barcode,
                product.get("name") or "Manual product",
                product.get("brand") or "",
                product.get("ingredients") or "",
                manual_hash,
                product.get("manufacturer_email") or "",
                product.get("source") or "manual",
                int(bool(product.get("official_certificate_available"))),
            ),
        )
        connection.commit()
        return int(cursor.lastrowid)

def _save_product_check(
    product_id: int,
    user_email: str,
    language: str,
    final_status: str,
    explanation: str,
    detected_concerns: list[dict[str, Any]],
    result_source: str,
    db_path: Path,
) -> None:
    """Save one product check result."""
    with closing(get_connection(db_path)) as connection:
        connection.execute(
            """
            INSERT INTO product_checks (
                product_id,
                user_email,
                language,
                final_status,
                result_source,
                explanation,
                detected_concerns_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?);
            """,
            (
                product_id,
                user_email.strip(),
                language,
                final_status,
                result_source,
                explanation,
                json.dumps(detected_concerns),
            ),
        )
        connection.commit()


def _find_product_by_barcode(barcode: str, db_path: Path) -> dict[str, Any] | None:
    with closing(get_connection(db_path)) as connection:
        row = connection.execute(
            """
            SELECT *
            FROM products
            WHERE barcode = ?;
            """,
            (barcode,),
        ).fetchone()
    if not row:
        return None
    return {
        "id": row["id"],
        "barcode": row["barcode"],
        "manual_product_hash": row["manual_product_hash"] or "",
        "product_identity_key": row["barcode"] or row["manual_product_hash"] or "",
        "name": row["name"],
        "brand": row["brand"] or "",
        "ingredients": row["ingredients"] or "",
        "manufacturer_email": row["manufacturer_email"] or "",
        "source": row["source"],
        "official_certificate_available": bool(row["official_certificate_available"]),
        "lookup_status": "found_in_database",
        "lookup_error": "",
        "result_source": "local database",
        "recheck_required": False,
    }


def _latest_product_check(product_id: int, db_path: Path) -> dict[str, Any] | None:
    with closing(get_connection(db_path)) as connection:
        row = connection.execute(
            """
            SELECT final_status, explanation, checked_at
            FROM product_checks
            WHERE product_id = ?
            ORDER BY checked_at DESC
            LIMIT 1;
            """,
            (product_id,),
        ).fetchone()
    return dict(row) if row else None


def _find_or_create_inquiry_for_response(
    request: ManufacturerResponseRequest,
    db_path: Path,
) -> dict[str, Any]:
    if request.inquiry_id is not None:
        inquiry = _fetch_inquiry(request.inquiry_id, db_path)
        if not inquiry:
            raise HTTPException(status_code=404, detail="Manufacturer inquiry not found.")
        return inquiry

    ingredient = (request.doubtful_ingredient or "").strip()
    if not ingredient:
        raise HTTPException(
            status_code=422,
            detail="doubtful_ingredient is required when inquiry_id is not provided.",
        )

    existing = _find_matching_inquiry(request, ingredient, db_path)
    if existing:
        return existing

    product = {
        "barcode": (request.barcode or "").strip() or None,
        "name": (request.product_name or "Manual product").strip(),
        "brand": (request.brand or "").strip(),
        "ingredients": (request.ingredients_text or "").strip(),
        "manufacturer_email": (request.manufacturer_email or "").strip(),
        "source": "manual",
        "official_certificate_available": False,
    }
    product_id = _save_product(product, db_path)
    product["id"] = product_id

    requested_ingredients = [part.strip() for part in ingredient.split(",") if part.strip()]
    draft = email_service.generate_manufacturer_email_draft(
        product,
        [{"ingredient": ingredient_name} for ingredient_name in requested_ingredients],
    )
    with closing(get_connection(db_path)) as connection:
        cursor = connection.execute(
            """
            INSERT INTO manufacturer_inquiries (
                product_id,
                ingredient_term,
                requested_ingredients_json,
                manufacturer_email,
                email_subject,
                email_body,
                status
            )
            VALUES (?, ?, ?, ?, ?, ?, 'draft');
            """,
            (
                product_id,
                ingredient,
                json.dumps(requested_ingredients),
                product["manufacturer_email"],
                draft["subject"],
                draft["body"],
            ),
        )
        connection.commit()

    inquiry = _fetch_inquiry(int(cursor.lastrowid), db_path)
    if not inquiry:
        raise HTTPException(status_code=500, detail="Inquiry could not be created.")
    return inquiry


def _fetch_inquiry(inquiry_id: int, db_path: Path) -> dict[str, Any] | None:
    with closing(get_connection(db_path)) as connection:
        row = connection.execute(
            """
            SELECT
                mi.id,
                mi.product_id,
                mi.ingredient_term,
                mi.requested_ingredients_json,
                mi.manufacturer_email,
                mi.verified_manufacturer_email,
                mi.email_status,
                mi.gmail_message_id,
                mi.gmail_thread_id,
                mi.email_subject,
                mi.email_body,
                mi.status,
                p.name AS product_name,
                p.brand,
                p.barcode,
                p.ingredients
            FROM manufacturer_inquiries mi
            JOIN products p ON p.id = mi.product_id
            WHERE mi.id = ?;
            """,
            (inquiry_id,),
        ).fetchone()
    return dict(row) if row else None


def _find_matching_inquiry(
    request: ManufacturerResponseRequest,
    ingredient: str,
    db_path: Path,
) -> dict[str, Any] | None:
    with closing(get_connection(db_path)) as connection:
        rows = connection.execute(
            """
            SELECT
                mi.id,
                mi.product_id,
                mi.ingredient_term,
                mi.requested_ingredients_json,
                mi.manufacturer_email,
                mi.email_subject,
                mi.email_body,
                mi.status,
                p.name AS product_name,
                p.brand,
                p.barcode,
                p.ingredients
            FROM manufacturer_inquiries mi
            JOIN products p ON p.id = mi.product_id
            WHERE lower(mi.ingredient_term) = lower(?)
            ORDER BY mi.created_at DESC;
            """,
            (ingredient,),
        ).fetchall()

    barcode = (request.barcode or "").strip()
    manual_hash = _product_manual_hash(
        {
            "name": request.product_name or "Manual product",
            "brand": request.brand or "",
            "ingredients": request.ingredients_text or "",
        }
    )
    for row in rows:
        row_data = dict(row)
        if barcode and row_data.get("barcode") == barcode:
            return row_data
        if not barcode:
            row_hash = _product_manual_hash(
                {
                    "name": row_data.get("product_name") or "Manual product",
                    "brand": row_data.get("brand") or "",
                    "ingredients": row_data.get("ingredients") or "",
                }
            )
            if row_hash == manual_hash:
                return row_data
    return None


def _store_manufacturer_response(
    inquiry: dict[str, Any],
    response_text: str,
    analyzed_status: str,
    analysis_notes: str,
    confirmed_ingredients: list[str],
    unresolved_ingredients: list[str],
    db_path: Path,
) -> dict[str, str] | None:
    """Store a manufacturer response and create a user notification draft."""
    product_id = int(inquiry["product_id"])
    product_name = str(inquiry.get("product_name") or "this product")
    ingredients_text = str(inquiry.get("ingredients") or "")
    doubtful_ingredient = str(inquiry.get("ingredient_term") or "")

    with closing(get_connection(db_path)) as connection:
        connection.execute(
            """
            INSERT INTO manufacturer_responses (
                inquiry_id,
                response_text,
                analyzed_status,
                analysis_notes,
                ingredients_text,
                doubtful_ingredient,
                confirmed_ingredients_json,
                unresolved_ingredients_json,
                verification_source,
                response_date,
                recheck_required
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'manufacturer_response', CURRENT_TIMESTAMP, 0);
            """,
            (
                int(inquiry["id"]),
                response_text.strip(),
                analyzed_status,
                analysis_notes,
                ingredients_text,
                doubtful_ingredient,
                json.dumps(confirmed_ingredients),
                json.dumps(unresolved_ingredients),
            ),
        )
        connection.execute(
            "UPDATE manufacturer_inquiries SET status = 'response_received' WHERE id = ?;",
            (int(inquiry["id"]),),
        )
        notification_draft = _create_user_notification_if_needed(
            connection,
            product_id,
            product_name,
            analyzed_status,
        )
        connection.commit()
    return notification_draft


def _requested_ingredients_from_inquiry(inquiry: dict[str, Any]) -> list[str]:
    raw_json = inquiry.get("requested_ingredients_json")
    if raw_json:
        try:
            loaded = json.loads(str(raw_json))
            if isinstance(loaded, list):
                return [str(item) for item in loaded if str(item).strip()]
        except json.JSONDecodeError:
            pass
    return [part.strip() for part in str(inquiry.get("ingredient_term") or "").split(",") if part.strip()]


def _create_user_notification_if_needed(
    connection: Any,
    product_id: int,
    product_name: str,
    analyzed_status: str,
) -> dict[str, str] | None:
    user_email = _latest_user_email_for_product(connection, product_id)
    if not user_email:
        return None

    subject = f"Update about {product_name}"
    message = (
        f"We received a manufacturer response for {product_name}.\n\n"
        f"Updated status: {analyzed_status}\n\n"
        "Manufacturer Confirmed Suitable is not the same as Halal Certified. "
        "Official Halal Certified status only applies if an official certificate is available.\n\n"
        "This notification is a draft. No email was sent automatically."
    )
    connection.execute(
        """
        INSERT INTO user_notifications (
            product_id,
            user_email,
            subject,
            message,
            status
        )
        VALUES (?, ?, ?, ?, 'draft');
        """,
        (product_id, user_email, subject, message),
    )
    return {
        "to": user_email,
        "subject": subject,
        "message": message,
        "status": "draft",
    }


def _latest_user_email_for_product(connection: Any, product_id: int) -> str:
    row = connection.execute(
        """
        SELECT user_email
        FROM product_checks
        WHERE product_id = ? AND user_email IS NOT NULL AND user_email != ''
        ORDER BY checked_at DESC
        LIMIT 1;
        """,
        (product_id,),
    ).fetchone()
    return str(row["user_email"]) if row else ""
