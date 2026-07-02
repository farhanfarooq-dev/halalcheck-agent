"""Modular agent layer for the AI HalalCheck Agent.

Each function acts like one small agent with a clear job. Streamlit and FastAPI
will call these functions later, so this file does not contain any UI code.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

import email_service
import product_lookup
import rag_engine
import config
from database import DB_PATH, get_connection, initialize_database
from halal_rules import (
    FINAL_DOUBTFUL,
    FINAL_NO_CONCERN,
    FINAL_NOT_HALAL,
    FINAL_UNKNOWN,
    STATUS_DOUBTFUL,
    STATUS_NOT_HALAL,
    analyze_ingredients,
)


STATUS_HALAL_CERTIFIED = "Halal Certified"
STATUS_MANUFACTURER_CONFIRMED = "Manufacturer Confirmed Suitable"
STATUS_STILL_DOUBTFUL = "Still Doubtful"
REQUIRED_CERTIFICATION_LIMIT_PHRASE = (
    "Manufacturer Confirmed Suitable is not the same as Halal Certified."
)
OFFICIAL_CERTIFICATE_LIMIT_PHRASE = (
    "Halal Certified only applies when official_certificate_available=True "
    "and an official halal certificate is available."
)
DECISION_SUPPORT_PHRASE = (
    "This app is decision support and not an official halal certification authority."
)


def product_lookup_agent(
    barcode: str | None = None,
    product_name: str | None = None,
    brand: str | None = None,
    ingredients: str | None = None,
    manufacturer_email: str | None = None,
    official_certificate_available: bool = False,
    db_path: Path = DB_PATH,
) -> dict[str, Any]:
    """Return structured product data using local DB first, then barcode API."""
    clean_barcode = (barcode or "").strip()

    if clean_barcode:
        stored_product = _find_product_by_barcode(clean_barcode, db_path)
        lookup_result = _lookup_product_by_barcode(clean_barcode)
        if lookup_result and lookup_result.get("lookup_status") == "api_found":
            api_product = _merge_product_data(
                lookup_result,
                barcode=clean_barcode,
                product_name=product_name,
                brand=brand,
                ingredients=ingredients,
                manufacturer_email=manufacturer_email,
                official_certificate_available=official_certificate_available,
                source="open_food_facts",
                lookup_status="api_found",
            )
            if stored_product:
                api_product["id"] = stored_product["id"]
                api_product["previous_stored_ingredients"] = stored_product.get("ingredients", "")
                if _ingredients_changed(
                    stored_product.get("ingredients", ""),
                    api_product.get("ingredients", ""),
                ):
                    api_product["recheck_required"] = True
                    api_product["result_source"] = "fresh ingredient analysis"
                else:
                    api_product["recheck_required"] = False
                    api_product["result_source"] = "local database + barcode refresh"
            return api_product
        if lookup_result and lookup_result.get("lookup_status") in {
            "api_not_found",
            "api_forbidden",
            "api_error",
        }:
            if stored_product:
                stored_product["lookup_status"] = "found_in_database"
                stored_product["lookup_error"] = str(lookup_result.get("lookup_error") or "")
                stored_product["api_url"] = lookup_result.get("api_url", "")
                stored_product["http_status_code"] = lookup_result.get("http_status_code")
                stored_product["response_preview"] = lookup_result.get("response_preview", "")
                stored_product["result_source"] = "local database"
                return stored_product
            return _manual_product_data(
                barcode=clean_barcode,
                product_name=product_name,
                brand=brand,
                ingredients=ingredients,
                manufacturer_email=manufacturer_email,
                official_certificate_available=official_certificate_available,
                lookup_status=str(lookup_result.get("lookup_status")),
                lookup_error=str(lookup_result.get("lookup_error") or ""),
                lookup_metadata=lookup_result,
                source="manual",
            )
        if stored_product:
            stored_product["result_source"] = "local database"
            return stored_product

    return _manual_product_data(
        barcode=clean_barcode or None,
        product_name=product_name,
        brand=brand,
        ingredients=ingredients,
        manufacturer_email=manufacturer_email,
        official_certificate_available=official_certificate_available,
        lookup_status="manual_input",
        lookup_error="",
        lookup_metadata={},
        source="manual",
    )


def _manual_product_data(
    barcode: str | None,
    product_name: str | None,
    brand: str | None,
    ingredients: str | None,
    manufacturer_email: str | None,
    official_certificate_available: bool,
    lookup_status: str,
    lookup_error: str,
    lookup_metadata: dict[str, Any],
    source: str,
) -> dict[str, Any]:
    clean_name = (product_name or "Manual product").strip()
    clean_brand = (brand or "").strip()
    clean_ingredients = (ingredients or "").strip()
    manual_hash = _manual_product_hash(clean_name, clean_brand, clean_ingredients)
    return {
        "id": None,
        "barcode": barcode,
        "manual_product_hash": manual_hash,
        "product_identity_key": barcode or manual_hash,
        "name": clean_name,
        "brand": clean_brand,
        "ingredients": clean_ingredients,
        "fetched_ingredients": "",
        "quantity": "",
        "manufacturer_email": (manufacturer_email or "").strip(),
        "source": source,
        "official_certificate_available": official_certificate_available,
        "lookup_status": lookup_status,
        "lookup_error": lookup_error,
        "api_url": lookup_metadata.get("api_url", ""),
        "http_status_code": lookup_metadata.get("http_status_code"),
        "response_preview": lookup_metadata.get("response_preview", ""),
        "result_source": "manual input",
        "recheck_required": False,
    }


def ingredient_analysis_agent(product_data: dict[str, Any]) -> dict[str, Any]:
    """Analyze product ingredients using the rule checker."""
    ingredients_text = str(product_data.get("ingredients") or "")
    analysis = analyze_ingredients(ingredients_text)

    return {
        "ingredients_text": ingredients_text,
        "detected_concerns": analysis["detected_issues"],
        "ingredient_level_analysis": analysis["detected_issues"],
        "final_preliminary_status": analysis["final_preliminary_status"],
    }


def halal_decision_agent(
    product_data: dict[str, Any],
    ingredient_analysis: dict[str, Any],
    manufacturer_confirmation: dict[str, Any] | None = None,
    db_path: Path = DB_PATH,
) -> dict[str, str]:
    """Apply the final halal status decision logic."""
    if bool(product_data.get("official_certificate_available")):
        return _decision(
            STATUS_HALAL_CERTIFIED,
            "An official halal certificate is marked as available for this product.",
            "official certificate",
        )

    detected_concerns = ingredient_analysis.get("detected_concerns", [])
    if _has_status(detected_concerns, STATUS_NOT_HALAL):
        return _decision(
            FINAL_NOT_HALAL,
            "A clearly not-halal ingredient was detected in the ingredient list.",
            "fresh ingredient analysis",
        )

    reusable_confirmation = None
    if not product_data.get("recheck_required"):
        reusable_confirmation = find_reusable_manufacturer_confirmation(
            product_data=product_data,
            ingredients_text=str(ingredient_analysis.get("ingredients_text") or ""),
            detected_concerns=detected_concerns,
            db_path=db_path,
        )
    if reusable_confirmation and reusable_confirmation["analyzed_status"] == FINAL_NOT_HALAL:
        return _decision(
            FINAL_NOT_HALAL,
            "The manufacturer response indicates the ingredient source is not halal-suitable.",
            "stored manufacturer confirmation",
        )

    if _confirmation_is_acceptable(manufacturer_confirmation) or (
        reusable_confirmation
        and reusable_confirmation["analyzed_status"] == STATUS_MANUFACTURER_CONFIRMED
    ):
        return _decision(
            STATUS_MANUFACTURER_CONFIRMED,
            "The manufacturer confirmed that the unclear source is acceptable.",
            "stored manufacturer confirmation",
        )

    preliminary_status = str(ingredient_analysis.get("final_preliminary_status") or "")
    if preliminary_status == FINAL_UNKNOWN:
        return _decision(
            FINAL_UNKNOWN,
            "The ingredient list is missing or incomplete.",
            "fresh ingredient analysis",
        )

    if _has_status(detected_concerns, STATUS_DOUBTFUL):
        return _decision(
            FINAL_DOUBTFUL,
            "One or more ingredients need source confirmation from the manufacturer.",
            "fresh ingredient analysis",
        )

    if preliminary_status == FINAL_NO_CONCERN:
        return _decision(
            FINAL_NO_CONCERN,
            "No known doubtful or not-halal ingredient was detected by the local rules.",
            "fresh ingredient analysis",
        )

    return _decision(
        FINAL_UNKNOWN,
        "The product could not be classified with confidence.",
        "fresh ingredient analysis",
    )


def manufacturer_inquiry_agent(
    product_data: dict[str, Any],
    decision: dict[str, str],
    ingredient_analysis: dict[str, Any],
    db_path: Path = DB_PATH,
) -> dict[str, Any]:
    """Create or reuse a manufacturer inquiry when a product is doubtful."""
    if decision["status"] != FINAL_DOUBTFUL:
        return {
            "required": False,
            "status": "not_required",
            "message": "No manufacturer inquiry is required for this status.",
        }

    doubtful_issues = _doubtful_issues(ingredient_analysis)
    if not doubtful_issues:
        return {
            "required": False,
            "status": "not_required",
            "message": "No doubtful ingredient was found.",
        }

    product_id = _ensure_product_exists(product_data, db_path)
    reusable_confirmation = find_reusable_manufacturer_confirmation(
        product_data={**product_data, "id": product_id},
        ingredients_text=str(ingredient_analysis.get("ingredients_text") or ""),
        detected_concerns=doubtful_issues,
        db_path=db_path,
    )
    if reusable_confirmation:
        return {
            "required": False,
            "status": "stored_response_reused",
            "message": "A stored manufacturer response was reused for this ingredient list.",
            "requested_ingredients": _ingredient_names(doubtful_issues),
            "response": reusable_confirmation,
        }

    ingredient_term = _ingredient_list_label(doubtful_issues)
    existing_inquiry = _find_existing_inquiry(
        product_id,
        ingredient_term,
        str(ingredient_analysis.get("ingredients_text") or ""),
        db_path,
    )
    if existing_inquiry:
        existing_response = _find_response_for_inquiry(int(existing_inquiry["id"]), db_path)
        return {
            "required": True,
            "status": existing_inquiry["status"],
            "message": "A manufacturer inquiry already exists for this product.",
            "inquiry": existing_inquiry,
            "response": existing_response,
        }

    requested_ingredients = _ingredient_names(doubtful_issues)
    email_draft = _create_email_draft(product_data, doubtful_issues)
    inquiry_id = _insert_manufacturer_inquiry(
        product_id=product_id,
        ingredient_term=ingredient_term,
        requested_ingredients=requested_ingredients,
        manufacturer_email=str(product_data.get("manufacturer_email") or ""),
        email_subject=email_draft["subject"],
        email_body=email_draft["body"],
        db_path=db_path,
    )
    email_draft["body"] = _append_reference_to_email_body(email_draft["body"], inquiry_id)
    _update_inquiry_email_body(inquiry_id, email_draft["body"], db_path)

    return {
        "required": True,
        "status": "draft_created",
        "message": "A manufacturer inquiry draft was created.",
        "requested_ingredients": requested_ingredients,
        "inquiry": {
            "id": inquiry_id,
            "product_id": product_id,
            "ingredient_term": ingredient_term,
            "requested_ingredients": requested_ingredients,
            "manufacturer_email": product_data.get("manufacturer_email")
            or "manufacturer email required",
            "email_subject": email_draft["subject"],
            "email_body": email_draft["body"],
            "sender": email_draft.get("sender", ""),
            "reply_to": email_draft.get("reply_to", ""),
            "status": "draft",
        },
    }


def analyze_manufacturer_response(
    response_text: str,
    doubtful_ingredients: list[str] | None = None,
) -> dict[str, Any]:
    """Classify a pasted manufacturer response using simple transparent rules."""
    clean_response = response_text.strip()
    normalized = clean_response.lower()
    requested = [ingredient for ingredient in (doubtful_ingredients or []) if ingredient]

    if not clean_response or len(clean_response) < 20:
        return _response_analysis(
            FINAL_UNKNOWN,
            "The response is too short or missing key source information.",
            [],
            requested,
        )

    not_halal_terms = [
        "pork-derived",
        "pork derived",
        "derived from pork",
        "gelatin from pork",
        "gelatine from pork",
        "lard",
        "alcohol-derived",
        "alcohol derived",
        "animal-based",
        "animal based",
    ]
    suitable_terms = [
        "plant-based",
        "plant based",
        "vegan",
        "synthetic",
        "microbial",
        "vegetable source",
        "vegetable origin",
        "non-animal",
        "non animal",
        "not animal-derived",
        "non-alcohol",
        "non alcohol",
        "alcohol-free",
    ]
    unclear_terms = [
        "cannot confirm",
        "unable to confirm",
        "proprietary",
        "may contain",
        "varies",
        "depends",
        "not available",
    ]

    if any(term in normalized for term in not_halal_terms):
        return _response_analysis(
            FINAL_NOT_HALAL,
            "The response mentions an animal, pork, lard, or alcohol-derived source.",
            [],
            requested,
        )

    if any(term in normalized for term in suitable_terms):
        confirmed = _confirmed_ingredients_from_response(normalized, requested)
        unresolved = [ingredient for ingredient in requested if ingredient not in confirmed]
        if requested and unresolved:
            return _response_analysis(
                STATUS_STILL_DOUBTFUL,
                "Confirmed: "
                + ", ".join(confirmed or ["none"])
                + ". Still unresolved: "
                + ", ".join(unresolved)
                + ".",
                confirmed,
                unresolved,
            )
        return _response_analysis(
            STATUS_MANUFACTURER_CONFIRMED,
            (
                "The response confirms a plant-based, vegan, synthetic, microbial, "
                "non-animal, or non-alcohol source for all requested doubtful ingredients."
            ),
            confirmed or requested,
            [],
        )

    if any(term in normalized for term in unclear_terms):
        return _response_analysis(
            STATUS_STILL_DOUBTFUL,
            "The response is unclear and does not confirm an acceptable source.",
            [],
            requested,
        )

    return _response_analysis(
        FINAL_UNKNOWN,
        "The response does not contain enough source information to classify confidently.",
        [],
        requested,
    )


def find_reusable_manufacturer_confirmation(
    product_data: dict[str, Any],
    ingredients_text: str,
    detected_concerns: list[dict[str, Any]],
    db_path: Path = DB_PATH,
) -> dict[str, Any] | None:
    """Find a stored response for the same barcode or manual identity."""
    requested_terms = {
        _normalize_ingredient_key(str(issue.get("ingredient") or ""))
        for issue in detected_concerns
        if issue.get("status") == STATUS_DOUBTFUL
    }
    requested_terms.discard("")
    if not requested_terms:
        return None

    initialize_database(db_path)
    normalized_ingredients = _normalize_text(ingredients_text)
    product_id = product_data.get("id")
    barcode = str(product_data.get("barcode") or "").strip()
    manual_hash = str(product_data.get("manual_product_hash") or "").strip()
    if not barcode and not manual_hash:
        manual_hash = _manual_product_hash(
            str(product_data.get("name") or "Manual product"),
            str(product_data.get("brand") or ""),
            ingredients_text,
        )

    with closing(get_connection(db_path)) as connection:
        rows = connection.execute(
            """
            SELECT
                mr.*,
                mi.ingredient_term,
                mi.requested_ingredients_json,
                mi.product_id,
                p.id AS stored_product_id,
                p.barcode,
                p.manual_product_hash
            FROM manufacturer_responses mr
            JOIN manufacturer_inquiries mi ON mi.id = mr.inquiry_id
            JOIN products p ON p.id = mi.product_id
            WHERE mr.analyzed_status IN (?, ?)
              AND COALESCE(mr.recheck_required, 0) = 0
            ORDER BY COALESCE(mr.response_date, mr.created_at) DESC;
            """,
            (STATUS_MANUFACTURER_CONFIRMED, FINAL_NOT_HALAL),
        ).fetchall()

    for row in rows:
        row_barcode = str(row["barcode"] or "").strip()
        row_hash = str(row["manual_product_hash"] or "").strip()
        same_identity = (
            bool(product_id and int(row["stored_product_id"]) == int(product_id))
            or bool(barcode and row_barcode == barcode)
            or bool(not barcode and manual_hash and row_hash == manual_hash)
        )
        if not same_identity:
            continue

        response_ingredients_text = _normalize_text(str(row["ingredients_text"] or ""))
        if not response_ingredients_text or response_ingredients_text != normalized_ingredients:
            continue

        row_data = dict(row)
        if row["analyzed_status"] == FINAL_NOT_HALAL:
            return row_data

        confirmed_terms = _stored_ingredient_key_set(
            row_data.get("confirmed_ingredients_json"),
            row_data.get("doubtful_ingredient") or row_data.get("ingredient_term"),
        )
        unresolved_terms = _stored_ingredient_key_set(
            row_data.get("unresolved_ingredients_json"),
            None,
        )
        if requested_terms.issubset(confirmed_terms) and not requested_terms.intersection(
            unresolved_terms
        ):
            row_data["result_source"] = "stored manufacturer confirmation"
            row_data["recheck_required"] = False
            return row_data
    return None


def user_communication_agent(
    product_data: dict[str, Any],
    decision: dict[str, str],
    ingredient_analysis: dict[str, Any],
    language: str = "en",
) -> dict[str, Any]:
    """Generate a simple user-facing explanation in English or German."""
    status = decision["status"]
    product_name = product_data.get("name") or "this product"
    concerns = ingredient_analysis.get("detected_concerns", [])
    concern_names = ", ".join(issue["ingredient"] for issue in concerns) or "none"
    retrieved_sections = rag_engine.retrieve_knowledge(status, concerns, language)
    retrieved_context = rag_engine.build_context_text(retrieved_sections)
    local_explanation = _build_local_explanation(
        language=language,
        product_name=product_name,
        status=status,
        concern_names=concern_names,
        reason=decision["reason"],
        retrieved_context=retrieved_context,
    )
    explanation_mode = _select_explanation_mode()
    explanation = local_explanation
    fallback_used = False

    if explanation_mode == "OpenAI":
        llm_explanation = _generate_openai_explanation(
            product_name=product_name,
            status=status,
            concern_names=concern_names,
            reason=decision["reason"],
            retrieved_context=retrieved_context,
            language=language,
        )
        if llm_explanation:
            explanation = llm_explanation
        else:
            explanation_mode = "Local"
            fallback_used = True
    elif explanation_mode == "Gemini":
        llm_explanation = _generate_gemini_explanation(
            product_name=product_name,
            status=status,
            concern_names=concern_names,
            reason=decision["reason"],
            retrieved_context=retrieved_context,
            language=language,
        )
        if llm_explanation:
            explanation = llm_explanation
        else:
            explanation_mode = "Local"
            fallback_used = True

    explanation = _append_required_safety_text(explanation)
    mode_note = _explanation_mode_note(explanation_mode, fallback_used)
    explanation = f"{explanation}\n\n{mode_note}"

    return {
        "language": language,
        "status": status,
        "explanation": explanation,
        "retrieved_context": retrieved_context,
        "llm_provider": config.LLM_PROVIDER,
        "explanation_mode": explanation_mode,
        "fallback_used": fallback_used,
    }


def _build_local_explanation(
    language: str,
    product_name: str,
    status: str,
    concern_names: str,
    reason: str,
    retrieved_context: str,
) -> str:
    if language.lower().startswith("de"):
        return _german_explanation(
            product_name=product_name,
            status=status,
            concern_names=concern_names,
            reason=reason,
            retrieved_context=retrieved_context,
        )
    return _english_explanation(
        product_name=product_name,
        status=status,
        concern_names=concern_names,
        reason=reason,
        retrieved_context=retrieved_context,
    )


def _english_explanation(
    product_name: str,
    status: str,
    concern_names: str,
    reason: str,
    retrieved_context: str,
) -> str:
    context_part = f"\n\nRelevant knowledge:\n{retrieved_context}" if retrieved_context else ""
    return (
        f"Status for {product_name}: {status}.\n\n"
        f"What was found: {concern_names}.\n\n"
        f"Why: {reason}\n\n"
        "This result is decision-support guidance based on the ingredient rules and "
        "the local halal knowledge base."
        f"{context_part}"
    )


def _german_explanation(
    product_name: str,
    status: str,
    concern_names: str,
    reason: str,
    retrieved_context: str,
) -> str:
    context_part = f"\n\nRelevantes Wissen:\n{retrieved_context}" if retrieved_context else ""
    return (
        f"Status fuer {product_name}: {status}.\n\n"
        f"Gefundene Hinweise: {concern_names}.\n\n"
        f"Grund: {reason}\n\n"
        "Dieses Ergebnis ist eine Entscheidungshilfe auf Basis der Zutatenregeln "
        "und der lokalen Halal-Wissensbasis."
        f"{context_part}"
    )


def _select_explanation_mode() -> str:
    provider = config.LLM_PROVIDER.lower()
    if provider == "openai" and config.OPENAI_API_KEY:
        return "OpenAI"
    if provider == "gemini" and config.GEMINI_API_KEY:
        return "Gemini"
    return "Local"


def _explanation_mode_note(explanation_mode: str, fallback_used: bool) -> str:
    if fallback_used:
        return "Explanation mode: Local. The selected API call failed, so the app used the safe local RAG/rule explanation."
    if explanation_mode == "OpenAI":
        return "Explanation mode: OpenAI."
    if explanation_mode == "Gemini":
        return "Explanation mode: Gemini."
    return "Explanation mode: Local. No API key is required."


def _generate_openai_explanation(
    product_name: str,
    status: str,
    concern_names: str,
    reason: str,
    retrieved_context: str,
    language: str,
) -> str | None:
    try:
        from openai import OpenAI

        client = OpenAI(api_key=config.OPENAI_API_KEY)
        response = client.chat.completions.create(
            model=config.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": _llm_system_prompt(language)},
                {
                    "role": "user",
                    "content": _llm_user_prompt(
                        product_name,
                        status,
                        concern_names,
                        reason,
                        retrieved_context,
                    ),
                },
            ],
            temperature=0.2,
            max_tokens=450,
        )
        content = response.choices[0].message.content
        return _ensure_required_disclaimer(content)
    except Exception:
        return None


def _generate_gemini_explanation(
    product_name: str,
    status: str,
    concern_names: str,
    reason: str,
    retrieved_context: str,
    language: str,
) -> str | None:
    try:
        import requests

        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{config.GEMINI_MODEL}:generateContent"
        )
        response = requests.post(
            url,
            params={"key": config.GEMINI_API_KEY},
            json={
                "contents": [
                    {
                        "parts": [
                            {
                                "text": (
                                    _llm_system_prompt(language)
                                    + "\n\n"
                                    + _llm_user_prompt(
                                        product_name,
                                        status,
                                        concern_names,
                                        reason,
                                        retrieved_context,
                                    )
                                )
                            }
                        ]
                    }
                ],
                "generationConfig": {
                    "temperature": 0.2,
                    "maxOutputTokens": 450,
                },
            },
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        text = payload["candidates"][0]["content"]["parts"][0]["text"]
        return _ensure_required_disclaimer(text)
    except Exception:
        return None


def _llm_system_prompt(language: str) -> str:
    if language.lower().startswith("de"):
        return (
            "Du bist ein vorsichtiger HalalCheck-Erklaerassistent. Erklaere kurz, "
            "einfach und auf Deutsch. Sage niemals, dass ein Produkt halal "
            "zertifiziert ist, ausser der Status ist Halal Certified. Erwaehne, "
            "dass die App nur Entscheidungshilfe ist und keine offizielle "
            "Halal-Zertifizierungsstelle."
        )
    return (
        "You are a careful HalalCheck explanation assistant. Explain briefly and "
        "simply in English. Never say a product is halal certified unless the "
        "status is Halal Certified. Mention that the app is decision support and "
        "not an official halal certification authority."
    )


def _llm_user_prompt(
    product_name: str,
    status: str,
    concern_names: str,
    reason: str,
    retrieved_context: str,
) -> str:
    return (
        f"Product: {product_name}\n"
        f"Final status: {status}\n"
        f"Detected concerns: {concern_names}\n"
        f"Rule reason: {reason}\n"
        f"Knowledge base context:\n{retrieved_context}\n\n"
        "Explain the result for a normal user. Clearly state that Manufacturer "
        "Confirmed Suitable is not the same as Halal Certified."
    )


def _ensure_required_disclaimer(text: str | None) -> str | None:
    if not text:
        return None
    return _append_required_safety_text(text)


def _append_required_safety_text(text: str) -> str:
    """Append mandatory safety wording without relying on LLM phrasing."""
    explanation = text.strip()
    required_sentences = [
        REQUIRED_CERTIFICATION_LIMIT_PHRASE,
        OFFICIAL_CERTIFICATE_LIMIT_PHRASE,
        DECISION_SUPPORT_PHRASE,
    ]
    missing_sentences = [
        sentence for sentence in required_sentences if sentence not in explanation
    ]
    if not missing_sentences:
        return explanation
    safety_text = " ".join(missing_sentences)
    if not explanation:
        return safety_text
    return f"{explanation}\n\n{safety_text}"


def run_product_check_demo(db_path: Path = DB_PATH) -> dict[str, Any]:
    """Small demo workflow that can be run from the command line."""
    product = product_lookup_agent(
        barcode="DEMO-AGENT-001",
        product_name="Demo Biscuit",
        brand="Bootcamp Foods",
        ingredients="Wheat flour, sugar, E471, aroma",
        manufacturer_email="quality@example.com",
        db_path=db_path,
    )
    analysis = ingredient_analysis_agent(product)
    decision = halal_decision_agent(product, analysis, db_path=db_path)
    inquiry = manufacturer_inquiry_agent(product, decision, analysis, db_path=db_path)
    communication = user_communication_agent(product, decision, analysis)

    return {
        "product": product,
        "analysis": analysis,
        "decision": decision,
        "manufacturer_inquiry": inquiry,
        "communication": communication,
    }


def _find_product_by_barcode(barcode: str, db_path: Path) -> dict[str, Any] | None:
    initialize_database(db_path)
    with closing(get_connection(db_path)) as connection:
        row = connection.execute(
            "SELECT * FROM products WHERE barcode = ?;",
            (barcode,),
        ).fetchone()
    return _row_to_product(row) if row else None


def _lookup_product_by_barcode(barcode: str) -> dict[str, Any] | None:
    """Call product_lookup.py if a compatible helper exists."""
    for function_name in ("lookup_product_by_barcode", "lookup_product"):
        lookup_function = getattr(product_lookup, function_name, None)
        if callable(lookup_function):
            try:
                result = lookup_function(barcode)
            except Exception:
                return {
                    "lookup_status": "api_error",
                    "lookup_error": "Barcode lookup raised an unexpected error.",
                    "barcode": barcode,
                    "source": "open_food_facts",
                }
            return result if isinstance(result, dict) else None
    return None


def _merge_product_data(
    looked_up_product: dict[str, Any],
    barcode: str,
    product_name: str | None,
    brand: str | None,
    ingredients: str | None,
    manufacturer_email: str | None,
    official_certificate_available: bool,
    source: str,
    lookup_status: str,
) -> dict[str, Any]:
    clean_name = looked_up_product.get("name") or looked_up_product.get("product_name") or product_name or "Unknown product"
    clean_brand = looked_up_product.get("brand") or looked_up_product.get("brands") or brand or ""
    clean_ingredients = looked_up_product.get("ingredients") or looked_up_product.get("ingredients_text") or ingredients or ""
    manual_hash = _manual_product_hash(clean_name, clean_brand, clean_ingredients)
    return {
        "id": None,
        "barcode": barcode,
        "manual_product_hash": manual_hash,
        "product_identity_key": barcode or manual_hash,
        "name": clean_name,
        "brand": clean_brand,
        "ingredients": clean_ingredients,
        "fetched_ingredients": looked_up_product.get("fetched_ingredients")
        or clean_ingredients
        or "",
        "quantity": looked_up_product.get("quantity") or "",
        "manufacturer_email": manufacturer_email or looked_up_product.get("manufacturer_email") or "",
        "source": source,
        "official_certificate_available": official_certificate_available
        or bool(looked_up_product.get("official_certificate_available")),
        "lookup_status": lookup_status,
        "lookup_error": looked_up_product.get("lookup_error") or "",
        "api_url": looked_up_product.get("api_url") or "",
        "http_status_code": looked_up_product.get("http_status_code"),
        "response_preview": looked_up_product.get("response_preview") or "",
    }


def _decision(status: str, reason: str, result_source: str) -> dict[str, str]:
    return {"status": status, "reason": reason, "result_source": result_source}


def _has_status(issues: list[dict[str, str]], status: str) -> bool:
    return any(issue.get("status") == status for issue in issues)


def _confirmation_is_acceptable(confirmation: dict[str, Any] | None) -> bool:
    if not confirmation:
        return False
    if bool(confirmation.get("source_acceptable")):
        return True
    return str(confirmation.get("status") or "").lower() in {
        "manufacturer confirmed suitable",
        "acceptable",
        "confirmed suitable",
    }


def _doubtful_issues(ingredient_analysis: dict[str, Any]) -> list[dict[str, str]]:
    return [
        issue
        for issue in ingredient_analysis.get("detected_concerns", [])
        if issue.get("status") == STATUS_DOUBTFUL
    ]


def _ingredient_names(issues: list[dict[str, Any]]) -> list[str]:
    return [str(issue.get("ingredient") or "").strip() for issue in issues if issue.get("ingredient")]


def _ingredient_list_label(issues: list[dict[str, Any]]) -> str:
    return ", ".join(_ingredient_names(issues))


def _ensure_product_exists(product_data: dict[str, Any], db_path: Path) -> int:
    initialize_database(db_path)

    if product_data.get("id"):
        return int(product_data["id"])

    with closing(get_connection(db_path)) as connection:
        barcode = product_data.get("barcode")
        manual_hash = _product_manual_hash(product_data)
        product_data["manual_product_hash"] = manual_hash
        product_data["product_identity_key"] = barcode or manual_hash
        if barcode:
            existing = connection.execute(
                "SELECT id FROM products WHERE barcode = ?;",
                (barcode,),
            ).fetchone()
            if existing:
                product_data["id"] = int(existing["id"])
                return int(existing["id"])
        else:
            existing = connection.execute(
                "SELECT id FROM products WHERE manual_product_hash = ?;",
                (manual_hash,),
            ).fetchone()
            if existing:
                product_data["id"] = int(existing["id"])
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
                product_data.get("name") or "Manual product",
                product_data.get("brand") or "",
                product_data.get("ingredients") or "",
                manual_hash,
                product_data.get("manufacturer_email") or "",
                product_data.get("source") or "manual",
                int(bool(product_data.get("official_certificate_available"))),
            ),
        )
        connection.commit()

    product_id = int(cursor.lastrowid)
    product_data["id"] = product_id
    return product_id


def _find_existing_inquiry(
    product_id: int,
    ingredient_term: str,
    ingredients_text: str,
    db_path: Path,
) -> dict[str, Any] | None:
    normalized_ingredients = _normalize_text(ingredients_text)
    with closing(get_connection(db_path)) as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM manufacturer_inquiries
            WHERE product_id = ? AND ingredient_term = ?
            ORDER BY created_at DESC
            """,
            (product_id, ingredient_term),
        ).fetchall()
    for row in rows:
        if row["status"] != "response_received":
            return dict(row)
        response = _find_response_for_inquiry(int(row["id"]), db_path)
        if response and _normalize_text(str(response.get("ingredients_text") or "")) == normalized_ingredients:
            return dict(row)
    return None


