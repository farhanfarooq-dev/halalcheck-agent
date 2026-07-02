"""Tests for safe Gmail manufacturer inquiry workflow."""

from __future__ import annotations

from contextlib import closing
from pathlib import Path

import gmail_workflow
from agents import (
    STATUS_MANUFACTURER_CONFIRMED,
    halal_decision_agent,
    ingredient_analysis_agent,
    manufacturer_inquiry_agent,
    product_lookup_agent,
)
from database import get_connection


def _create_doubtful_inquiry(db_path: Path) -> tuple[dict, dict, dict]:
    product = product_lookup_agent(
        product_name="Gmail Cookie",
        brand="Gmail Brand",
        ingredients="Sugar, E471, aroma",
        manufacturer_email="quality@example.com",
        db_path=db_path,
    )
    analysis = ingredient_analysis_agent(product)
    decision = halal_decision_agent(product, analysis, db_path=db_path)
    inquiry = manufacturer_inquiry_agent(product, decision, analysis, db_path=db_path)
    return product, analysis, inquiry


def test_manufacturer_email_discovery_returns_candidates() -> None:
    result = gmail_workflow.discover_manufacturer_emails(
        {"brand": "Demo", "manufacturer_email": "quality@example.com"}
    )

    assert result["status"] == "candidates_found"
    assert result["candidates"][0]["email"] == "quality@example.com"
    assert result["candidates"][0]["verification_status"] == "needs human verification"


def test_manufacturer_email_discovery_needs_manual_entry() -> None:
    result = gmail_workflow.discover_manufacturer_emails({"brand": "Unknown"})

    assert result["status"] == "needs_manual_entry"
    assert result["candidates"] == []


def test_gmail_send_is_mocked_and_updates_inquiry(monkeypatch, tmp_path: Path) -> None:
    db_path = tmp_path / "gmail-send.db"
    _, _, inquiry = _create_doubtful_inquiry(db_path)
    monkeypatch.setattr(gmail_workflow.config, "EMAIL_MODE", "approval")
    monkeypatch.setattr(gmail_workflow.config, "GMAIL_SENDER_EMAIL", "halalcheckde@gmail.com")
    captured = {}

    def fake_sender(system_sender, to, subject, body):
        captured["system_sender"] = system_sender
        captured["to"] = to
        return {"gmail_message_id": "msg-1", "gmail_thread_id": "thread-1"}

    result = gmail_workflow.approve_and_send_inquiry(
        inquiry_id=int(inquiry["inquiry"]["id"]),
        recipient_email="quality@example.com",
        subject=inquiry["inquiry"]["email_subject"],
        body=inquiry["inquiry"]["email_body"],
        db_path=db_path,
        gmail_sender=fake_sender,
    )

    assert result["status"] == "sent"
    assert captured["system_sender"] == "halalcheckde@gmail.com"
    assert captured["to"] == "quality@example.com"
    with closing(get_connection(db_path)) as connection:
        row = connection.execute(
            """
            SELECT email_status, gmail_message_id, gmail_thread_id,
                   system_sender_email, manufacturer_email
            FROM manufacturer_inquiries;
            """
        ).fetchone()
    assert row["email_status"] == "sent"
    assert row["gmail_message_id"] == "msg-1"
    assert row["gmail_thread_id"] == "thread-1"
    assert row["system_sender_email"] == "halalcheckde@gmail.com"
    assert row["manufacturer_email"] == "quality@example.com"


def test_gmail_send_stays_draft_by_default(tmp_path: Path) -> None:
    db_path = tmp_path / "gmail-draft.db"
    _, _, inquiry = _create_doubtful_inquiry(db_path)

    result = gmail_workflow.approve_and_send_inquiry(
        inquiry_id=int(inquiry["inquiry"]["id"]),
        recipient_email="quality@example.com",
        subject=inquiry["inquiry"]["email_subject"],
        body=inquiry["inquiry"]["email_body"],
        db_path=db_path,
        gmail_sender=lambda system_sender, to, subject, body: {"gmail_message_id": "should-not-send"},
    )

    assert result["status"] == "draft"


