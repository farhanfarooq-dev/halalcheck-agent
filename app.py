"""Streamlit MVP for AI HalalCheck Agent."""

from __future__ import annotations

import json
from contextlib import closing
from typing import Any

import streamlit as st

import config
from agents import (
    FINAL_DOUBTFUL,
    analyze_manufacturer_response,
    halal_decision_agent,
    ingredient_analysis_agent,
    manufacturer_inquiry_agent,
    product_lookup_agent,
    user_communication_agent,
    _product_manual_hash,
)
from database import DB_PATH, get_connection, initialize_database
from image_extraction import extract_ingredients_from_image
from gmail_workflow import (
    approve_and_send_inquiry,
    discover_manufacturer_emails,
    gmail_sending_allowed,
    sync_manufacturer_replies,
)


st.set_page_config(page_title="AI HalalCheck Agent", page_icon="AH", layout="wide")


def main() -> None:
    """Run the Streamlit application."""
    require_access_password()
    initialize_database(DB_PATH)

    st.title("AI HalalCheck Agent")
    st.caption(
        "Decision-support demo. This app does not issue official halal certification."
    )

    page = st.sidebar.radio(
        "Navigation",
        ["Product Check", "History", "Admin Response Review"],
    )

    if page == "Product Check":
        show_product_check_page()
    elif page == "History":
        show_history_page()
    else:
        show_admin_response_review_page()



def require_access_password() -> None:
    """Stop the app unless the optional access password has been entered."""
    access_password = config.APP_ACCESS_PASSWORD.strip()
    if not access_password:
        return
    if st.session_state.get("access_granted") is True:
        return

    entered_password = st.text_input("Access password", type="password")
    if entered_password == access_password:
        st.session_state["access_granted"] = True
        return

    st.warning("Please enter the correct access password.")
    st.stop()

def show_product_check_page() -> None:
    """Collect product details, run agents, and display the result."""
    st.header("Product Check")

    if "ingredients_text" not in st.session_state:
        st.session_state["ingredients_text"] = ""

    uploaded_image = st.file_uploader(
        "Upload ingredient label image (optional)",
        type=["png", "jpg", "jpeg"],
    )
    if st.button("Extract ingredients from image"):
        if uploaded_image is None:
            st.warning("Please upload an ingredient label image first.")
        else:
            extraction_result = extract_ingredients_from_image(uploaded_image)
            if extraction_result["status"] == "ok":
                st.session_state["ingredients_text"] = extraction_result[
                    "ingredients_text"
                ]
                st.success(extraction_result["message"])
            else:
                st.info(extraction_result["message"])

    with st.form("product_check_form"):
        barcode = st.text_input("Barcode")
        product_name = st.text_input("Product name")
        brand = st.text_input("Brand")
        ingredients = st.text_area("Ingredients", height=140, key="ingredients_text")
        manufacturer_email = st.text_input("Manufacturer email")
        user_email = st.text_input("User/customer email (optional)")
        language_label = st.selectbox("Language", ["English", "German"])
        official_certificate_available = st.checkbox(
            "Official halal certificate is available"
        )
        submitted = st.form_submit_button("Check Product")

    if not submitted:
        st.info("Enter product details and click Check Product.")
        return

    language_code = "de" if language_label == "German" else "en"

    product = product_lookup_agent(
        barcode=barcode,
        product_name=product_name,
        brand=brand,
        ingredients=ingredients,
        manufacturer_email=manufacturer_email,
        official_certificate_available=official_certificate_available,
        db_path=DB_PATH,
    )
    show_lookup_warning(product)

    analysis = ingredient_analysis_agent(product)
    product_id = save_product(product)
    product["id"] = product_id
    decision = halal_decision_agent(product, analysis, db_path=DB_PATH)
    inquiry = manufacturer_inquiry_agent(product, decision, analysis, db_path=DB_PATH)
    communication = user_communication_agent(
        product,
        decision,
        analysis,
        language=language_code,
    )

    save_product_check(
        product_id=product_id,
        user_email=user_email,
        language=language_code,
        final_status=decision["status"],
        explanation=communication["explanation"],
        detected_concerns=analysis["detected_concerns"],
        result_source=decision.get("result_source", ""),
    )

    display_product_result(product, analysis, decision, inquiry, communication)


