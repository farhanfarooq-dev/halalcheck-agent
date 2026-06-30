"""Tests for the lightweight FastAPI backend."""

from pathlib import Path

from fastapi.testclient import TestClient

import api


def test_check_product_and_store_manufacturer_response(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "api-test.db"
    monkeypatch.setattr(api, "DB_PATH", db_path)
    monkeypatch.setattr(api.config, "LLM_PROVIDER", "local")
    monkeypatch.setattr(api.config, "OPENAI_API_KEY", "")
    monkeypatch.setattr(api.config, "GEMINI_API_KEY", "")

    client = TestClient(api.app)
    check_response = client.post(
        "/check-product",
        json={
            "product_name": "API Biscuit",
            "ingredients": "Sugar, E471",
            "manufacturer_email": "quality@example.com",
            "user_email": "customer@example.com",
            "language": "en",
        },
    )

    assert check_response.status_code == 200
    check_payload = check_response.json()
    assert check_payload["decision"]["status"] == "Doubtful / Needs Verification"
    inquiry_id = check_payload["manufacturer_inquiry"]["inquiry"]["id"]

    response = client.post(
        "/manufacturer-response",
        json={
            "inquiry_id": inquiry_id,
            "response_text": "The E471 used in this product is plant-based.",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["stored"] is True
    assert payload["analyzed_status"] == "Manufacturer Confirmed Suitable"
    assert payload["notification_draft"]["to"] == "customer@example.com"
