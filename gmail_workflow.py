"""Safe Gmail workflow helpers for manufacturer inquiries.

The functions in this module are human-in-the-loop by design. They never send
mail while EMAIL_MODE=draft, and tests can inject mocked senders/reply fetchers.
"""

from __future__ import annotations

import base64
import json
import re
from contextlib import closing
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Callable

import config
from agents import STATUS_MANUFACTURER_CONFIRMED, analyze_manufacturer_response
from database import DB_PATH, get_connection, initialize_database

EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)
GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]


def discover_manufacturer_emails(product_data: dict[str, Any]) -> dict[str, Any]:
    """Return possible manufacturer emails with a human-verification status."""
    candidates: list[dict[str, str]] = []

    for source_field in ("manufacturer_email", "contact_email", "email"):
        email = str(product_data.get(source_field) or "").strip()
        if _looks_like_email(email):
            candidates.append(
                {
                    "email": email,
                    "source": source_field,
                    "verification_status": "needs human verification",
                }
            )

    for source_field in ("website", "product_url", "contact_url", "api_url"):
        value = str(product_data.get(source_field) or "")
        for email in EMAIL_RE.findall(value):
            candidates.append(
                {
                    "email": email,
                    "source": source_field,
                    "verification_status": "needs human verification",
                }
            )

    unique_candidates = _dedupe_candidates(candidates)
    if unique_candidates:
        return {
            "status": "candidates_found",
            "candidates": unique_candidates,
            "message": "Possible manufacturer emails found. Please verify before sending.",
        }

    return {
        "status": "needs_manual_entry",
        "candidates": [],
        "message": "No reliable manufacturer email was found. Please enter it manually.",
    }


def gmail_is_configured() -> bool:
    """Return True when Gmail OAuth paths and sender are configured."""
    return bool(
        config.GMAIL_SENDER_EMAIL.strip()
        and config.GMAIL_CREDENTIALS_PATH.strip()
        and config.GMAIL_TOKEN_PATH.strip()
    )


def gmail_sending_allowed() -> bool:
    """Return True only for modes that allow human-approved sending."""
    return config.EMAIL_MODE.lower() in {"approval", "send"} and gmail_is_configured()


def approve_and_send_inquiry(
    inquiry_id: int,
    recipient_email: str,
    subject: str,
    body: str,
    db_path: Path = DB_PATH,
    gmail_sender: Callable[[str, str, str, str], dict[str, str]] | None = None,
) -> dict[str, str]:
    """Send one reviewed inquiry only after an explicit human action."""
    initialize_database(db_path)
    recipient_email = recipient_email.strip()
    if not _looks_like_email(recipient_email):
        return {"status": "not_sent", "message": "Please confirm a valid recipient email."}
    if config.EMAIL_MODE.lower() == "draft":
        return {"status": "draft", "message": "EMAIL_MODE=draft, so no email was sent."}
    if not gmail_sending_allowed() and gmail_sender is None:
        return {"status": "not_configured", "message": "Gmail is not configured for sending."}

    system_sender_email = config.GMAIL_SENDER_EMAIL.strip()
    sender = gmail_sender or _send_with_gmail_api
    try:
        send_result = sender(system_sender_email, recipient_email, subject, body)
    except Exception as exc:
        _mark_inquiry_send_error(inquiry_id, str(exc), db_path)
        return {"status": "error", "message": f"Gmail send failed: {exc}"}

    gmail_message_id = str(send_result.get("gmail_message_id") or send_result.get("id") or "")
    gmail_thread_id = str(send_result.get("gmail_thread_id") or send_result.get("threadId") or "")
    with closing(get_connection(db_path)) as connection:
        connection.execute(
            """
            UPDATE manufacturer_inquiries
            SET manufacturer_email = ?, system_sender_email = ?,
                verified_manufacturer_email = ?, email_status = 'sent',
                gmail_message_id = ?, gmail_thread_id = ?,
                sent_at = CURRENT_TIMESTAMP, send_error = ''
            WHERE id = ?;
            """,
            (
                recipient_email,
                system_sender_email,
                recipient_email,
                gmail_message_id,
                gmail_thread_id,
                inquiry_id,
            ),
        )
        _store_verified_contact(connection, recipient_email, inquiry_id)
        connection.commit()

    return {
        "status": "sent",
        "message": "Manufacturer inquiry sent after approval.",
        "gmail_message_id": gmail_message_id,
        "gmail_thread_id": gmail_thread_id,
        "system_sender_email": system_sender_email,
        "recipient_email": recipient_email,
    }


