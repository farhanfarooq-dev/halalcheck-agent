"""Manufacturer email draft and optional SMTP sending helpers.

Email sending is intentionally disabled by default. In demo mode the app only
creates human-reviewable drafts, which keeps the project safe for bootcamp
presentations.
"""

from __future__ import annotations

import smtplib
from email.message import EmailMessage
from email.utils import formataddr
from typing import Any

import config


def generate_manufacturer_email_draft(
    product_data: dict[str, Any],
    doubtful_issue: dict[str, str],
) -> dict[str, str]:
    """Create a short, natural customer email draft."""
    product_label = _product_label(product_data)
    product_name_line = f"Product: {product_label}"
    brand = str(product_data.get("brand") or "").strip()
    barcode = str(product_data.get("barcode") or "").strip()
    ingredient = doubtful_issue.get("ingredient") or "the ingredient"
    signature = _signature()

    detail_lines = [product_name_line]
    if brand:
        detail_lines.append(f"Brand: {brand}")
    if barcode:
        detail_lines.append(f"Barcode: {barcode}")
    detail_lines.append(f"Ingredient: {ingredient}")

    body = (
        "Dear Sir or Madam,\n\n"
        "I hope you are well.\n\n"
        "I have a question about one of the ingredients in your product:\n\n"
        + "\n".join(detail_lines)
        + "\n\n"
        "Could you please confirm the source of this ingredient? For example, "
        "is it plant-based, animal-based, microbial, synthetic, or alcohol-derived?\n\n"
        "This information would help me understand whether the product is suitable "
        "for my dietary requirements.\n\n"
        "Thank you very much for your help.\n\n"
        f"{signature}"
    )

    return {
        "subject": f"Question about ingredient source in {product_label}",
        "body": body,
        "sender": _formatted_sender(),
        "reply_to": config.REPLY_TO_EMAIL.strip(),
    }


def send_email(
    to_email: str,
    subject: str,
    body: str,
) -> dict[str, str]:
    """Send an email only when EMAIL_MODE=send and SMTP settings are complete."""
    if config.EMAIL_MODE.lower() != "send":
        return {
            "status": "draft",
            "warning": "EMAIL_MODE is draft, so no email was sent.",
        }

    missing_fields = _missing_required_email_settings()
    if missing_fields:
        return {
            "status": "not_sent",
            "warning": (
                "EMAIL_MODE is send, but required SMTP settings are missing: "
                + ", ".join(missing_fields)
                + ". No email was sent."
            ),
        }

    message = EmailMessage()
    message["From"] = _formatted_sender()
    message["To"] = to_email
    message["Subject"] = subject
    if config.REPLY_TO_EMAIL.strip():
        message["Reply-To"] = config.REPLY_TO_EMAIL.strip()
    message.set_content(body)

    with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT) as smtp:
        smtp.starttls()
        smtp.login(config.SMTP_USER, config.SMTP_PASSWORD)
        smtp.send_message(message)

    return {"status": "sent", "warning": ""}


def _product_label(product_data: dict[str, Any]) -> str:
    product_name = str(product_data.get("name") or "").strip()
    barcode = str(product_data.get("barcode") or "").strip()

    if product_name and product_name.lower() != "manual product":
        return product_name
    if barcode:
        return f"your product with barcode {barcode}"
    return "your product"


def _signature() -> str:
    sender_name = config.SENDER_DISPLAY_NAME.strip()
    if sender_name:
        return f"Kind regards,\n{sender_name}"
    return "Kind regards"


def _formatted_sender() -> str:
    from_email = config.FROM_EMAIL.strip()
    sender_name = config.SENDER_DISPLAY_NAME.strip()
    if from_email and sender_name:
        return formataddr((sender_name, from_email))
    return from_email


def _missing_required_email_settings() -> list[str]:
    """Return missing settings that are required before real email sending."""
    required_settings = {
        "SMTP_HOST": config.SMTP_HOST,
        "SMTP_USER": config.SMTP_USER,
        "SMTP_PASSWORD": config.SMTP_PASSWORD,
        "FROM_EMAIL": config.FROM_EMAIL,
    }
    return [name for name, value in required_settings.items() if not value]
