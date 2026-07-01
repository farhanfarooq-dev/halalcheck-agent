"""Optional ingredient-label image extraction helpers."""

from __future__ import annotations

import base64
from typing import Any, BinaryIO

import config

EXTRACTION_UNAVAILABLE_MESSAGE = (
    "Image extraction requires OpenAI vision support. Please enter ingredients manually."
)
EXTRACTION_PROMPT = (
    "Extract only the ingredient list from this food label image. Return plain text. "
    "Do not classify halal status."
)


def extract_ingredients_from_image(image_file: BinaryIO | Any) -> dict[str, str]:
    """Extract plain ingredient text from an uploaded label image when configured."""
    if config.LLM_PROVIDER.lower() != "openai" or not config.OPENAI_API_KEY:
        return {
            "status": "unavailable",
            "ingredients_text": "",
            "message": EXTRACTION_UNAVAILABLE_MESSAGE,
        }

    image_bytes = _read_image_bytes(image_file)
    if not image_bytes:
        return {
            "status": "error",
            "ingredients_text": "",
            "message": "No readable image data was found. Please try another image or enter ingredients manually.",
        }

    try:
        extracted_text = _extract_with_openai_vision(
            image_bytes=image_bytes,
            mime_type=_mime_type(image_file),
        )
    except Exception:
        return {
            "status": "error",
            "ingredients_text": "",
            "message": "Image extraction failed. Please enter ingredients manually.",
        }

    clean_text = _clean_extracted_text(extracted_text)
    if not clean_text:
        return {
            "status": "empty",
            "ingredients_text": "",
            "message": "No ingredient text was found. Please enter ingredients manually.",
        }

    return {
        "status": "ok",
        "ingredients_text": clean_text,
        "message": "Ingredients extracted. Please review and edit before checking the product.",
    }


def _extract_with_openai_vision(image_bytes: bytes, mime_type: str) -> str:
    from openai import OpenAI

    client = OpenAI(api_key=config.OPENAI_API_KEY)
    encoded_image = base64.b64encode(image_bytes).decode("ascii")
    response = client.chat.completions.create(
        model=config.OPENAI_MODEL,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": EXTRACTION_PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime_type};base64,{encoded_image}",
                        },
                    },
                ],
            }
        ],
        temperature=0,
        max_tokens=500,
    )
    content = response.choices[0].message.content
    return content or ""


def _read_image_bytes(image_file: BinaryIO | Any) -> bytes:
    if hasattr(image_file, "getvalue"):
        return bytes(image_file.getvalue())
    if hasattr(image_file, "read"):
        position = image_file.tell() if hasattr(image_file, "tell") else None
        data = image_file.read()
        if position is not None and hasattr(image_file, "seek"):
            image_file.seek(position)
        return bytes(data)
    return b""


def _mime_type(image_file: Any) -> str:
    mime_type = str(getattr(image_file, "type", "") or "").strip().lower()
    if mime_type in {"image/png", "image/jpeg", "image/jpg"}:
        return "image/jpeg" if mime_type == "image/jpg" else mime_type
    name = str(getattr(image_file, "name", "") or "").lower()
    if name.endswith(".png"):
        return "image/png"
    return "image/jpeg"


def _clean_extracted_text(text: str) -> str:
    clean_text = text.strip()
    for prefix in ("Ingredients:", "Ingredient list:", "INGREDIENTS:"):
        if clean_text.startswith(prefix):
            clean_text = clean_text[len(prefix):].strip()
    return clean_text.strip("` \n\t")
