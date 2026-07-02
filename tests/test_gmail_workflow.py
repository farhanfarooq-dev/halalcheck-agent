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

    result = gmail_workflow.approve_and_send_inquiry(
        inquiry_id=int(inquiry["inquiry"]["id"]),
        recipient_email="quality@example.com",
        subject=inquiry["inquiry"]["email_subject"],
        body=inquiry["inquiry"]["email_body"],
        db_path=db_path,
        gmail_sender=lambda to, subject, body: {
            "gmail_message_id": "msg-1",
            "gmail_thread_id": "thread-1",
        },
    )

    assert result["status"] == "sent"
    with closing(get_connection(db_path)) as connection:
        row = connection.execute(
            "SELECT email_status, gmail_message_id, gmail_thread_id FROM manufacturer_inquiries;"
        ).fetchone()
    assert row["email_status"] == "sent"
    assert row["gmail_message_id"] == "msg-1"
    assert row["gmail_thread_id"] == "thread-1"


def test_gmail_send_stays_draft_by_default(tmp_path: Path) -> None:
    db_path = tmp_path / "gmail-draft.db"
    _, _, inquiry = _create_doubtful_inquiry(db_path)

    result = gmail_workflow.approve_and_send_inquiry(
        inquiry_id=int(inquiry["inquiry"]["id"]),
        recipient_email="quality@example.com",
        subject=inquiry["inquiry"]["email_subject"],
        body=inquiry["inquiry"]["email_body"],
        db_path=db_path,
        gmail_sender=lambda to, subject, body: {"gmail_message_id": "should-not-send"},
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
        gmail_sender=lambda to, subject, body: {
            "gmail_message_id": "msg-2",
            "gmail_thread_id": "thread-2",
        },
    )

    sync_result = gmail_workflow.sync_manufacturer_replies(
        db_path=db_path,
        reply_fetcher=lambda inquiry_row: [
            {
                "source": "gmail_mock",
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
