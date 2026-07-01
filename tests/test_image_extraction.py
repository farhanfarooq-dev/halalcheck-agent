"""Tests for optional ingredient-label image extraction."""

from __future__ import annotations

from io import BytesIO

import image_extraction


class UploadedImage(BytesIO):
    name = "ingredients.png"
    type = "image/png"


def test_image_extraction_requires_openai_configuration(monkeypatch) -> None:
    monkeypatch.setattr(image_extraction.config, "LLM_PROVIDER", "local")
    monkeypatch.setattr(image_extraction.config, "OPENAI_API_KEY", "")

    result = image_extraction.extract_ingredients_from_image(UploadedImage(b"fake"))

    assert result["status"] == "unavailable"
    assert result["ingredients_text"] == ""
    assert "OpenAI vision support" in result["message"]


def test_image_extraction_returns_mocked_plain_ingredient_text(monkeypatch) -> None:
    monkeypatch.setattr(image_extraction.config, "LLM_PROVIDER", "openai")
    monkeypatch.setattr(image_extraction.config, "OPENAI_API_KEY", "fake-key")
    monkeypatch.setattr(
        image_extraction,
        "_extract_with_openai_vision",
        lambda image_bytes, mime_type: "Ingredients: Sugar, wheat flour, E471",
    )

    result = image_extraction.extract_ingredients_from_image(UploadedImage(b"fake"))

    assert result["status"] == "ok"
    assert result["ingredients_text"] == "Sugar, wheat flour, E471"
    assert "review and edit" in result["message"]
