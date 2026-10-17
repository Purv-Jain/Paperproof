"""Provenance for external search results.

Every external source shown to the user must carry enough information to be
checked by hand: where it came from, who published it, when it was retrieved,
what was actually used, and why it was included. A search snippet is never
presented on its own as a verified fact.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TypedDict
from urllib.parse import urlparse

# Bound how much untrusted external text can reach the interface.
MAX_SOURCES = 8
MAX_EXCERPT = 600
MAX_TITLE = 200
ALLOWED_SCHEMES = {"http", "https"}


class SearchSource(TypedDict):
    url: str
    title: str
    publisher: str
    retrieved_at: str
    excerpt: str
    reason: str
    verified: bool


def _clean(value: object, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:limit]


def _publisher(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _build_source(
    url: str,
    title: str,
    excerpt: str,
    reason: str,
    stamp: str,
) -> SearchSource:
    return SearchSource(
        url=url,
        title=title or url,
        publisher=_publisher(url),
        retrieved_at=stamp,
        excerpt=excerpt,
        reason=reason,
        verified=False,
    )


def parse_url_citations(
    annotations: object,
    reason: str,
    retrieved_at: str | None = None,
) -> list[SearchSource]:
    """Turn OpenRouter url_citation annotations into provenance records.

    Entries without a usable http(s) URL are dropped rather than shown as a
    source the user cannot open.
    """
    if not isinstance(annotations, list):
        return []
    stamp = retrieved_at or utc_now()
    sources: list[SearchSource] = []
    seen: set[str] = set()
    for annotation in annotations:
        if not isinstance(annotation, dict):
            continue
        citation = annotation.get("url_citation")
        if not isinstance(citation, dict):
            continue
        url = _clean(citation.get("url"), 500)
        parsed = urlparse(url) if url else None
        if not parsed or parsed.scheme not in ALLOWED_SCHEMES or not parsed.netloc:
            continue
        if url in seen:
            continue
        seen.add(url)
        sources.append(
            _build_source(
                url=url,
                title=_clean(citation.get("title"), MAX_TITLE),
                excerpt=_clean(citation.get("content"), MAX_EXCERPT),
                reason=reason,
                stamp=stamp,
            )
        )
        if len(sources) >= MAX_SOURCES:
            break
    return sources


def parse_gemini_annotations(
    annotations: object,
    reason: str,
    retrieved_at: str | None = None,
) -> list[SearchSource]:
    """Turn Gemini grounding annotations into provenance records.

    Gemini puts url/title on the annotation itself rather than nesting them,
    and its ``title`` is usually the publisher domain rather than a page
    title. It returns no excerpt, so the record honestly shows none.
    """
    if not isinstance(annotations, list):
        return []
    stamp = retrieved_at or utc_now()
    sources: list[SearchSource] = []
    seen: set[str] = set()
    for annotation in annotations:
        if not isinstance(annotation, dict):
            continue
        if annotation.get("type") not in (None, "url_citation"):
            continue
        url = _clean(annotation.get("url"), 500)
        parsed = urlparse(url) if url else None
        if not parsed or parsed.scheme not in ALLOWED_SCHEMES or not parsed.netloc:
            continue
        if url in seen:
            continue
        seen.add(url)
        sources.append(
            _build_source(
                url=url,
                title=_clean(annotation.get("title"), MAX_TITLE),
                excerpt="",
                reason=reason,
                stamp=stamp,
            )
        )
        if len(sources) >= MAX_SOURCES:
            break
    return sources


def provenance_warning(has_sources: bool) -> str:
    """Standing caveat shown with any external context."""
    if not has_sources:
        return ""
    return (
        "External results are search excerpts and metadata, not pages that "
        "Paperproof read end to end. Open each source before relying on it."
    )


__all__ = [
    "MAX_SOURCES",
    "SearchSource",
    "parse_gemini_annotations",
    "parse_url_citations",
    "provenance_warning",
    "utc_now",
]