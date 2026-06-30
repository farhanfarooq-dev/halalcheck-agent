"""Beginner-friendly halal ingredient and E-code rule checker.

This module is intentionally independent from Streamlit, FastAPI, and SQLite.
Later agents can import ``analyze_ingredients`` and reuse the same rule logic
from the web app, API, or tests.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


STATUS_ACCEPTABLE = "Acceptable"
STATUS_DOUBTFUL = "Doubtful / source required"
STATUS_NOT_HALAL = "Not Halal"
STATUS_UNKNOWN = "Unknown"

FINAL_NO_CONCERN = "No Concern Found"
FINAL_DOUBTFUL = "Doubtful / Needs Verification"
FINAL_NOT_HALAL = "Not Halal"
FINAL_UNKNOWN = "Unknown"


@dataclass(frozen=True)
class HalalRule:
    """One ingredient rule used by the local analyzer."""

    name: str
    patterns: tuple[str, ...]
    status: str
    reason: str
    recommended_action: str


RULES: tuple[HalalRule, ...] = (
    HalalRule(
        name="E120 / Carmine / Karmin",
        patterns=(r"\bE[\s-]?120\b", r"\bcarmine\b", r"\bkarmin\b"),
        status=STATUS_NOT_HALAL,
        reason="E120/carmine is commonly derived from insects.",
        recommended_action="Avoid this product unless a qualified halal authority says otherwise.",
    ),
    HalalRule(
        name="Pork / Schwein",
        patterns=(r"\bpork\b", r"\bschwein\w*\b"),
        status=STATUS_NOT_HALAL,
        reason="Pork-derived ingredients are not halal.",
        recommended_action="Do not use this product.",
    ),
    HalalRule(
        name="Lard / Schmalz",
        patterns=(r"\blard\b", r"\bschmalz\b", r"\bschweineschmalz\b"),
        status=STATUS_NOT_HALAL,
        reason="Lard is pig fat.",
        recommended_action="Do not use this product.",
    ),
    HalalRule(
        name="Alcohol / Alkohol",
        patterns=(r"\balcohol\b", r"\balkohol\b"),
        status=STATUS_DOUBTFUL,
        reason="Alcohol source and usage need verification.",
        recommended_action="Ask the manufacturer whether alcohol is present in the final product and how it is used.",
    ),
    HalalRule(
        name="E441 / Gelatin / Gelatine",
        patterns=(r"\bE[\s-]?441\b", r"\bgelatin\b", r"\bgelatine\b"),
        status=STATUS_DOUBTFUL,
        reason="Gelatin can come from animal sources.",
        recommended_action="Ask the manufacturer whether the gelatin is fish, bovine halal-certified, or another acceptable source.",
    ),
    HalalRule(
        name="E471 / Mono- and diglycerides",
        patterns=(
            r"\bE[\s-]?471\b",
            r"\bmono[\s-]*and[\s-]*diglycerides\b",
            r"\bmono[\s-]*und[\s-]*diglyceride\b",
            r"\bmono[\s-]*und[\s-]*diglyceriden\b",
        ),
        status=STATUS_DOUBTFUL,
        reason="E471 can be plant-based or animal-based.",
        recommended_action="Ask the manufacturer whether E471 is plant-based, microbial, synthetic, or animal-derived.",
    ),
    HalalRule(
        name="E472 / Emulsifier",
        patterns=(r"\bE[\s-]?472[a-f]?\b", r"\bemulsifier\w*\b", r"\bemulgator\w*\b"),
        status=STATUS_DOUBTFUL,
        reason="Some emulsifiers need source confirmation.",
        recommended_action="Ask the manufacturer for the source of the emulsifier.",
    ),
    HalalRule(
        name="Glycerine / Glycerol / Glycerin",
        patterns=(r"\bglycerine\b", r"\bglycerol\b", r"\bglycerin\b"),
        status=STATUS_DOUBTFUL,
        reason="Glycerine/glycerol can be plant-based, synthetic, or animal-derived.",
        recommended_action="Ask the manufacturer whether it is plant-based, microbial, synthetic, or animal-derived.",
    ),
    HalalRule(
        name="Enzymes / Enzyme",
        patterns=(r"\benzymes\b", r"\benzyme\b", r"\benzymen\b"),
        status=STATUS_DOUBTFUL,
        reason="Enzymes can come from animal, microbial, or plant sources.",
        recommended_action="Ask the manufacturer for the enzyme source.",
    ),
    HalalRule(
        name="Rennet / Lab",
        patterns=(r"\brennet\b", r"\blab\b"),
        status=STATUS_DOUBTFUL,
        reason="Rennet may be animal, microbial, or vegetarian.",
        recommended_action="Ask whether the rennet is microbial, vegetarian, or halal-certified animal rennet.",
    ),
    HalalRule(
        name="Whey / Molke",
        patterns=(r"\bwhey\b", r"\bmolke\b"),
        status=STATUS_ACCEPTABLE,
        reason="Whey is generally acceptable when no non-halal processing concern is found.",
        recommended_action="No action needed unless other doubtful ingredients are present.",
    ),
    HalalRule(
        name="Flavouring / Aroma",
        patterns=(r"\bflavou?rings?\b", r"\baroma\b", r"\baromen\b"),
        status=STATUS_DOUBTFUL,
        reason="Flavouring/aroma can include carrier solvents or animal-derived components.",
        recommended_action="Ask the manufacturer whether flavouring contains alcohol or animal-derived ingredients.",
    ),
    HalalRule(
        name="Animal fat / Tierisches Fett",
        patterns=(r"\banimal fat\b", r"\btierisches fett\b", r"\btierische fette\b"),
        status=STATUS_DOUBTFUL,
        reason="Animal fat needs species and slaughter confirmation.",
        recommended_action="Ask the manufacturer which animal source is used and whether it is halal-certified.",
    ),
)


def analyze_ingredients(ingredients_text: str) -> dict[str, object]:
    """Analyze ingredients and return detected issues plus preliminary status.

    Return shape:
        {
            "detected_issues": [
                {
                    "ingredient": "E471",
                    "matched_rule": "E471 / Mono- and diglycerides",
                    "status": "Doubtful / source required",
                    "reason": "...",
                    "recommended_action": "...",
                }
            ],
            "final_preliminary_status": "Doubtful / Needs Verification",
        }
    """
    text = ingredients_text.strip()
    if not text:
        return {
            "detected_issues": [],
            "final_preliminary_status": FINAL_UNKNOWN,
        }

    detected_issues = _find_matching_rules(text)
    final_status = _decide_preliminary_status(detected_issues)

    return {
        "detected_issues": detected_issues,
        "final_preliminary_status": final_status,
    }


def _find_matching_rules(ingredients_text: str) -> list[dict[str, str]]:
    """Return one structured result for each matched rule."""
    matches: list[dict[str, str]] = []

    for rule in RULES:
        matched_text = _first_match(ingredients_text, rule.patterns)
        if matched_text is None:
            continue

        matches.append(
            {
                "ingredient": matched_text,
                "matched_rule": rule.name,
                "status": rule.status,
                "reason": rule.reason,
                "recommended_action": rule.recommended_action,
            }
        )

    return matches


def _first_match(text: str, patterns: tuple[str, ...]) -> str | None:
    """Find the first matched ingredient phrase for a rule."""
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(0)
    return None


def _decide_preliminary_status(detected_issues: list[dict[str, str]]) -> str:
    """Apply the first-pass halal decision logic."""
    if not detected_issues:
        return FINAL_NO_CONCERN

    statuses = {issue["status"] for issue in detected_issues}
    if STATUS_NOT_HALAL in statuses:
        return FINAL_NOT_HALAL
    if STATUS_DOUBTFUL in statuses:
        return FINAL_DOUBTFUL
    if statuses == {STATUS_ACCEPTABLE}:
        return FINAL_NO_CONCERN
    return FINAL_UNKNOWN
