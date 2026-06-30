"""Tests for the halal ingredient rule checker."""

from halal_rules import (
    FINAL_DOUBTFUL,
    FINAL_NO_CONCERN,
    FINAL_NOT_HALAL,
    FINAL_UNKNOWN,
    STATUS_ACCEPTABLE,
    STATUS_DOUBTFUL,
    STATUS_NOT_HALAL,
    analyze_ingredients,
)


def test_empty_ingredients_are_unknown() -> None:
    result = analyze_ingredients("")

    assert result["detected_issues"] == []
    assert result["final_preliminary_status"] == FINAL_UNKNOWN


def test_detects_not_halal_e120() -> None:
    result = analyze_ingredients("Sugar, glucose syrup, E120, flavouring")

    assert result["final_preliminary_status"] == FINAL_NOT_HALAL
    assert result["detected_issues"][0]["status"] == STATUS_NOT_HALAL


def test_detects_doubtful_e471() -> None:
    result = analyze_ingredients("Wheat flour, sugar, E471, aroma")

    assert result["final_preliminary_status"] == FINAL_DOUBTFUL
    assert any(
        issue["status"] == STATUS_DOUBTFUL
        and issue["matched_rule"] == "E471 / Mono- and diglycerides"
        for issue in result["detected_issues"]
    )


def test_detects_german_terms() -> None:
    result = analyze_ingredients("Zucker, Gelatine, Aroma, Molke")

    assert result["final_preliminary_status"] == FINAL_DOUBTFUL
    assert any(issue["ingredient"].lower() == "gelatine" for issue in result["detected_issues"])
    assert any(issue["ingredient"].lower() == "molke" for issue in result["detected_issues"])


def test_acceptable_only_returns_no_concern() -> None:
    result = analyze_ingredients("Milk, whey, salt")

    assert result["final_preliminary_status"] == FINAL_NO_CONCERN
    assert result["detected_issues"][0]["status"] == STATUS_ACCEPTABLE
