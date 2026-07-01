"""Small tests for the modular agent layer."""

from pathlib import Path
from contextlib import closing

import product_lookup
from database import get_connection, initialize_database
from agents import (
    FINAL_DOUBTFUL,
    FINAL_NOT_HALAL,
    FINAL_UNKNOWN,
    REQUIRED_CERTIFICATION_LIMIT_PHRASE,
    STATUS_HALAL_CERTIFIED,
    STATUS_MANUFACTURER_CONFIRMED,
    STATUS_STILL_DOUBTFUL,
    analyze_manufacturer_response,
    halal_decision_agent,
    ingredient_analysis_agent,
    manufacturer_inquiry_agent,
    product_lookup_agent,
    user_communication_agent,
    _product_manual_hash,
)


def _insert_product_confirmation(
    db_path: Path,
    barcode: str | None = "VERIFY-001",
    product_name: str = "Verified Product",
    brand: str = "Brand",
    ingredients: str = "Sugar, E471",
    requested_ingredients: list[str] | None = None,
    analyzed_status: str = STATUS_MANUFACTURER_CONFIRMED,
    confirmed_ingredients: list[str] | None = None,
    unresolved_ingredients: list[str] | None = None,
) -> int:
    initialize_database(db_path)
    requested_ingredients = requested_ingredients or ["E471"]
    confirmed_ingredients = confirmed_ingredients or (
        requested_ingredients if analyzed_status == STATUS_MANUFACTURER_CONFIRMED else []
    )
    unresolved_ingredients = unresolved_ingredients or []
    ingredient_term = ", ".join(requested_ingredients)
    manual_hash = _product_manual_hash(
        {"name": product_name, "brand": brand, "ingredients": ingredients}
    )
    with closing(get_connection(db_path)) as connection:
        cursor = connection.execute(
            """
            INSERT INTO products (
                barcode, name, brand, ingredients, manual_product_hash, manufacturer_email, source
            )
            VALUES (?, ?, ?, ?, ?, 'maker@example.com', 'manual');
            """,
            (barcode, product_name, brand, ingredients, manual_hash),
        )
        product_id = int(cursor.lastrowid)
        inquiry = connection.execute(
            """
            INSERT INTO manufacturer_inquiries (
                product_id, ingredient_term, requested_ingredients_json, manufacturer_email,
                email_subject, email_body, status
            )
            VALUES (?, ?, ?, 'maker@example.com', 'Question about ingredient source', 'body', 'response_received');
            """,
            (product_id, ingredient_term, __import__("json").dumps(requested_ingredients)),
        )
        connection.execute(
            """
            INSERT INTO manufacturer_responses (
                inquiry_id,
                response_text,
                analyzed_status,
                analysis_notes,
                ingredients_text,
                doubtful_ingredient,
                confirmed_ingredients_json,
                unresolved_ingredients_json,
                verification_source,
                response_date,
                recheck_required
            )
            VALUES (?, 'All requested ingredients are plant-based.', ?, 'Stored test response.', ?, ?, ?, ?,
                    'manufacturer_response', CURRENT_TIMESTAMP, 0);
            """,
            (
                int(inquiry.lastrowid),
                analyzed_status,
                ingredients,
                ingredient_term,
                __import__("json").dumps(confirmed_ingredients),
                __import__("json").dumps(unresolved_ingredients),
            ),
        )
        connection.commit()
    return product_id


def test_decision_prefers_official_certificate() -> None:
    product = {
        "official_certificate_available": True,
        "ingredients": "Sugar, E471",
    }
    analysis = ingredient_analysis_agent(product)
    decision = halal_decision_agent(product, analysis)

    assert decision["status"] == STATUS_HALAL_CERTIFIED


def test_manufacturer_confirmation_is_not_certification() -> None:
    product = {
        "official_certificate_available": False,
        "ingredients": "Sugar, E471",
    }
    analysis = ingredient_analysis_agent(product)
    decision = halal_decision_agent(
        product,
        analysis,
        manufacturer_confirmation={"source_acceptable": True},
    )

    assert decision["status"] == STATUS_MANUFACTURER_CONFIRMED


def test_inquiry_draft_is_created_for_doubtful_product(tmp_path: Path) -> None:
    db_path = tmp_path / "halalcheck-test.db"
    product = product_lookup_agent(
        barcode="TEST-001",
        product_name="Test Biscuit",
        ingredients="Wheat flour, E471",
        manufacturer_email="quality@example.com",
        db_path=db_path,
    )
    analysis = ingredient_analysis_agent(product)
    decision = halal_decision_agent(product, analysis, db_path=db_path)
    inquiry = manufacturer_inquiry_agent(product, decision, analysis, db_path=db_path)

    assert decision["status"] == FINAL_DOUBTFUL
    assert inquiry["status"] == "draft_created"
    assert "E471" in inquiry["inquiry"]["email_body"]


