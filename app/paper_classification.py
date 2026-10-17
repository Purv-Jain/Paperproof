"""Deterministic research-paper classification.

This is a warning system, not a truth detector. A real paper can use an
unusual structure, and nothing here may reject a document just because one
conventional section is absent. Everything is decided from explicit signals
recorded in the report, so the user can see why a paper was flagged and can
override the decision.
"""

from __future__ import annotations

import re
from typing import Any

from app.image_extraction import CAPTION_PATTERN, ResearchClassification

# Conventional sections, grouped so that a single missing heading never
# decides the outcome on its own.
STRUCTURAL_SIGNALS: dict[str, tuple[str, ...]] = {
    "abstract or summary": ("abstract", "summary", "synopsis"),
    "introduction or background": ("introduction", "background"),
    "methods or study design": (
        "methods",
        "method",
        "methodology",
        "study design",
        "materials and methods",
        "procedure",
        "data collection",
        "experimental design",
    ),
    "results or findings": (
        "results",
        "findings",
        "outcomes",
        "analysis",
        "evaluation",
    ),
    "discussion": ("discussion", "interpretation", "implications"),
    "conclusion or limitations": (
        "conclusion",
        "conclusions",
        "limitations",
        "future work",
    ),
}

BIBLIOGRAPHY_HEADINGS = ("references", "bibliography", "works cited", "literature cited")

# A citation pattern that is not an author-year citation.
AUTHOR_YEAR = re.compile(
    r"(?:\((?:[^()]{0,120})\b(?:19|20)\d{2}[a-z]?\b[^()]{0,120}\)"
    r"|\b[A-Z][A-Za-z’'\-]+\s*\(\s*(?:19|20)\d{2}[a-z]?\s*\))"
)
NUMERIC = re.compile(r"\[\s*\d{1,3}(?:\s*(?:,|;|-|–|—)\s*\d{1,3})*\s*\]")

RESEARCH_TERMS = frozenset(
    {
        "abstract",
        "analysis",
        "analyze",
        "assess",
        "baseline",
        "cohort",
        "control",
        "correlate",
        "data",
        "dataset",
        "experiment",
        "experimental",
        "finding",
        "findings",
        "group",
        "hypothesis",
        "intervention",
        "measure",
        "measured",
        "method",
        "methods",
        "model",
        "observation",
        "observations",
        "participant",
        "participants",
        "population",
        "procedure",
        "randomly",
        "regression",
        "respondent",
        "respondents",
        "result",
        "results",
        "sample",
        "significant",
        "statistical",
        "study",
        "survey",
        "trial",
        "variable",
    }
)

AFFILIATION_TERMS = (
    "university",
    "department",
    "institute",
    "laboratory",
    "college",
    "school of",
    "faculty",
    "academy",
    "hospital",
    "clinic",
    "research center",
    "research centre",
)


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _matched_groups(sections: list[str]) -> tuple[list[str], list[str]]:
    """Return (present group labels, missing group labels)."""
    present: list[str] = []
    missing: list[str] = []
    section_tokens = [_tokens(section) for section in sections]
    for label, aliases in STRUCTURAL_SIGNALS.items():
        found = False
        for alias in aliases:
            alias_tokens = _tokens(alias)
            if any(alias_tokens <= tokens for tokens in section_tokens):
                found = True
                break
        (present if found else missing).append(label)
    return present, missing


def _bibliography_found(sections: list[str], detected: bool) -> bool:
    if detected:
        return True
    tokens = set().union(*(_tokens(section) for section in sections)) if sections else set()
    return bool(tokens & _tokens(" ".join(BIBLIOGRAPHY_HEADINGS)))


def _content_signals(text: str, sections: list[str]) -> dict[str, Any]:
    author_year = len(AUTHOR_YEAR.findall(text))
    numeric = len(NUMERIC.findall(text))
    captions = 0
    for line in text.splitlines():
        if CAPTION_PATTERN.match(line.strip()):
            captions += 1
    lowered = text.lower()
    research_terms = sorted(
        term
        for term in RESEARCH_TERMS
        if re.search(rf"\b{re.escape(term)}\b", lowered)
    )
    affiliations = sum(
        1 for term in AFFILIATION_TERMS if term in lowered
    )
    return {
        "author_year_citations": author_year,
        "numeric_citations": numeric,
        "figure_captions": captions,
        "research_terms": research_terms,
        "affiliation_mentions": affiliations,
    }