def display_product_result(
    product: dict[str, Any],
    analysis: dict[str, Any],
    decision: dict[str, str],
    inquiry: dict[str, Any],
    communication: dict[str, str],
) -> None:
    """Render the product check result."""
    st.subheader("Result")
    st.metric("Final halal status", decision["status"])

    if decision["status"] == "Unknown" and not product.get("ingredients"):
        st.warning(
            "The ingredient list is empty, so the app cannot analyze this product. "
            "Please enter ingredients manually to get a better result."
        )

    with st.expander("Product summary", expanded=True):
        st.write(
            {
                "name": product.get("name"),
                "brand": product.get("brand"),
                "barcode": product.get("barcode"),
                "quantity": product.get("quantity"),
                "fetched_ingredients": product.get("fetched_ingredients"),
                "lookup_status": product.get("lookup_status"),
                "lookup_error": product.get("lookup_error"),
                "http_status_code": product.get("http_status_code"),
                "api_url": product.get("api_url"),
                "response_preview": product.get("response_preview"),
                "source": product.get("source"),
                "result_source": decision.get("result_source")
                or product.get("result_source"),
                "product_identity_key": product.get("product_identity_key"),
                "recheck_required": product.get("recheck_required"),
                "manufacturer_email": product.get("manufacturer_email"),
            }
        )
    if product.get("recheck_required"):
        st.warning(
            "Recheck Required: the current ingredient list is different from the "
            "stored ingredient list, so old manufacturer confirmation was not reused."
        )

    st.subheader("AI Explanation")
    st.caption(f"Explanation mode: {communication.get('explanation_mode', 'Local')}")
    st.write(communication["explanation"])

    st.subheader("Ingredients checked")
    checked_ingredients = analysis.get("ingredients_text") or ""
    if checked_ingredients.strip():
        st.text_area(
            "Exact ingredient text analyzed",
            value=checked_ingredients,
            height=120,
            disabled=True,
        )
    else:
        st.warning(
            "No ingredient text was available for analysis. Please enter ingredients manually."
        )

    st.subheader("Ingredient analysis")
    if analysis["detected_concerns"]:
        st.dataframe(analysis["detected_concerns"], use_container_width=True)
    elif not checked_ingredients.strip():
        st.info("Ingredient analysis was skipped because no ingredient text was available.")
    else:
        st.success("No known doubtful or not-halal ingredient was detected.")

    if decision["status"] == FINAL_DOUBTFUL and inquiry.get("required"):
        st.subheader("Manufacturer inquiry draft")
        st.info(inquiry["message"])
        inquiry_data = inquiry.get("inquiry", {})
        st.text_input(
            "Draft recipient",
            value=str(
                inquiry_data.get("manufacturer_email")
                or "manufacturer email required"
            ),
            disabled=True,
        )
        st.text_input(
            "Draft sender",
            value=str(inquiry_data.get("sender") or ""),
            disabled=True,
        )
        st.text_input(
            "Reply-To",
            value=str(inquiry_data.get("reply_to") or ""),
            disabled=True,
        )
        requested_ingredients = inquiry_data.get("requested_ingredients") or inquiry.get("requested_ingredients") or []
        if requested_ingredients:
            st.write({"requested_doubtful_ingredients": requested_ingredients})

        discovery = discover_manufacturer_emails(product)
        st.write({"manufacturer_email_discovery": discovery["message"]})
        candidates = discovery.get("candidates", [])
        candidate_emails = [candidate["email"] for candidate in candidates]
        if candidate_emails:
            selected_candidate = st.selectbox(
                "Possible manufacturer emails",
                candidate_emails,
                key=f"email_candidate_{inquiry_data.get('id')}",
            )
        else:
            selected_candidate = str(inquiry_data.get("manufacturer_email") or "")
        recipient_email = st.text_input(
            "Confirmed recipient email",
            value=selected_candidate,
            key=f"recipient_email_{inquiry_data.get('id')}",
        )

        st.text_input(
            "Draft subject",
            value=str(inquiry_data.get("email_subject") or ""),
            disabled=True,
        )
        st.text_area(
            "Draft body",
            value=str(inquiry_data.get("email_body") or ""),
            height=220,
            disabled=True,
        )
        if gmail_sending_allowed():
            if st.button("Approve and Send", key=f"send_inquiry_{inquiry_data.get('id')}"):
                send_result = approve_and_send_inquiry(
                    inquiry_id=int(inquiry_data.get("id")),
                    recipient_email=recipient_email,
                    subject=str(inquiry_data.get("email_subject") or ""),
                    body=str(inquiry_data.get("email_body") or ""),
                    db_path=DB_PATH,
                )
                if send_result["status"] == "sent":
                    st.success(send_result["message"])
                else:
                    st.warning(send_result["message"])
        else:
            st.caption(
                "Gmail sending is not configured or EMAIL_MODE=draft. Draft only; no email was sent."
            )
    elif decision["status"] == "Manufacturer Confirmed Suitable":
        st.info(
            "This product is Manufacturer Confirmed Suitable based on manufacturer "
            "response. It is not Halal Certified. Official Halal Certified status "
            "only applies if an official certificate is available."
        )