def test_user_explanation_mentions_confirmation_limit(monkeypatch) -> None:
    import agents

    monkeypatch.setattr(agents.config, "LLM_PROVIDER", "local")
    monkeypatch.setattr(agents.config, "OPENAI_API_KEY", "")
    monkeypatch.setattr(agents.config, "GEMINI_API_KEY", "")

    product = {"name": "Test Product", "ingredients": "Sugar"}
    analysis = ingredient_analysis_agent(product)
    decision = halal_decision_agent(product, analysis)
    message = user_communication_agent(product, decision, analysis)

    assert REQUIRED_CERTIFICATION_LIMIT_PHRASE in message["explanation"]
    assert "Explanation mode: Local" in message["explanation"]
    assert message["explanation_mode"] == "Local"


def test_found_api_product_without_ingredients_is_unknown() -> None:
    product = {
        "name": "API Product Without Ingredients",
        "lookup_status": "api_found",
        "ingredients": "",
        "fetched_ingredients": "",
        "official_certificate_available": False,
    }
    analysis = ingredient_analysis_agent(product)
    decision = halal_decision_agent(product, analysis)

    assert decision["status"] == FINAL_UNKNOWN


def test_manual_doubtful_and_not_halal_examples() -> None:
    doubtful_product = {"ingredients": "Sugar, E471, aroma"}
    doubtful_analysis = ingredient_analysis_agent(doubtful_product)
    doubtful_decision = halal_decision_agent(doubtful_product, doubtful_analysis)
    assert doubtful_decision["status"] == FINAL_DOUBTFUL

    not_halal_product = {"ingredients": "Noodles, pork extract, salt"}
    not_halal_analysis = ingredient_analysis_agent(not_halal_product)
    not_halal_decision = halal_decision_agent(not_halal_product, not_halal_analysis)
    assert not_halal_decision["status"] == FINAL_NOT_HALAL


def test_explanation_generated_for_required_statuses() -> None:
    examples = [
        {"name": "Not Halal Demo", "ingredients": "pork extract"},
        {"name": "Doubtful Demo", "ingredients": "Sugar, E471"},
        {"name": "Unknown Demo", "ingredients": ""},
        {"name": "No Concern Demo", "ingredients": "Water, oats, salt"},
        {
            "name": "Halal Certified Demo",
            "ingredients": "Sugar, E471",
            "official_certificate_available": True,
        },
    ]

    for product in examples:
        analysis = ingredient_analysis_agent(product)
        decision = halal_decision_agent(product, analysis)
        message = user_communication_agent(product, decision, analysis)

        assert message["explanation"]
        assert decision["status"] in message["explanation"]
        assert REQUIRED_CERTIFICATION_LIMIT_PHRASE in message["explanation"]
        assert "retrieved_context" in message


def test_openai_mode_uses_api_when_configured(monkeypatch) -> None:
    import agents

    monkeypatch.setattr(agents.config, "LLM_PROVIDER", "openai")
    monkeypatch.setattr(agents.config, "OPENAI_API_KEY", "fake-key")
    monkeypatch.setattr(
        agents,
        "_generate_openai_explanation",
        lambda **kwargs: "OpenAI explanation. This app is decision support and not an official halal certification authority.",
    )

    product = {"name": "OpenAI Demo", "ingredients": "Sugar, E471"}
    analysis = ingredient_analysis_agent(product)
    decision = halal_decision_agent(product, analysis)
    message = user_communication_agent(product, decision, analysis)

    assert message["explanation_mode"] == "OpenAI"
    assert "OpenAI explanation" in message["explanation"]
    assert REQUIRED_CERTIFICATION_LIMIT_PHRASE in message["explanation"]


def test_gemini_failure_falls_back_to_local(monkeypatch) -> None:
    import agents

    monkeypatch.setattr(agents.config, "LLM_PROVIDER", "gemini")
    monkeypatch.setattr(agents.config, "GEMINI_API_KEY", "fake-key")
    monkeypatch.setattr(agents, "_generate_gemini_explanation", lambda **kwargs: None)

    product = {"name": "Gemini Demo", "ingredients": "Sugar, E471"}
    analysis = ingredient_analysis_agent(product)
    decision = halal_decision_agent(product, analysis)
    message = user_communication_agent(product, decision, analysis)

    assert message["explanation_mode"] == "Local"
    assert message["fallback_used"] is True
    assert "safe local RAG/rule explanation" in message["explanation"]


def test_analyze_plant_based_response() -> None:
    result = analyze_manufacturer_response(
        "The emulsifier E471 used in this product is plant-based."
    )

    assert result["analyzed_status"] == STATUS_MANUFACTURER_CONFIRMED


