"""Tests for Open Food Facts lookup normalization."""

import product_lookup


class FakeResponse:
    def __init__(self, payload, status_code=200, text=""):
        self.payload = payload
        self.status_code = status_code
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise product_lookup.requests.RequestException(f"HTTP {self.status_code}")
        return None

    def json(self):
        return self.payload


def test_lookup_product_by_barcode_normalizes_open_food_facts_response(monkeypatch):
    captured = {}

    def fake_get(url, headers, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["timeout"] = timeout
        return FakeResponse(
            {
                "status": 1,
                "product": {
                    "product_name": "Demo Spread",
                    "brands": "Demo Brand",
                    "ingredients_text": "Sugar, cocoa, E471",
                    "quantity": "400 g",
                },
            }
        )

    monkeypatch.setattr(product_lookup.requests, "get", fake_get)

    result = product_lookup.lookup_product_by_barcode("12345")

    assert captured["url"] == "https://world.openfoodfacts.org/api/v2/product/12345.json"
    assert captured["headers"]["Accept"] == "application/json"
    assert captured["headers"]["User-Agent"].startswith("AI-HalalCheck-Agent/1.0 (")
    assert captured["timeout"] == 10
    assert result["lookup_status"] == "api_found"
    assert result["barcode"] == "12345"
    assert result["name"] == "Demo Spread"
    assert result["brand"] == "Demo Brand"
    assert result["ingredients"] == "Sugar, cocoa, E471"
    assert result["fetched_ingredients"] == "Sugar, cocoa, E471"
    assert result["quantity"] == "400 g"


def test_lookup_product_by_barcode_found_without_ingredients(monkeypatch):
    def fake_get(url, headers, timeout):
        return FakeResponse(
            {
                "status": 1,
                "product": {
                    "product_name": "Water Bottle",
                    "brands": "Demo Water",
                    "quantity": "500 ml",
                },
            }
        )

    monkeypatch.setattr(product_lookup.requests, "get", fake_get)

    result = product_lookup.lookup_product_by_barcode("55555")

    assert result["lookup_status"] == "api_found"
    assert result["name"] == "Water Bottle"
    assert result["ingredients"] == ""
    assert result["fetched_ingredients"] == ""


def test_lookup_product_by_barcode_returns_api_not_found(monkeypatch):
    def fake_get(url, headers, timeout):
        return FakeResponse({"status": 0})

    monkeypatch.setattr(product_lookup.requests, "get", fake_get)

    result = product_lookup.lookup_product_by_barcode("00000")

    assert result["lookup_status"] == "api_not_found"
    assert result["barcode"] == "00000"


def test_lookup_product_by_barcode_returns_forbidden_status(monkeypatch):
    def fake_get(url, headers, timeout):
        return FakeResponse(
            {"error": "Forbidden"},
            status_code=403,
            text="Forbidden: please provide a valid User-Agent",
        )

    monkeypatch.setattr(product_lookup.requests, "get", fake_get)

    result = product_lookup.lookup_product_by_barcode("403403")

    assert result["lookup_status"] == "api_forbidden"
    assert result["http_status_code"] == 403
    assert "Forbidden" in result["response_preview"]


def test_lookup_product_by_barcode_returns_error_status(monkeypatch):
    def fake_get(url, headers, timeout):
        raise product_lookup.requests.RequestException("network failed")

    monkeypatch.setattr(product_lookup.requests, "get", fake_get)

    result = product_lookup.lookup_product_by_barcode("99999")

    assert result["lookup_status"] == "api_error"
    assert "network failed" in result["lookup_error"]


def test_lookup_product_by_barcode_without_barcode_returns_manual_status():
    result = product_lookup.lookup_product_by_barcode("")

    assert result["lookup_status"] == "manual_input"
