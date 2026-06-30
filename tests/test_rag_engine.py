"""Tests for simple knowledge-base retrieval."""

from rag_engine import build_context_text, retrieve_knowledge


def test_retrieves_context_for_doubtful_e471() -> None:
    sections = retrieve_knowledge(
        "Doubtful / Needs Verification",
        [{"ingredient": "E471", "matched_rule": "E471 / Mono- and diglycerides"}],
    )
    context = build_context_text(sections)

    assert sections
    assert "E471" in context or "Doubtful" in context


def test_retrieves_context_for_unknown_status() -> None:
    sections = retrieve_knowledge("Unknown", [])
    context = build_context_text(sections)

    assert "Unknown" in context or "missing" in context.lower()