def _word_count(text: str) -> int:
    return len(text.split())


def classify_research_paper(
    passages: list[dict[str, Any]],
    references: list[Any],
    images: list[Any] | None = None,
    bibliography_detected: bool = False,
) -> ResearchClassification:
    """Decide whether an extracted document plausibly is a research paper.

    Returns one of the four spec outcomes. Only ``rejected`` refuses to open
    a document, and it requires an absence of every structural and content
    signal rather than the absence of any single section.
    """
    images = images or []
    sections = [passage["section"] for passage in passages]
    text = "\n".join(passage["text"] for passage in passages)
    words = _word_count(text)

    present, missing = _matched_groups(sections)
    content = _content_signals(text, sections)
    has_bibliography = _bibliography_found(sections, bibliography_detected)
    citations = (
        content["author_year_citations"] + content["numeric_citations"]
    )
    structural = len(present) + (1 if has_bibliography else 0)
    content_score = (
        (2 if citations else 0)
        + (1 if references else 0)
        + (1 if content["figure_captions"] or images else 0)
        + (1 if content["research_terms"] else 0)
        + (1 if content["affiliation_mentions"] else 0)
    )

    signals = [f"section: {label}" for label in present]
    if has_bibliography:
        signals.append("bibliography heading")
    if references:
        signals.append(f"{len(references)} parsed reference entries")
    if citations:
        signals.append(
            f"{citations} in-text citation(s) "
            f"({content['author_year_citations']} author–year, "
            f"{content['numeric_citations']} numeric)"
        )
    if content["figure_captions"] or images:
        signals.append(
            f"{content['figure_captions']} caption(s) and {len(images)} figure(s)"
        )
    if content["research_terms"]:
        signals.append(
            "research language: " + ", ".join(content["research_terms"][:6])
        )
    if content["affiliation_mentions"]:
        signals.append(
            f"{content['affiliation_mentions']} affiliation-like mention(s)"
        )
    signals.append(f"{words:,} words")

    missing_signals = [f"section: {label}" for label in missing]
    if not has_bibliography:
        missing_signals.append("bibliography heading")
    if not citations:
        missing_signals.append("in-text citations")

    none_of_everything = not structural and content_score == 0

    if none_of_everything:
        outcome = "rejected"
        message = (
            "No research-paper structure was found: no abstract, introduction, "
            "methods, results, discussion, conclusion, or reference section, "
            "and no citations, figure captions, or research language. This "
            "looks like a different kind of document. It has not been opened."
        )
    elif structural >= 4 and content_score >= 2:
        outcome = "accepted"
        message = (
            "This looks like a research paper. "
            + (
                "Its structure is complete enough to open normally."
                if not missing_signals
                else "Some usual sections are missing, which many papers omit "
                "and which does not affect reading it."
            )
        )
    elif structural >= 2 or content_score >= 3:
        outcome = "accepted_with_warnings"
        missing_text = ", ".join(missing_signals) if missing_signals else "none"
        message = (
            "This looks like a research paper, but its structure is unusual. "
            f"Missing or unrecognised: {missing_text}. Open it anyway if you "
            "recognise it as a paper."
        )
    else:
        outcome = "needs_review"
        missing_text = ", ".join(missing_signals) if missing_signals else "none"
        message = (
            "This could not be confidently identified as a research paper. "
            f"Found {structural} structural and {content_score} content "
            f"signal(s); missing or unrecognised: {missing_text}. Confirm to "
            "open it, or discard it."
        )

    return ResearchClassification(
        outcome=outcome,
        signals=signals,
        missing_signals=missing_signals,
        message=message,
    )


__all__ = ["BIBLIOGRAPHY_HEADINGS", "STRUCTURAL_SIGNALS", "classify_research_paper"]