def sync_manufacturer_replies(
    db_path: Path = DB_PATH,
    reply_fetcher: Callable[[dict[str, Any]], list[dict[str, str]]] | None = None,
) -> dict[str, Any]:
    """Find replies for sent inquiries and store matched manufacturer responses."""
    initialize_database(db_path)
    sent_inquiries = _fetch_sent_inquiries(db_path)
    stored_replies: list[dict[str, Any]] = []

    for inquiry in sent_inquiries:
        replies = reply_fetcher(inquiry) if reply_fetcher else _fetch_gmail_replies(inquiry)
        for reply in replies:
            if not _reply_matches_inquiry(reply, inquiry):
                continue
            response_text = str(reply.get("body") or reply.get("response_text") or "").strip()
            if not response_text:
                continue
            requested_ingredients = _requested_ingredients_from_inquiry(inquiry)
            analysis = analyze_manufacturer_response(response_text, requested_ingredients)
            response_id = _store_manufacturer_response_from_reply(
                inquiry=inquiry,
                response_text=response_text,
                analyzed_status=analysis["analyzed_status"],
                analysis_notes=analysis["analysis_notes"],
                confirmed_ingredients=analysis.get("confirmed_ingredients", []),
                unresolved_ingredients=analysis.get("unresolved_ingredients", []),
                source="manufacturer_response",
                db_path=db_path,
            )
            stored_replies.append(
                {
                    "inquiry_id": int(inquiry["id"]),
                    "response_id": response_id,
                    "analyzed_status": analysis["analyzed_status"],
                    "confirmed_ingredients": analysis.get("confirmed_ingredients", []),
                    "unresolved_ingredients": analysis.get("unresolved_ingredients", []),
                }
            )
            break

    return {"status": "ok", "matched_replies": stored_replies, "count": len(stored_replies)}


def _send_with_gmail_api(
    system_sender_email: str,
    to_email: str,
    subject: str,
    body: str,
) -> dict[str, str]:
    service = _build_gmail_service(validate_sender=True)
    message = EmailMessage()
    message["To"] = to_email
    message["From"] = system_sender_email
    message["Subject"] = subject
    message["Reply-To"] = system_sender_email
    message.set_content(body)
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
    result = service.users().messages().send(userId="me", body={"raw": raw}).execute()
    return {
        "gmail_message_id": str(result.get("id") or ""),
        "gmail_thread_id": str(result.get("threadId") or ""),
    }


def _fetch_gmail_replies(inquiry: dict[str, Any]) -> list[dict[str, str]]:
    if not gmail_is_configured():
        return []
    service = _build_gmail_service()
    thread_id = str(inquiry.get("gmail_thread_id") or "")
    if not thread_id:
        return []
    thread = service.users().threads().get(userId="me", id=thread_id, format="full").execute()
    messages = thread.get("messages", [])[1:]
    replies = []
    for message in messages:
        body = _extract_gmail_plain_text(message.get("payload", {}))
        if body:
            replies.append({"source": "gmail", "body": body, "gmail_thread_id": thread_id})
    return replies


def _build_gmail_service(validate_sender: bool = False) -> Any:
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Gmail libraries are not installed. Install google-api-python-client, "
            "google-auth-oauthlib, and google-auth."
        ) from exc

    token_path = Path(config.GMAIL_TOKEN_PATH)
    credentials_path = Path(config.GMAIL_CREDENTIALS_PATH)
    credentials = None
    if token_path.exists():
        credentials = Credentials.from_authorized_user_file(str(token_path), GMAIL_SCOPES)
    if not credentials or not credentials.valid:
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
        else:
            if not credentials_path.exists():
                raise RuntimeError("Gmail credentials file was not found.")
            flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), GMAIL_SCOPES)
            credentials = flow.run_local_server(port=0)
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(credentials.to_json(), encoding="utf-8")
    service = build("gmail", "v1", credentials=credentials)
    if validate_sender:
        profile = service.users().getProfile(userId="me").execute()
        account_email = str(profile.get("emailAddress") or "").lower()
        expected_email = config.GMAIL_SENDER_EMAIL.strip().lower()
        if account_email and account_email != expected_email:
            raise RuntimeError(
                "Configured Gmail token account does not match GMAIL_SENDER_EMAIL."
            )
    return service


def _fetch_sent_inquiries(db_path: Path) -> list[dict[str, Any]]:
    with closing(get_connection(db_path)) as connection:
        rows = connection.execute(
            """
            SELECT
                mi.*,
                p.name AS product_name,
                p.brand,
                p.barcode,
                p.ingredients
            FROM manufacturer_inquiries mi
            JOIN products p ON p.id = mi.product_id
            LEFT JOIN manufacturer_responses mr ON mr.inquiry_id = mi.id
            WHERE mi.email_status = 'sent' AND mr.id IS NULL
            ORDER BY mi.sent_at DESC;
            """
        ).fetchall()
    return [dict(row) for row in rows]