def _find_response_for_inquiry(
    inquiry_id: int,
    db_path: Path,
) -> dict[str, Any] | None:
    with closing(get_connection(db_path)) as connection:
        row = connection.execute(
            """
            SELECT *
            FROM manufacturer_responses
            WHERE inquiry_id = ?
            ORDER BY created_at DESC
            LIMIT 1;
            """,
            (inquiry_id,),
        ).fetchone()
    return dict(row) if row else None


def _create_email_draft(
    product_data: dict[str, Any],
    doubtful_issues: list[dict[str, str]],
) -> dict[str, str]:
    return email_service.generate_manufacturer_email_draft(product_data, doubtful_issues)




def _append_reference_to_email_body(email_body: str, inquiry_id: int) -> str:
    if f"HC-{inquiry_id}" in email_body:
        return email_body
    return f"{email_body}\n\nReference: HC-{inquiry_id}"


def _update_inquiry_email_body(inquiry_id: int, email_body: str, db_path: Path) -> None:
    with closing(get_connection(db_path)) as connection:
        connection.execute(
            "UPDATE manufacturer_inquiries SET email_body = ? WHERE id = ?;",
            (email_body, inquiry_id),
        )
        connection.commit()

def _insert_manufacturer_inquiry(
    product_id: int,
    ingredient_term: str,
    requested_ingredients: list[str],
    manufacturer_email: str,
    email_subject: str,
    email_body: str,
    db_path: Path,
) -> int:
    with closing(get_connection(db_path)) as connection:
        cursor = connection.execute(
            """
            INSERT INTO manufacturer_inquiries (
                product_id,
                ingredient_term,
                requested_ingredients_json,
                manufacturer_email,
                email_subject,
                email_body,
                status
            )
            VALUES (?, ?, ?, ?, ?, ?, 'draft');
            """,
            (
                product_id,
                ingredient_term,
                json.dumps(requested_ingredients),
                manufacturer_email,
                email_subject,
                email_body,
            ),
        )
        connection.commit()
    return int(cursor.lastrowid)


