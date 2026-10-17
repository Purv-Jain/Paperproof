"""Deterministic question-intent routing.

Retrieval and the model call both depend on which kinds of evidence a question
actually needs, so that a normal paper question is not answered from the
bibliography and a reference question is not answered from body text alone.

The rules here are intentionally transparent and inspectable. A small
structured classifier can be layered on later for cases the rules miss, but it
must never be the only signal: every decision still has to be explainable to
the user.
"""

from __future__ import annotations

import re

# Words that mean the question is about the bibliography itself.
REFERENCE_TERMS = frozenset(
    {
        "reference",
        "references",
        "bibliography",
        "citation",
        "citations",
        "cite",
        "cited",
        "cites",
        "citing",
        "doi",
        "source",
        "sources",
        "works",
        "cited",
        "et",
        "al",
    }
)

# Phrases that make a reference question unambiguous.
REFERENCE_PHRASES = (
    "reference list",
    "reference lists",
    "works cited",
    "bibliograph",
    "doi",
    "cited in the text",
    "cited in this paper",
    "is cited",
    "are cited",
    "never cited",
    "uncited",
)

# Words that mean the question is about a figure, chart, or table.
IMAGE_TERMS = frozenset(
    {
        "figure",
        "figures",
        "fig",
        "figs",
        "chart",
        "charts",
        "graph",
        "graphs",
        "plot",
        "plots",
        "diagram",
        "diagrams",
        "image",
        "images",
        "picture",
        "pictures",
        "photo",
        "photos",
        "photograph",
        "illustration",
        "table",
        "tables",
        "exhibit",
        "panel",
        "axis",
        "axes",
        "legend",
        "caption",
        "captions",
    }
)

# Explicit requests to look outside the paper. External context is never used
# silently; these phrases are the only way to switch it on.
EXTERNAL_PHRASES = (
    "current evidence",
    "latest research",
    "latest evidence",
    "recent studies",
    "recent research",
    "these days",
    "to date",
    "what do experts",
    "experts say",
    "according to the web",
    "external sources",
    "on the web",
    "search the web",
    "look it up",
    "today",
    "nowadays",
)


def _tokens(text: str) -> set[str]:
    return {word for word in re.findall(r"[a-z0-9]+", text.lower()) if len(word) > 1}


def detect_sources(question: str) -> dict[str, bool]:
    """Decide which evidence kinds a question needs.

    Returns flags for ``references``, ``images``, and ``external``. All are
    opt-in: an unrecognised question is treated as ordinary paper text, which
    keeps the existing retrieval behaviour intact.
    """
    lowered = question.lower()
    tokens = _tokens(question)

    references = any(phrase in lowered for phrase in REFERENCE_PHRASES)
    if not references:
        # "citation" only counts when it reads like a question about the
        # bibliography, not when it appears inside a quoted claim.
        references = bool(
            tokens
            & {
                "reference",
                "references",
                "bibliography",
                "doi",
                "cited",
                "uncited",
                "bibliographic",
            }
        )

    images = bool(tokens & IMAGE_TERMS)

    external = any(phrase in lowered for phrase in EXTERNAL_PHRASES)

    return {
        "references": references,
        "images": images,
        "external": external,
        "mixed": sum([references, images, external]) > 1,
    }


__all__ = [
    "EXTERNAL_PHRASES",
    "IMAGE_TERMS",
    "REFERENCE_PHRASES",
    "REFERENCE_TERMS",
    "detect_sources",
]