def test_gmail_reply_sync_mocked_stores_response_and_reuses_confirmation(
    monkeypatch,
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "gmail-sync.db"
    product, _, inquiry = _create_doubtful_inquiry(db_path)
    monkeypatch.setattr(gmail_workflow.config, "EMAIL_MODE", "approval")
    gmail_workflow.approve_and_send_inquiry(
        inquiry_id=int(inquiry["inquiry"]["id"]),
        recipient_email="quality@example.com",
        subject=inquiry["inquiry"]["email_subject"],
        body=inquiry["inquiry"]["email_body"],
        db_path=db_path,
        gmail_sender=lambda system_sender, to, subject, body: {
            "gmail_message_id": "msg-2",
            "gmail_thread_id": "thread-2",
        },
    )

    sync_result = gmail_workflow.sync_manufacturer_replies(
        db_path=db_path,
        reply_fetcher=lambda inquiry_row: [
            {
                "source": "gmail_mock",
                "gmail_thread_id": inquiry_row["gmail_thread_id"],
                "body": "The E471 and aroma are plant-based and non-alcohol.",
            }
        ],
    )

    assert sync_result["count"] == 1
    assert sync_result["matched_replies"][0]["analyzed_status"] == STATUS_MANUFACTURER_CONFIRMED

    refreshed_product = product_lookup_agent(
        product_name=product["name"],
        brand=product["brand"],
        ingredients=product["ingredients"],
        db_path=db_path,
    )
    refreshed_analysis = ingredient_analysis_agent(refreshed_product)
    refreshed_decision = halal_decision_agent(
        refreshed_product,
        refreshed_analysis,
        db_path=db_path,
    )

    assert refreshed_decision["status"] == STATUS_MANUFACTURER_CONFIRMED
    assert refreshed_decision["result_source"] == "stored manufacturer confirmation"


def test_user_email_is_notification_only_not_sender(monkeypatch, tmp_path: Path) -> None:
    db_path = tmp_path / "gmail-user-email.db"
    product, analysis, inquiry = _create_doubtful_inquiry(db_path)
    monkeypatch.setattr(gmail_workflow.config, "EMAIL_MODE", "approval")
    monkeypatch.setattr(gmail_workflow.config, "GMAIL_SENDER_EMAIL", "halalcheckde@gmail.com")
    with closing(get_connection(db_path)) as connection:
        connection.execute(
            "UPDATE manufacturer_inquiries SET user_email = ? WHERE id = ?;",
            ("customer@example.com", int(inquiry["inquiry"]["id"])),
        )
        connection.execute(
            """
            INSERT INTO product_checks (
                product_id, user_email, language, final_status, explanation,
                detected_concerns_json
            )
            VALUES (?, 'customer@example.com', 'en', 'Doubtful / Needs Verification', '', '[]');
            """,
            (int(inquiry["inquiry"]["product_id"]),),
        )
        connection.commit()

    captured = {}
    gmail_workflow.approve_and_send_inquiry(
        inquiry_id=int(inquiry["inquiry"]["id"]),
        recipient_email="quality@example.com",
        subject=inquiry["inquiry"]["email_subject"],
        body=inquiry["inquiry"]["email_body"],
        db_path=db_path,
        gmail_sender=lambda system_sender, to, subject, body: captured.update(
            {"system_sender": system_sender, "to": to}
        ) or {"gmail_message_id": "msg-3", "gmail_thread_id": "thread-3"},
    )
    gmail_workflow.sync_manufacturer_replies(
        db_path=db_path,
        reply_fetcher=lambda inquiry_row: [
            {
                "gmail_thread_id": inquiry_row["gmail_thread_id"],
                "body": "The E471 and aroma are plant-based and non-alcohol.",
            }
        ],
    )

    assert captured["system_sender"] == "halalcheckde@gmail.com"
    assert captured["to"] == "quality@example.com"
    assert captured["system_sender"] != "customer@example.com"
    with closing(get_connection(db_path)) as connection:
        notification = connection.execute(
            "SELECT user_email, status FROM user_notifications;"
        ).fetchone()
        response = connection.execute(
            """
            SELECT system_sender_email, manufacturer_email, user_email, verification_source
            FROM manufacturer_responses;
            """
        ).fetchone()
    assert notification["user_email"] == "customer@example.com"
    assert notification["status"] == "draft"
    assert response["system_sender_email"] == "halalcheckde@gmail.com"
    assert response["manufacturer_email"] == "quality@example.com"
    assert response["user_email"] == "customer@example.com"
    assert response["verification_source"] == "manufacturer_response"


def test_reply_sync_matches_reference_id_without_thread(monkeypatch, tmp_path: Path) -> None:
    db_path = tmp_path / "gmail-reference-match.db"
    _, _, inquiry = _create_doubtful_inquiry(db_path)
    monkeypatch.setattr(gmail_workflow.config, "EMAIL_MODE", "approval")
    gmail_workflow.approve_and_send_inquiry(
        inquiry_id=int(inquiry["inquiry"]["id"]),
        recipient_email="quality@example.com",
        subject=inquiry["inquiry"]["email_subject"],
        body=inquiry["inquiry"]["email_body"],
        db_path=db_path,
        gmail_sender=lambda system_sender, to, subject, body: {
            "gmail_message_id": "msg-4",
            "gmail_thread_id": "thread-4",
        },
    )

    result = gmail_workflow.sync_manufacturer_replies(
        db_path=db_path,
        reply_fetcher=lambda inquiry_row: [
            {
                "subject": "Re: ingredient source",
                "body": f"Reference: HC-{inquiry_row['id']} The E471 and aroma are plant-based and non-alcohol.",
            }
        ],
    )

    assert result["count"] == 1
    assert result["matched_replies"][0]["analyzed_status"] == STATUS_MANUFACTURER_CONFIRMED