def _ingredients_changed(old_ingredients: str | None, new_ingredients: str | None) -> bool:
    old_normalized = _normalize_text(old_ingredients or "")
    new_normalized = _normalize_text(new_ingredients or "")
    if not old_normalized or not new_normalized:
        return False
    return old_normalized != new_normalized


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _manual_product_hash(product_name: str, brand: str, ingredients: str) -> str:
    identity = "|".join(
        [
            _normalize_text(product_name),
            _normalize_text(brand),
            _normalize_text(ingredients),
        ]
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _product_manual_hash(product_data: dict[str, Any]) -> str:
    existing_hash = str(product_data.get("manual_product_hash") or "").strip()
    if existing_hash:
        return existing_hash
    return _manual_product_hash(
        str(product_data.get("name") or "Manual product"),
        str(product_data.get("brand") or ""),
        str(product_data.get("ingredients") or ""),
    )


def _normalize_ingredient_key(ingredient: str) -> str:
    normalized = _normalize_text(ingredient)
    if normalized in {"flavouring", "flavoring", "flavourings", "flavorings", "aroma", "aromen"}:
        return "aroma/flavouring"
    return normalized


def _ingredient_aliases(ingredient: str) -> set[str]:
    key = _normalize_ingredient_key(ingredient)
    if key == "aroma/flavouring":
        return {"aroma", "aromen", "flavouring", "flavourings", "flavoring", "flavorings"}
    return {key}


def _confirmed_ingredients_from_response(
    normalized_response: str,
    requested: list[str],
) -> list[str]:
    if not requested:
        return []
    global_confirmation_terms = (
        "all requested",
        "all listed",
        "all of the following",
        "the following ingredients",
        "both ingredients",
        "all ingredients",
    )
    if any(term in normalized_response for term in global_confirmation_terms):
        return requested.copy()
    if len(requested) == 1:
        return requested.copy()
    confirmed = []
    for ingredient in requested:
        if any(alias in normalized_response for alias in _ingredient_aliases(ingredient)):
            confirmed.append(ingredient)
    return confirmed


def _response_analysis(
    status: str,
    notes: str,
    confirmed: list[str],
    unresolved: list[str],
) -> dict[str, Any]:
    return {
        "analyzed_status": status,
        "analysis_notes": notes,
        "confirmed_ingredients": confirmed,
        "unresolved_ingredients": unresolved,
    }


def _stored_ingredient_key_set(
    json_value: Any,
    fallback: Any,
) -> set[str]:
    ingredients: list[str] = []
    if json_value:
        try:
            loaded = json.loads(str(json_value))
            if isinstance(loaded, list):
                ingredients.extend(str(item) for item in loaded)
        except json.JSONDecodeError:
            ingredients.append(str(json_value))
    if not ingredients and fallback:
        ingredients.extend(part.strip() for part in str(fallback).split(","))
    return {_normalize_ingredient_key(ingredient) for ingredient in ingredients if ingredient}


def _row_to_product(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "barcode": row["barcode"],
        "manual_product_hash": row["manual_product_hash"] or "",
        "product_identity_key": row["barcode"] or row["manual_product_hash"] or "",
        "name": row["name"],
        "brand": row["brand"] or "",
        "ingredients": row["ingredients"] or "",
        "fetched_ingredients": "",
        "quantity": "",
        "manufacturer_email": row["manufacturer_email"] or "",
        "source": row["source"],
        "official_certificate_available": bool(row["official_certificate_available"]),
        "lookup_status": "found_in_database",
        "lookup_error": "",
        "result_source": "local database",
        "recheck_required": False,
    }


if __name__ == "__main__":
    demo_result = run_product_check_demo()
    print(json.dumps(demo_result, indent=2))