def show_history_page() -> None:
    """Show previously checked products."""
    st.header("History")
    rows = fetch_product_check_history()

    if not rows:
        st.info("No product checks have been saved yet.")
        return

    st.dataframe(rows, use_container_width=True)


def show_lookup_warning(product: dict[str, Any]) -> None:
    """Show visible lookup feedback for barcode API failures."""
    lookup_status = product.get("lookup_status")
    if lookup_status == "api_not_found":
        st.warning(
            "Product not found in barcode database. Please enter ingredients manually."
        )
    elif lookup_status == "api_forbidden":
        st.warning(
            "Barcode API access was forbidden. Please check User-Agent configuration."
        )
    elif lookup_status == "api_error":
        st.warning("Barcode API lookup failed. Please enter ingredients manually.")
    elif lookup_status == "api_found" and not str(product.get("fetched_ingredients") or "").strip():
        st.warning(
            "Product found, but ingredient list is missing. Please enter ingredients manually."
        )


def show_admin_response_review_page() -> None:
    """Allow an admin to paste and store a manufacturer response."""
    st.header("Admin Response Review")
    if st.button("Sync manufacturer replies from Gmail"):
        sync_result = sync_manufacturer_replies(DB_PATH)
        st.write(sync_result)

    inquiries = fetch_pending_inquiries()

    if not inquiries:
        st.info("No pending manufacturer inquiries found.")
        return

    labels = [
        f"#{item['id']} - {item['product_name']} - {item['ingredient_term']}"
        for item in inquiries
    ]
    selected_label = st.selectbox("Pending inquiry", labels)
    selected_index = labels.index(selected_label)
    selected_inquiry = inquiries[selected_index]

    st.text_input(
        "Product name",
        value=str(selected_inquiry["product_name"] or ""),
        disabled=True,
    )
    st.text_input(
        "Barcode",
        value=str(selected_inquiry["barcode"] or ""),
        disabled=True,
    )
    requested_ingredients = _requested_ingredients_from_inquiry(selected_inquiry)
    st.text_input(
        "Doubtful ingredients being confirmed",
        value=", ".join(requested_ingredients),
        disabled=True,
    )
    st.text_input(
        "Draft recipient",
        value=str(
            selected_inquiry["manufacturer_email"]
            or "manufacturer email required"
        ),
        disabled=True,
    )
    st.text_input(
        "Draft subject",
        value=str(selected_inquiry["email_subject"] or ""),
        disabled=True,
    )
    st.text_area(
        "Draft body",
        value=selected_inquiry["email_body"],
        height=180,
        disabled=True,
    )

    response_text = st.text_area("Paste manufacturer response", height=180)
    response_analysis = analyze_manufacturer_response(response_text, requested_ingredients)
    st.write(
        {
            "analyzed_status": response_analysis["analyzed_status"],
            "analysis_notes": response_analysis["analysis_notes"],
            "confirmed_ingredients": response_analysis.get("confirmed_ingredients", []),
            "unresolved_ingredients": response_analysis.get("unresolved_ingredients", []),
        }
    )
    st.caption(
        "Manufacturer Confirmed Suitable is not the same as Halal Certified. "
        "Official Halal Certified status only applies if an official certificate is available."
    )

    if st.button("Store Response"):
        if not response_text.strip():
            st.warning("Please paste a manufacturer response before saving.")
            return

        store_manufacturer_response(
            inquiry_id=int(selected_inquiry["id"]),
            response_text=response_text,
            analyzed_status=response_analysis["analyzed_status"],
            analysis_notes=response_analysis["analysis_notes"],
            confirmed_ingredients=response_analysis.get("confirmed_ingredients", []),
            unresolved_ingredients=response_analysis.get("unresolved_ingredients", []),
            product_id=int(selected_inquiry["product_id"]),
            product_name=str(selected_inquiry["product_name"]),
            ingredients_text=str(selected_inquiry["ingredients"] or ""),
            doubtful_ingredient=str(selected_inquiry["ingredient_term"]),
        )
        st.success("Manufacturer response stored and notification draft created if a user email exists.")


