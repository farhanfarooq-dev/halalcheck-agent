"""Open Food Facts barcode lookup helpers.

Open Food Facts does not require an API key for this public product lookup.
The function always returns a small status dictionary so the UI can explain
whether the API found the product, did not find it, or failed.
"""

from __future__ import annotations

from typing import Any

import config

try:
    import requests
except ModuleNotFoundError:
    class _MissingRequests:
        class RequestException(Exception):
            pass

        @staticmethod
        def get(url: str, timeout: int):
            raise _MissingRequests.RequestException(
                "The requests package is not installed."
            )

    requests = _MissingRequests()


def lookup_product_by_barcode(barcode: str) -> dict[str, Any]:
    """Look up a barcode with Open Food Facts and return structured status.

    Status values:
    - api_found: product was found and normalized fields are returned.
    - api_not_found: API responded, but no product exists for the barcode.
    - api_forbidden: API returned HTTP 403, often because User-Agent is missing.
    - api_error: request failed, JSON was invalid, or another API issue occurred.
    - manual_input: no barcode was provided.
    """
    clean_barcode = barcode.strip()
    if not clean_barcode:
        return {
            "lookup_status": "manual_input",
            "lookup_error": "",
            "barcode": "",
            "source": "manual",
        }

    url = _build_product_url(clean_barcode)
    headers = _build_request_headers()

    try:
        response = requests.get(url, headers=headers, timeout=10)
        status_code = getattr(response, "status_code", None)
        if status_code == 403:
            return _error_result(
                lookup_status="api_forbidden",
                barcode=clean_barcode,
                url=url,
                response=response,
                error_message="HTTP 403 Forbidden",
            )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        return _error_result(
            lookup_status="api_error",
            barcode=clean_barcode,
            url=url,
            error_message=str(exc),
        )

    if payload.get("status") != 1:
        return {
            "lookup_status": "api_not_found",
            "lookup_error": "",
            "barcode": clean_barcode,
            "source": "open_food_facts",
            "api_url": url,
            "http_status_code": 200,
            "response_preview": "",
        }

    product = payload.get("product") or {}
    ingredients = (
        product.get("ingredients_text")
        or product.get("ingredients_text_en")
        or product.get("ingredients_text_de")
        or ""
    )

    return {
        "lookup_status": "api_found",
        "lookup_error": "",
        "barcode": clean_barcode,
        "name": product.get("product_name") or product.get("product_name_en") or "",
        "brand": product.get("brands") or "",
        "ingredients": ingredients,
        "fetched_ingredients": ingredients,
        "quantity": product.get("quantity") or "",
        "source": "open_food_facts",
        "manufacturer_email": "",
        "official_certificate_available": False,
        "api_url": url,
        "http_status_code": 200,
        "response_preview": "",
    }


def demo_lookup(barcode: str = "3017620422003") -> None:
    """Small manual demo for local testing."""
    result = lookup_product_by_barcode(barcode)
    print("Lookup result:")
    for key, value in result.items():
        print(f"{key}: {value}")


def _build_product_url(barcode: str) -> str:
    base_url = config.OPENFOODFACTS_BASE_URL.rstrip("/")
    return f"{base_url}/api/v2/product/{barcode}.json"


def _build_request_headers() -> dict[str, str]:
    contact_email = config.FROM_EMAIL or "contact-email-not-configured"
    user_agent = f"{config.APP_NAME}/{config.APP_VERSION} ({contact_email})"
    return {
        "User-Agent": user_agent,
        "Accept": "application/json",
    }


def _error_result(
    lookup_status: str,
    barcode: str,
    url: str,
    error_message: str,
    response: Any | None = None,
) -> dict[str, Any]:
    status_code = getattr(response, "status_code", None) if response else None
    response_text = getattr(response, "text", "") if response else ""
    return {
        "lookup_status": lookup_status,
        "lookup_error": error_message,
        "barcode": barcode,
        "source": "open_food_facts",
        "api_url": url,
        "http_status_code": status_code,
        "response_preview": response_text[:300],
    }


if __name__ == "__main__":
    demo_lookup()