def test_analyze_animal_based_response() -> None:
    result = analyze_manufacturer_response(
        "The gelatin is animal-based and derived from pork."
    )

    assert result["analyzed_status"] == FINAL_NOT_HALAL


def test_analyze_unclear_response() -> None:
    result = analyze_manufacturer_response(
        "Unfortunately, this information is proprietary and may vary by supplier."
    )

    assert result["analyzed_status"] == STATUS_STILL_DOUBTFUL


def test_duplicate_inquiry_prevention(tmp_path: Path) -> None:
    db_path = tmp_path / "duplicate-test.db"
    product = product_lookup_agent(
        barcode="DUP-001",
        product_name="Duplicate Demo",
        ingredients="Sugar, E471",
        manufacturer_email="quality@example.com",
        db_path=db_path,
    )
    analysis = ingredient_analysis_agent(product)
    decision = halal_decision_agent(product, analysis, db_path=db_path)

    first = manufacturer_inquiry_agent(product, decision, analysis, db_path=db_path)
    second = manufacturer_inquiry_agent(product, decision, analysis, db_path=db_path)

    assert first["status"] == "draft_created"
    assert second["status"] == "draft"
    assert second["inquiry"]["id"] == first["inquiry"]["id"]


def test_same_barcode_reuses_stored_confirmation(tmp_path: Path) -> None:
    db_path = tmp_path / "stored-confirmation.db"
    _insert_product_confirmation(db_path)

    product = product_lookup_agent(barcode="VERIFY-001", db_path=db_path)
    analysis = ingredient_analysis_agent(product)
    decision = halal_decision_agent(product, analysis, db_path=db_path)
    inquiry = manufacturer_inquiry_agent(product, decision, analysis, db_path=db_path)

    assert product["lookup_status"] == "found_in_database"
    assert decision["status"] == STATUS_MANUFACTURER_CONFIRMED
    assert decision["result_source"] == "stored manufacturer confirmation"
    assert inquiry["status"] == "not_required"