def _reply_matches_inquiry(reply: dict[str, str], inquiry: dict[str, Any]) -> bool:
    """Match replies from the central system inbox to a sent inquiry."""
    thread_id = str(inquiry.get("gmail_thread_id") or "").strip()
    if thread_id and str(reply.get("gmail_thread_id") or reply.get("thread_id") or "").strip() == thread_id:
        return True

    haystack = " ".join(
        [
            str(reply.get("subject") or ""),
            str(reply.get("body") or reply.get("response_text") or ""),
        ]
    ).lower()
    inquiry_id = str(inquiry.get("id") or "")
    if inquiry_id and f"hc-{inquiry_id}" in haystack:
        return True

    subject = str(inquiry.get("email_subject") or "").lower()
    product_name = str(inquiry.get("product_name") or "").lower()
    barcode = str(inquiry.get("barcode") or "").lower()
    return bool(
        (subject and subject in haystack)
        or (product_name and product_name in haystack)
        or (barcode and barcode in haystack)
    )

def _store_manufacturer_response_from_reply(
    inquiry: dict[str, Any],
    response_text: str,
    analyzed_status: str,
    analysis_notes: str,
    confirmed_ingredients: list[str],
    unresolved_ingredients: list[str],
    source: str,
    db_path: Path,
) -> int:
    with closing(get_connection(db_path)) as connection:
        cursor = connection.execute(
            """
            INSERT INTO manufacturer_responses (
                inquiry_id, response_text, analyzed_status, analysis_notes,
                ingredients_text, doubtful_ingredient, confirmed_ingredients_json,
                unresolved_ingredients_json, system_sender_email, manufacturer_email,
                user_email, verification_source, response_date,
                recheck_required
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, 0);
            """,
            (
                int(inquiry["id"]),
                response_text,
                analyzed_status,
                analysis_notes,
                str(inquiry.get("ingredients") or ""),
                str(inquiry.get("ingredient_term") or ""),
                json.dumps(confirmed_ingredients),
                json.dumps(unresolved_ingredients),
                str(inquiry.get("system_sender_email") or config.GMAIL_SENDER_EMAIL.strip()),
                str(inquiry.get("manufacturer_email") or ""),
                str(inquiry.get("user_email") or ""),
                source,
            ),
        )
        connection.execute(
            """
            UPDATE manufacturer_inquiries
            SET status = 'response_received', reply_received_at = CURRENT_TIMESTAMP
            WHERE id = ?;
            """,
            (int(inquiry["id"]),),
        )
        _create_user_notification_if_needed(
            connection,
            int(inquiry["product_id"]),
            str(inquiry.get("product_name") or "this product"),
            analyzed_status,
        )
        connection.commit()
    return int(cursor.lastrowid)


def _store_verified_contact(connection: Any, email: str, inquiry_id: int) -> None:
    row = connection.execute(
        """
        SELECT p.brand, p.id AS product_id
        FROM manufacturer_inquiries mi
        JOIN products p ON p.id = mi.product_id
        WHERE mi.id = ?;
        """,
        (inquiry_id,),
    ).fetchone()
    if not row:
        return
    connection.execute(
        """
        INSERT INTO manufacturer_contacts (brand, product_id, email, verification_status)
        VALUES (?, ?, ?, 'human_verified');
        """,
        (str(row["brand"] or ""), int(row["product_id"]), email),
    )


def _create_user_notification_if_needed(
    connection: Any,
    product_id: int,
    product_name: str,
    analyzed_status: str,
) -> None:
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
    if not row:
        return
    connection.execute(
        """
        INSERT INTO user_notifications (product_id, user_email, subject, message, status)
        VALUES (?, ?, ?, ?, 'draft');
        """,
        (
            product_id,
            str(row["user_email"]),
            f"Update about {product_name}",
            f"We received a manufacturer response for {product_name}.\n\n"
            f"Updated status: {analyzed_status}\n\n"
            "This notification is a draft. No email was sent automatically.",
        ),
    )


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


def _extract_gmail_plain_text(payload: dict[str, Any]) -> str:
    data = payload.get("body", {}).get("data")
    if data:
        return base64.urlsafe_b64decode(data.encode("ascii")).decode("utf-8", errors="ignore")
    for part in payload.get("parts", []) or []:
        text = _extract_gmail_plain_text(part)
        if text:
            return text
    return ""


def _mark_inquiry_send_error(inquiry_id: int, error: str, db_path: Path) -> None:
    with closing(get_connection(db_path)) as connection:
        connection.execute(
            """
            UPDATE manufacturer_inquiries
            SET email_status = 'send_error', send_error = ?
            WHERE id = ?;
            """,
            (error, inquiry_id),
        )
        connection.commit()


def _dedupe_candidates(candidates: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[str] = set()
    unique = []
    for candidate in candidates:
        email = candidate["email"].lower()
        if email in seen:
            continue
        seen.add(email)
        unique.append(candidate)
    return unique


def _looks_like_email(email: str) -> bool:
    return bool(EMAIL_RE.fullmatch(email.strip()))
