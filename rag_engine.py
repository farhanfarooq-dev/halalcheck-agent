"""Simple keyword-based RAG retrieval for the MVP.

This is deliberately small and beginner-friendly. It reads the markdown
knowledge base, splits it into sections, and returns the most relevant sections
for a product status and detected ingredients. ChromaDB/FAISS can be added
later without changing the Streamlit page.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
KNOWLEDGE_BASE_PATH = BASE_DIR / "data" / "halal_knowledge_base.md"


def retrieve_knowledge(
    status: str,
    detected_ingredients: list[dict[str, Any]] | None = None,
    language: str = "en",
    max_sections: int = 3,
) -> list[dict[str, str]]:
    """Return relevant knowledge-base sections for the current result."""
    sections = _load_sections()
    if not sections:
        return []

    keywords = _build_keywords(status, detected_ingredients or [], language)
    scored_sections: list[tuple[int, dict[str, str]]] = []

    for section in sections:
        searchable_text = f"{section['title']} {section['content']}".lower()
        score = sum(1 for keyword in keywords if keyword in searchable_text)
        if score > 0:
            scored_sections.append((score, section))

    scored_sections.sort(key=lambda item: item[0], reverse=True)
    return [section for _, section in scored_sections[:max_sections]]


def build_context_text(sections: list[dict[str, str]]) -> str:
    """Convert retrieved sections into short display text."""
    if not sections:
        return ""

    lines: list[str] = []
    for section in sections:
        lines.append(f"{section['title']}: {section['content']}")
    return "\n\n".join(lines)


def _load_sections() -> list[dict[str, str]]:
    if not KNOWLEDGE_BASE_PATH.exists():
        return []

    text = KNOWLEDGE_BASE_PATH.read_text(encoding="utf-8")
    sections: list[dict[str, str]] = []
    current_title = "Knowledge Base"
    current_lines: list[str] = []

    for line in text.splitlines():
        if line.startswith("## "):
            _append_section(sections, current_title, current_lines)
            current_title = line.replace("## ", "").strip()
            current_lines = []
        elif not line.startswith("# "):
            current_lines.append(line)

    _append_section(sections, current_title, current_lines)
    return sections


def _append_section(
    sections: list[dict[str, str]],
    title: str,
    lines: list[str],
) -> None:
    content = " ".join(line.strip() for line in lines if line.strip())
    if content:
        sections.append({"title": title, "content": content})


def _build_keywords(
    status: str,
    detected_ingredients: list[dict[str, Any]],
    language: str,
) -> set[str]:
    keywords = set(_words(status))
    keywords.update({"status", "halal", "certified", "manufacturer", "confirmation"})

    for issue in detected_ingredients:
        keywords.update(_words(str(issue.get("ingredient", ""))))
        keywords.update(_words(str(issue.get("matched_rule", ""))))
        keywords.update(_words(str(issue.get("status", ""))))

    normalized_status = status.lower()
    if "doubtful" in normalized_status:
        keywords.update({"doubtful", "verification", "source", "confirmation"})
    if "not halal" in normalized_status:
        keywords.update({"not", "halal", "detected"})
    if "unknown" in normalized_status:
        keywords.update({"unknown", "missing", "incomplete"})
    if "no concern" in normalized_status:
        keywords.update({"concern", "rules", "ingredient"})

    if language.lower().startswith("de"):
        keywords.update({"halal", "zertifizierung", "hersteller", "bestaetigung"})

    return {keyword for keyword in keywords if len(keyword) >= 2}


def _words(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z0-9]+", text.lower())