def save_product(product: dict[str, Any]) -> int:
    """Insert or update a product and return its database id."""
    with closing(get_connection(DB_PATH)) as connection:
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

def save_product_check(
    product_id: int,
    user_email: str,
    language: str,
    final_status: str,
    explanation: str,
    detected_concerns: list[dict[str, str]],
    result_source: str,
) -> None:
    """Save one product check result."""
    with closing(get_connection(DB_PATH)) as connection:
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


def fetch_product_check_history() -> list[dict[str, str]]:
    """Return saved product checks for the History page."""
    with closing(get_connection(DB_PATH)) as connection:
        rows = connection.execute(
            """
            SELECT
                p.name AS product_name,
                p.barcode,
                pc.final_status,
                pc.result_source,
                pc.checked_at
            FROM product_checks pc
            JOIN products p ON p.id = pc.product_id
            ORDER BY pc.checked_at DESC;
            """
        ).fetchall()

    return [dict(row) for row in rows]


def fetch_pending_inquiries() -> list[dict[str, Any]]:
    """Return inquiries that do not yet have a stored response."""
    with closing(get_connection(DB_PATH)) as connection:
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
                mi.created_at,
                p.name AS product_name,
                p.brand,
                p.barcode,
                p.ingredients
            FROM manufacturer_inquiries mi
            JOIN products p ON p.id = mi.product_id
            LEFT JOIN manufacturer_responses mr ON mr.inquiry_id = mi.id
            WHERE mr.id IS NULL
            ORDER BY mi.created_at DESC;
            """
        ).fetchall()

    return [dict(row) for row in rows]


def store_manufacturer_response(
    inquiry_id: int,
    response_text: str,
    analyzed_status: str,
    analysis_notes: str,
    confirmed_ingredients: list[str],
    unresolved_ingredients: list[str],
    product_id: int,
    product_name: str,
    ingredients_text: str,
    doubtful_ingredient: str,
) -> None:
    """Store a manufacturer response for later decision logic."""
    with closing(get_connection(DB_PATH)) as connection:
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
                inquiry_id,
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
            (inquiry_id,),
        )
        user_email = _latest_user_email_for_product(connection, product_id)
        if user_email:
            subject, message = _notification_draft(product_name, analyzed_status)
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
        connection.commit()


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


def _notification_draft(product_name: str, analyzed_status: str) -> tuple[str, str]:
    subject = f"Update about {product_name}"
    message = (
        f"We received a manufacturer response for {product_name}.\n\n"
        f"Updated status: {analyzed_status}\n\n"
        "Manufacturer Confirmed Suitable is not the same as Halal Certified. "
        "Official Halal Certified status only applies if an official certificate is available.\n\n"
        "This notification is a draft. No email was sent automatically."
    )
    return subject, message


if __name__ == "__main__":
    main()