def test_same_barcode_changed_ingredients_requires_recheck(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "changed-ingredients.db"
    _insert_product_confirmation(db_path, ingredients="Sugar, E471")

    def fake_lookup(barcode: str):
        return {
            "lookup_status": "api_found",
            "lookup_error": "",
            "barcode": barcode,
            "name": "Verified Product",
            "brand": "Brand",
            "ingredients": "Sugar, E471, aroma",
            "fetched_ingredients": "Sugar, E471, aroma",
            "quantity": "100 g",
            "source": "open_food_facts",
        }

    monkeypatch.setattr(product_lookup, "lookup_product_by_barcode", fake_lookup)

    product = product_lookup_agent(barcode="VERIFY-001", db_path=db_path)
    analysis = ingredient_analysis_agent(product)
    decision = halal_decision_agent(product, analysis, db_path=db_path)

    assert product["recheck_required"] is True
    assert decision["status"] == FINAL_DOUBTFUL
    assert decision["result_source"] == "fresh ingredient analysis"


def test_official_certificate_takes_priority_over_confirmation(tmp_path: Path) -> None:
    db_path = tmp_path / "official-priority.db"
    product_id = _insert_product_confirmation(db_path)
    product = {
        "id": product_id,
        "ingredients": "Sugar, E471",
        "official_certificate_available": True,
    }
    analysis = ingredient_analysis_agent(product)
    decision = halal_decision_agent(product, analysis, db_path=db_path)

    assert decision["status"] == STATUS_HALAL_CERTIFIED
    assert decision["result_source"] == "official certificate"


def test_manufacturer_confirmed_suitable_is_not_halal_certified(tmp_path: Path) -> None:
    db_path = tmp_path / "not-certified.db"
    product_id = _insert_product_confirmation(db_path)
    product = {
        "id": product_id,
        "name": "Verified Product",
        "ingredients": "Sugar, E471",
        "official_certificate_available": False,
    }
    analysis = ingredient_analysis_agent(product)
    decision = halal_decision_agent(product, analysis, db_path=db_path)
    message = user_communication_agent(product, decision, analysis)

    assert decision["status"] == STATUS_MANUFACTURER_CONFIRMED
    assert decision["status"] != STATUS_HALAL_CERTIFIED
    assert REQUIRED_CERTIFICATION_LIMIT_PHRASE in message["explanation"]


def test_manual_product_reuses_stored_confirmation_by_identity(tmp_path: Path) -> None:
    db_path = tmp_path / "manual-reuse.db"
    _insert_product_confirmation(
        db_path,
        barcode=None,
        product_name="Manual Cookie",
        brand="Small Brand",
        ingredients="Sugar, E471",
    )

    product = product_lookup_agent(
        product_name="Manual Cookie",
        brand="Small Brand",
        ingredients="Sugar, E471",
        manufacturer_email="maker@example.com",
        db_path=db_path,
    )
    analysis = ingredient_analysis_agent(product)
    decision = halal_decision_agent(product, analysis, db_path=db_path)
    inquiry = manufacturer_inquiry_agent(product, decision, analysis, db_path=db_path)

    assert decision["status"] == STATUS_MANUFACTURER_CONFIRMED
    assert decision["result_source"] == "stored manufacturer confirmation"
    assert inquiry["status"] == "not_required"


def test_inquiry_draft_includes_multiple_doubtful_ingredients(tmp_path: Path) -> None:
    db_path = tmp_path / "multi-inquiry.db"
    product = product_lookup_agent(
        product_name="Aroma Biscuit",
        brand="Brand",
        ingredients="Sugar, E471, aroma",
        manufacturer_email="quality@example.com",
        db_path=db_path,
    )
    analysis = ingredient_analysis_agent(product)
    decision = halal_decision_agent(product, analysis, db_path=db_path)
    inquiry = manufacturer_inquiry_agent(product, decision, analysis, db_path=db_path)

    assert inquiry["status"] == "draft_created"
    assert inquiry["requested_ingredients"] == ["E471", "aroma"]
    assert "- E471" in inquiry["inquiry"]["email_body"]
    assert "- aroma" in inquiry["inquiry"]["email_body"]
    assert "following ingredients" in inquiry["inquiry"]["email_body"]


def test_admin_response_confirming_all_doubtful_ingredients_is_reused(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "all-confirmed.db"
    _insert_product_confirmation(
        db_path,
        barcode=None,
        product_name="Multi Cookie",
        brand="Brand",
        ingredients="Sugar, E471, aroma",
        requested_ingredients=["E471", "aroma"],
        confirmed_ingredients=["E471", "aroma"],
    )

    product = product_lookup_agent(
        product_name="Multi Cookie",
        brand="Brand",
        ingredients="Sugar, E471, aroma",
        db_path=db_path,
    )
    analysis = ingredient_analysis_agent(product)
    decision = halal_decision_agent(product, analysis, db_path=db_path)

    assert decision["status"] == STATUS_MANUFACTURER_CONFIRMED
    assert decision["result_source"] == "stored manufacturer confirmation"


def test_admin_response_confirming_one_of_multiple_ingredients_stays_doubtful(
    tmp_path: Path,
) -> None:
    response = analyze_manufacturer_response(
        "The E471 used in this product is plant-based.",
        ["E471", "aroma"],
    )
    assert response["analyzed_status"] == STATUS_STILL_DOUBTFUL
    assert response["confirmed_ingredients"] == ["E471"]
    assert response["unresolved_ingredients"] == ["aroma"]

    db_path = tmp_path / "partial-confirmed.db"
    _insert_product_confirmation(
        db_path,
        barcode=None,
        product_name="Partial Cookie",
        brand="Brand",
        ingredients="Sugar, E471, aroma",
        requested_ingredients=["E471", "aroma"],
        analyzed_status=STATUS_STILL_DOUBTFUL,
        confirmed_ingredients=["E471"],
        unresolved_ingredients=["aroma"],
    )
    product = product_lookup_agent(
        product_name="Partial Cookie",
        brand="Brand",
        ingredients="Sugar, E471, aroma",
        db_path=db_path,
    )
    analysis = ingredient_analysis_agent(product)
    decision = halal_decision_agent(product, analysis, db_path=db_path)

    assert decision["status"] == FINAL_DOUBTFUL
    assert decision["result_source"] == "fresh ingredient analysis"


def test_duplicate_inquiry_not_created_after_stored_confirmation_exists(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "no-duplicate-after-confirmation.db"
    _insert_product_confirmation(
        db_path,
        barcode=None,
        product_name="Reuse Cookie",
        brand="Brand",
        ingredients="Sugar, E471, aroma",
        requested_ingredients=["E471", "aroma"],
        confirmed_ingredients=["E471", "aroma"],
    )

    product = product_lookup_agent(
        product_name="Reuse Cookie",
        brand="Brand",
        ingredients="Sugar, E471, aroma",
        manufacturer_email="maker@example.com",
        db_path=db_path,
    )
    analysis = ingredient_analysis_agent(product)
    decision = halal_decision_agent(product, analysis, db_path=db_path)
    inquiry = manufacturer_inquiry_agent(product, decision, analysis, db_path=db_path)

    with closing(get_connection(db_path)) as connection:
        inquiry_count = connection.execute(
            "SELECT COUNT(*) FROM manufacturer_inquiries;"
        ).fetchone()[0]

    assert decision["status"] == STATUS_MANUFACTURER_CONFIRMED
    assert inquiry["status"] == "not_required"
    assert inquiry_count == 1
