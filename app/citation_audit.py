import logging
import re
import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from difflib import SequenceMatcher
from typing import TypedDict
from urllib.parse import quote

import reflex as rx
import requests

from app.logging_safety import log_failure
from app.states.paper_data import (
    ExtractionLine,
    Paper,
    Passage,
    _is_bibliography_end,
    _is_bibliography_heading,
    _partition_lines,
)


MAX_VERIFIED_REFERENCES = 15
CROSSREF_URL = "https://api.crossref.org/works"
CROSSREF_RETRYABLE_STATUSES = {429, 502, 503, 504}
CROSSREF_MAX_ATTEMPTS = 3
CROSSREF_MAX_RETRY_AFTER = 30.0
CROSSREF_REQUEST_INTERVAL = 1.0

# Second resolver. Crossref indexes DOI-registered works only, so a preprint,
# book, thesis, or report returns "not found" there and becomes
# indistinguishable from a fabricated reference. OpenAlex covers far more and,
# unlike every other external service this project uses, requires no key and
# no billing, so the fallback costs nothing.
OPENALEX_URL = "https://api.openalex.org/works"
# OpenAlex asks callers to send a contact address so they can be reached before
# rate-limiting rather than silently blocked.
OPENALEX_HEADERS = {
    "User-Agent": "Paperproof/1.0 (citation audit; https://reflex.dev)"
}


class AuditIssue(TypedDict):
    category: str
    location: str
    excerpt: str
    explanation: str
    action: str
    severity: str


class ReferenceAudit(TypedDict):
    id: str
    text: str
    location: str
    status: str
    message: str
    doi: str
    url: str
    matched_title: str
    matched_author: str
    matched_year: str
    parsed_author: str
    parsed_title: str
    parsed_year: str
    parsed_venue: str
    lookup_method: str
    matched_fields: list[str]
    conflicting_fields: list[str]
    uncertainty: str
    checked_at: str


class AuditSummary(TypedDict):
    citations_found: int
    references_parsed: int
    references_checked: int
    confirmed: int
    needing_review: int
    extraction_warnings: int
    references_failed: int


class AuditNote(TypedDict):
    heading: str
    body: str


class AuditReport(TypedDict):
    paper_id: str
    status: str
    summary: str
    error: str
    issues: list[AuditIssue]
    references: list[ReferenceAudit]
    fix_prompt: str
    counts: AuditSummary
    explanation: list[AuditNote]
    limits: list[str]


# How serious each finding is. Severity drives the correction prompt grouping
# and the visual weight in the interface.
SEVERITY_BY_CATEGORY = {
    "Citation missing from reference list": "high",
    "Citation placement · manual review": "high",
    "Bibliography extraction": "high",
    "Conflicting publication year": "medium",
    "Citation style not fully supported": "medium",
    "Citation number out of range": "medium",
    "Uncited reference": "medium",
    "Possible duplicate reference": "medium",
    "Incomplete reference formatting": "low",
    "Verification limit": "low",
}


def issue(
    category: str,
    location: str,
    excerpt: str,
    explanation: str,
    action: str,
) -> AuditIssue:
    """Build a finding, deriving its severity from the category."""
    return AuditIssue(
        category=category,
        location=location,
        excerpt=excerpt,
        explanation=explanation,
        action=action,
        severity=SEVERITY_BY_CATEGORY.get(category, "low"),
    )


def empty_audit_report(paper_id: str = "") -> AuditReport:
    return AuditReport(
        paper_id=paper_id,
        status="not_run",
        summary="Run an audit to compare in-text citations with the reference list.",
        error="",
        issues=[],
        references=[],
        fix_prompt="",
        counts=AuditSummary(
            citations_found=0,
            references_parsed=0,
            references_checked=0,
            confirmed=0,
            needing_review=0,
            extraction_warnings=0,
        ),
        explanation=[],
        limits=[],
    )


def _location(section: str, page: int) -> str:
    if page > 0:
        return f"{section} · page {page}"
    return section or "Document location unavailable"


def _is_reference_heading(text: str) -> bool:
    return _is_bibliography_heading(text)


def _is_end_heading(text: str) -> bool:
    return _is_bibliography_end(text)


def _legacy_partition(
    paper: Paper,
) -> tuple[list[Passage], list[tuple[str, str]], bool]:
    lines: list[ExtractionLine] = []
    for passage in paper["passages"]:
        if _is_reference_heading(passage["section"]) or _is_end_heading(
            passage["section"]
        ):
            lines.append(
                ExtractionLine(
                    text=passage["section"],
                    page=passage["page"],
                    prominent=False,
                    heading=True,
                    table=False,
                )
            )
        for text in passage["text"].splitlines():
            lines.append(
                ExtractionLine(
                    text=text,
                    page=passage["page"],
                    prominent=False,
                    heading=False,
                    table=passage["section"] == "Extracted table",
                )
            )
    body, entries, found = _partition_lines(lines, "Document text")
    return body, [(entry["text"], "References") for entry in entries], found


def _body_passages(paper: Paper) -> list[Passage]:
    if paper["source"] == "sample" or paper.get("bibliography_parsed", False):
        return paper["passages"]
    return _legacy_partition(paper)[0]


VENUE_PATTERN = re.compile(
    r"\b(journal|review|press|proceedings|publisher|transactions|"
    r"annals|bulletin|quarterly|gazette|archives|reports?)\b",
    re.IGNORECASE,
)


def _reference_venue(text: str) -> str:
    """Best-effort source name, such as a journal or publisher.

    In the common style the venue follows the title and runs up to the first
    comma or volume marker, which is much more reliable than searching for a
    keyword anywhere in the entry.
    """
    title = _reference_title(text)
    if not title:
        return ""
    start = text.find(title)
    if start < 0:
        return ""
    rest = text[start + len(title) :].lstrip(" .,:;-–—")
    if not rest:
        return ""
    head = re.split(r"[,;]|\b\d+\s*\(", rest, maxsplit=1)[0]
    head = re.sub(r"\s+", " ", head).strip(" .")
    return head[:160]


def _parse_reference(text: str) -> dict[str, str]:
    """Pull structured fields out of one bibliography entry.

    These are derived values. The original text is always kept alongside them
    and is never overwritten.
    """
    return {
        "parsed_author": _reference_author(text),
        "parsed_title": _reference_title(text),
        "parsed_year": _reference_year(text),
        "parsed_venue": _reference_venue(text),
    }


def _references_for_paper(paper: Paper) -> tuple[list[ReferenceAudit], bool]:
    if (
        paper["source"] == "sample"
        or paper.get("bibliography_parsed", False)
        or paper.get("references")
    ):
        source_entries = [
            (reference["text"], f"References · entry {index}")
            for index, reference in enumerate(paper["references"], start=1)
        ]
        found_section = bool(source_entries) or paper.get(
            "bibliography_detected", False
        )
    else:
        _, source_entries, found_section = _legacy_partition(paper)
    parsed: list[ReferenceAudit] = []
    for index, (text, location) in enumerate(source_entries, start=1):
        entry_location = (
            location if "entry " in location else f"{location} · entry {index}"
        )
        parsed.append(
            ReferenceAudit(
                id=f"ref-{index}",
                text=text[:2400],
                location=entry_location,
                status="pending",
                message="",
                doi=_doi_from_text(text),
                url="",
                matched_title="",
                matched_author="",
                matched_year="",
                **_parse_reference(text),
                lookup_method="",
                matched_fields=[],
                conflicting_fields=[],
                uncertainty="",
                checked_at="",
            )
        )
    return parsed, found_section


def _clean_author(value: str) -> str:
    return re.sub(r"[^a-z]", "", value.lower())


def _citation_records(text: str) -> list[tuple[str, str, int, int]]:
    found: list[tuple[str, str, int, int]] = []
    occupied: list[tuple[int, int]] = []
    parenthetical = re.compile(r"\(([^()]{1,240})\)")
    author_year = re.compile(
        r"([A-Z][A-Za-z’'\-]+)(?:\s+(?:et\s+al\.?|and\s+[A-Z][A-Za-z’'\-]+|&\s*[A-Z][A-Za-z’'\-]+))?\s*,?\s*((?:19|20)\d{2}[a-z]?)",
        re.IGNORECASE,
    )
    for group in parenthetical.finditer(text):
        if not re.search(r"\b(?:19|20)\d{2}\b", group.group(1)):
            continue
        for match in author_year.finditer(group.group(1)):
            start = group.start() + 1 + match.start()
            end = group.start() + 1 + match.end()
            found.append((match.group(1), match.group(2), start, end))
            occupied.append((start, end))
    narrative = re.compile(
        r"\b([A-Z][A-Za-z’'\-]+)(?:\s+(?:et\s+al\.?|and\s+[A-Z][A-Za-z’'\-]+|&\s*[A-Z][A-Za-z’'\-]+))?\s*\(((?:19|20)\d{2}[a-z]?)\)",
        re.IGNORECASE,
    )
    for match in narrative.finditer(text):
        if any(start <= match.start() < end for start, end in occupied):
            continue
        found.append(
            (match.group(1), match.group(2), match.start(), match.end())
        )
    unique: dict[tuple[str, str, int, int], None] = {}
    for item in found:
        unique[item] = None
    return list(unique)


def _sentence_excerpt(text: str, start: int, end: int) -> str:
    left = (
        max(
            text.rfind(".", 0, start),
            text.rfind("!", 0, start),
            text.rfind("?", 0, start),
        )
        + 1
    )
    right_candidates = [
        position
        for character in ".!?"
        if (position := text.find(character, end)) >= 0
    ]
    right = min(right_candidates) + 1 if right_candidates else len(text)
    return " ".join(text[left:right].split())[:1000]


# Bracketed numeric citations such as [1], [1, 2], or [1-3]. Bracketed years
# like [2020] are excluded because four-digit runs cannot match this pattern.
NUMERIC_CITATION = re.compile(
    r"\[\s*\d{1,3}(?:\s*(?:,|;|-|–|—)\s*\d{1,3})*\s*\]"
)


def _citation_style(body_texts: list[str]) -> str:
    """Classify the citation style used in the extracted body text.

    Returns one of ``numeric``, ``mixed``, ``author_year``, or ``none``.
    The author-year parser cannot resolve bracketed numeric citations, so
    numeric and mixed documents must not be reported as having uncited or
    missing references.
    """
    numeric = sum(len(NUMERIC_CITATION.findall(text)) for text in body_texts)
    author_year = sum(len(_citation_records(text)) for text in body_texts)
    if numeric and author_year:
        return "mixed"
    if numeric:
        return "numeric"
    return "author_year" if author_year else "none"


def _numeric_citation_range(texts: list[str]) -> tuple[int, int]:
    """Highest and count of bracketed numeric citations in the body."""
    highest = 0
    found = 0
    for text in texts:
        for group in NUMERIC_CITATION.findall(text):
            for number in re.findall(r"\d{1,3}", group):
                highest = max(highest, int(number))
            found += 1
    return highest, found


def _citation_style_supported(style: str) -> bool:
    """Report whether uncited-reference checks are meaningful for this style."""
    return style in {"author_year", "none"}


def _numeric_citation_excerpt(body_texts: list[str]) -> str:
    """Return one sentence containing a numeric citation, for the finding."""
    for text in body_texts:
        match = NUMERIC_CITATION.search(text)
        if match:
            return _sentence_excerpt(text, match.start(), match.end())[:400]
    return ""


def _reference_year(text: str) -> str:
    match = re.search(r"\b((?:19|20)\d{2})[a-z]?\b", text)
    return match.group(1) if match else ""


def _reference_author(text: str) -> str:
    year_match = re.search(r"\b(?:19|20)\d{2}[a-z]?\b", text)
    prefix = text[: year_match.start()] if year_match else text[:160]
    match = re.search(r"\b([A-Z][A-Za-z’'\-]+)", prefix)
    return match.group(1) if match else ""


def _citation_reference_matches(author: str, reference: ReferenceAudit) -> bool:
    author_key = _clean_author(author)
    prefix = reference["text"].split("(", 1)[0]
    surnames = re.findall(r"\b[A-Z][A-Za-z’'\-]+", prefix)
    return any(_clean_author(surname) == author_key for surname in surnames)


def _normalized_text(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


def _reference_content_terms(text: str) -> set[str]:
    ignored = {
        "a",
        "an",
        "and",
        "as",
        "at",
        "by",
        "for",
        "from",
        "in",
        "of",
        "on",
        "or",
        "the",
        "to",
        "duplicate",
        "entry",
        "incomplete",
        "details",
        "journal",
        "et",
        "al",
        "doi",
        "https",
        "http",
    }
    author = _clean_author(_reference_author(text))
    return {
        word
        for word in _normalized_text(text).split()
        if word not in ignored and not word.isdigit() and word != author
    }


# Numeric/IEEE entries put the article title in quotes and the year further
# along, usually right before a trailing "doi:" label. Straight, curly and
# low-9 quotes all occur in the wild, because the marks come from the PDF.
_QUOTE_OPEN = "\u201c\u201f\u201e\""
_QUOTE_CLOSE = "\u201d\u201f\u201e\""
_QUOTED_TITLE = re.compile(
    f"[{_QUOTE_OPEN}](?P<title>[^{_QUOTE_OPEN}{_QUOTE_CLOSE}]{{8,400}}?)[{_QUOTE_CLOSE}]",
    re.DOTALL,
)


def _reference_title(text: str) -> str:
    # A quoted title is tried first. The year-based fallback below assumes the
    # APA layout "(2025). Title.", so on an IEEE entry it reads the year, takes
    # the remainder, and splits it at the first "." — which lands inside the
    # trailing DOI and returns "doi: 10" as the title. That both mislabels the
    # reference in the report and makes every external match score zero.
    quoted = _QUOTED_TITLE.search(text)
    if quoted:
        title = quoted.group("title").strip(" .,:;")
        # Reject a quoted DOI or bare number, which is not a title.
        if title and not re.fullmatch(
            r"(?:doi\s*:\s*)?(?:https?://\S+)?10\.\d{4,9}/\S+", title, re.IGNORECASE
        ):
            return title
    year_match = re.search(r"\(\s*(?:19|20)\d{2}[a-z]?\s*\)\.?\s*", text)
    if year_match:
        remainder = text[year_match.end() :]
        return remainder.split(".", 1)[0].strip(" .,:;")
    year_match = re.search(r"\b(?:19|20)\d{2}[a-z]?\b\.?\s*", text)
    if year_match:
        remainder = text[year_match.end() :]
        return remainder.split(".", 1)[0].strip(" .,:;")
    return ""


def _doi_from_text(text: str) -> str:
    match = re.search(
        r"(?:https?://(?:dx\.)?doi\.org/|\bdoi\s*:\s*)?(10\.\d{4,9}/[^\s<>\]\[\"{}]+)",
        text,
        re.IGNORECASE,
    )
    if not match:
        return ""
    return match.group(1).rstrip(".,;:)'").lower()


def _crossref_year(work: dict[str, object]) -> str:
    for field in ("published", "published-print", "published-online", "issued"):
        date_value = work.get(field)
        if not isinstance(date_value, dict):
            continue
        date_parts = date_value.get("date-parts")
        if (
            isinstance(date_parts, list)
            and date_parts
            and isinstance(date_parts[0], list)
            and date_parts[0]
        ):
            return str(date_parts[0][0])
    return ""


def _work_metadata(work: dict[str, object]) -> tuple[str, str, str, str]:
    titles = work.get("title")
    title = (
        titles[0]
        if isinstance(titles, list) and titles and isinstance(titles[0], str)
        else ""
    )
    authors = work.get("author")
    author = ""
    if isinstance(authors, list) and authors and isinstance(authors[0], dict):
        first_author = authors[0]
        family = first_author.get("family", "")
        author = family if isinstance(family, str) else ""
    doi = work.get("DOI", "")
    return (
        title,
        author,
        _crossref_year(work),
        doi if isinstance(doi, str) else "",
    )


def _metadata_agreement(
    reference: str, work: dict[str, object]
) -> tuple[bool, str, str, str]:
    title, author, year, _ = _work_metadata(work)
    expected_title = _reference_title(reference)
    expected_author = _reference_author(reference)
    expected_year = _reference_year(reference)
    title_ratio = (
        SequenceMatcher(
            None, _normalized_text(expected_title), _normalized_text(title)
        ).ratio()
        if expected_title and title
        else 0.0
    )
    author_matches = bool(
        expected_author
        and author
        and _clean_author(expected_author) == _clean_author(author)
    )
    year_matches = bool(expected_year and year and expected_year == year)
    confirmed = bool(
        expected_title
        and expected_author
        and expected_year
        and title
        and author
        and year
        and title_ratio >= 0.88
        and author_matches
        and year_matches
    )
    reasons = []
    if expected_title and title and title_ratio >= 0.88:
        reasons.append("title aligns")
    if author_matches:
        reasons.append("first author aligns")
    if year_matches:
        reasons.append("year aligns")
    return confirmed, ", ".join(reasons), title, author


def _crossref_retry_delay(
    response: requests.Response, retry_index: int
) -> float:
    delay = float(retry_index)
    retry_after = response.headers.get("Retry-After", "").strip()
    if retry_after:
        try:
            requested_delay = float(retry_after)
        except ValueError:
            try:
                retry_at = parsedate_to_datetime(retry_after)
                if retry_at.tzinfo is None:
                    retry_at = retry_at.replace(tzinfo=UTC)
                requested_delay = max(
                    0.0, (retry_at - datetime.now(UTC)).total_seconds()
                )
            except (TypeError, ValueError, OverflowError) as e:
                log_failure("Reading a Crossref Retry-After header", e)
                requested_delay = 0.0
        delay = max(delay, min(requested_delay, CROSSREF_MAX_RETRY_AFTER))
    return min(delay, CROSSREF_MAX_RETRY_AFTER)


def _api_get(
    url: str,
    *,
    headers: dict[str, str],
    params: dict[str, str | int] | None = None,
) -> requests.Response:
    """Retry a public metadata API request within a bounded request rate.

    Shared by both resolvers, because the polite-rate-limit and retry policy
    should not differ between them.
    """
    for attempt in range(CROSSREF_MAX_ATTEMPTS):
        response = requests.get(
            url, params=params, headers=headers, timeout=(3, 8)
        )
        if response.status_code not in CROSSREF_RETRYABLE_STATUSES:
            return response
        if attempt + 1 == CROSSREF_MAX_ATTEMPTS:
            return response
        time.sleep(_crossref_retry_delay(response, attempt + 1))
    raise RuntimeError("Metadata request retry loop ended unexpectedly.")


def _openalex_to_work(work: dict[str, object]) -> dict[str, object]:
    """Normalize an OpenAlex record into the Crossref record shape.

    The comparison code (`_work_metadata`, `_metadata_agreement`, `_conflicts`)
    is written against Crossref's field names and is the most heavily tested
    part of this module. Both resolvers therefore feed it the same shape rather
    than duplicating every check for a second provider.
    """
    doi = work.get("doi")
    if isinstance(doi, str) and doi.lower().startswith("https://doi.org/"):
        doi = doi[len("https://doi.org/") :]
    authors: list[dict[str, str]] = []
    for authorship in work.get("authorships") or []:
        if not isinstance(authorship, dict):
            continue
        person = authorship.get("author")
        name = person.get("display_name") if isinstance(person, dict) else ""
        if isinstance(name, str) and name.strip():
            # Crossref separates family and given names. The final token is the
            # closest safe approximation of a surname, and it is only ever
            # compared against the entry's own first author.
            parts = name.strip().split()
            authors.append(
                {
                    "family": parts[-1] if parts else "",
                    "given": " ".join(parts[:-1]),
                }
            )
    year = work.get("publication_year")
    return {
        "DOI": doi if isinstance(doi, str) else "",
        "title": [work.get("title") or ""],
        "author": authors,
        "published": {"date-parts": [[year]] if isinstance(year, int) else []},
    }


def _openalex_doi_work(doi: str) -> dict[str, object] | None:
    """Fetch one work by DOI from OpenAlex.

    Returns None when OpenAlex has no record, or when the lookup failed. The
    caller cannot tell those apart and must not: a resolver outage must never
    be reported as evidence that a reference is missing.
    """
    try:
        response = _api_get(
            f"{OPENALEX_URL}/doi:{quote(doi, safe='/')}",
            headers=OPENALEX_HEADERS,
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        body = response.json()
    except (requests.exceptions.RequestException, ValueError) as e:
        log_failure("OpenAlex DOI lookup", e)
        return None
    if not isinstance(body, dict) or not body.get("id"):
        return None
    return _openalex_to_work(body)


def _openalex_search_works(text: str) -> list[dict[str, object]]:
    """Search OpenAlex by bibliographic metadata. Returns [] on any failure."""
    try:
        response = _api_get(
            OPENALEX_URL,
            params={"search": text[:1200], "per-page": 3},
            headers=OPENALEX_HEADERS,
        )
        response.raise_for_status()
        body = response.json()
    except (requests.exceptions.RequestException, ValueError) as e:
        log_failure("OpenAlex bibliographic search", e)
        return []
    results = body.get("results") if isinstance(body, dict) else None
    if not isinstance(results, list):
        return []
    return [
        _openalex_to_work(item)
        for item in results
        if isinstance(item, dict) and item.get("id")
    ]


def _record_check(
    reference: ReferenceAudit,
    status: str,
    method: str,
    message: str,
    matched_fields: list[str] | None = None,
    conflicting_fields: list[str] | None = None,
    uncertainty: str = "",
) -> ReferenceAudit:
    """Stamp a verification outcome with its provenance and caveats."""
    reference["status"] = status
    reference["message"] = message
    reference["lookup_method"] = method
    reference["matched_fields"] = matched_fields or []
    reference["conflicting_fields"] = conflicting_fields or []
    reference["checked_at"] = datetime.now(UTC).isoformat(timespec="seconds")
    reference["uncertainty"] = uncertainty
    return reference


def _conflicts(reference: ReferenceAudit, work: dict[str, object]) -> list[str]:
    """Fields where the entry and the external record disagree."""
    title, author, year, _ = _work_metadata(work)
    conflicts: list[str] = []
    expected_title = reference["parsed_title"]
    expected_author = reference["parsed_author"]
    expected_year = reference["parsed_year"]
    if (
        expected_title
        and title
        and SequenceMatcher(
            None, _normalized_text(expected_title), _normalized_text(title)
        ).ratio()
        < 0.88
    ):
        conflicts.append("title")
    if expected_author and author and _clean_author(expected_author) != _clean_author(author):
        conflicts.append("first author")
    if expected_year and year and expected_year != year:
        conflicts.append("year")
    return conflicts


def _openalex_recovery(
    reference: ReferenceAudit, text: str, doi: str
) -> ReferenceAudit | None:
    """Try OpenAlex after Crossref failed, so one outage loses less coverage.

    Returns None when OpenAlex could not settle the entry either, leaving the
    caller to report the original failure honestly.
    """
    try:
        if doi:
            work = _openalex_doi_work(doi)
            if work is not None:
                return _record_doi_match(
                    reference,
                    text,
                    work,
                    doi,
                    "OpenAlex",
                    outage_note="Crossref was unreachable for this lookup.",
                )
            return None
        found = _select_search_match(text, _openalex_search_works(text))
        if len(found) == 1:
            work, reasons, title, author = found[0]
            reference["matched_title"] = title
            reference["matched_author"] = author
            reference["matched_year"] = _crossref_year(work)
            return _record_check(
                reference,
                "confirmed",
                "bibliographic_search · OpenAlex",
                f"Crossref was unreachable, but an OpenAlex record matches the available title, first-author, and year metadata ({reasons}).",
                matched_fields=reasons.split(", ") if reasons else [],
                uncertainty=(
                    "Matched by metadata similarity, not by DOI, and Crossref "
                    "could not be consulted for this lookup."
                ),
            )
    except Exception as e:  # a fallback must never mask the original failure
        log_failure("OpenAlex recovery lookup", e)
    return None


def _select_search_match(
    text: str, items: list[dict[str, object]]
) -> list[tuple[dict[str, object], str, str, str]]:
    """Candidates from a metadata search that agree with the entry.

    More than one is returned on purpose: several agreeing records is a
    different finding from none, and must be reported as ambiguous rather than
    folded into "not found".
    """
    matches: list[tuple[dict[str, object], str, str, str]] = []
    for item in items:
        is_match, reasons, title, author = _metadata_agreement(text, item)
        if is_match:
            matches.append((item, reasons, title, author))
    return matches


def _record_doi_match(
    reference: ReferenceAudit,
    text: str,
    work: dict[str, object],
    doi: str,
    resolver: str,
    outage_note: str = "",
) -> ReferenceAudit:
    """Record a verdict for a work located by its exact DOI.

    Shared by both resolvers so an OpenAlex hit is judged by exactly the same
    title/author/year rules as a Crossref hit. `lookup_method` keeps the plain
    "doi" value for Crossref and names the resolver only when it differs, so
    existing consumers that match on the original values keep working.

    `outage_note` discloses that the primary resolver was unreachable, because a
    confirmation obtained without consulting it is weaker evidence and the
    reader is entitled to know.
    """
    matches, reasons, title, author = _metadata_agreement(text, work)
    reference["doi"] = doi
    reference["matched_title"] = title
    reference["matched_author"] = author
    reference["matched_year"] = _crossref_year(work)
    method = "doi" if resolver == "Crossref" else f"doi · {resolver}"
    if matches:
        message = f"Exact DOI found in {resolver}; {reasons}."
        if outage_note:
            message = f"{outage_note} {message}"
        return _record_check(
            reference,
            "confirmed",
            method,
            message,
            matched_fields=reasons.split(", ") if reasons else [],
            uncertainty=outage_note,
        )
    return _record_check(
        reference,
        "ambiguous",
        method,
        f"The DOI resolves in {resolver}, but available title, first-author, or year metadata does not sufficiently match this entry. Review it manually.",
        conflicting_fields=_conflicts(reference, work),
        uncertainty=" ".join(
            part
            for part in (
                "The DOI resolved, so the work exists; the disagreement is "
                "between the supplied entry and the registered metadata.",
                outage_note,
            )
            if part
        ),
    )


def _verify_reference(reference: ReferenceAudit) -> ReferenceAudit:
    text = reference["text"]
    doi = _doi_from_text(text)
    headers = {
        "User-Agent": "Paperproof/1.0 (citation audit; https://reflex.dev)"
    }
    try:
        if doi:
            response = _api_get(
                f"{CROSSREF_URL}/{quote(doi, safe='')}",
                headers=headers,
            )
            if response.status_code == 404:
                # Crossref had nothing, so OpenAlex is asked before the entry is
                # reported missing. This is what keeps a real preprint or
                # non-DOI work from looking exactly like a fabricated reference.
                fallback = _openalex_doi_work(doi)
                if fallback is not None:
                    return _record_doi_match(
                        reference, text, fallback, doi, "OpenAlex"
                    )
                return _record_check(
                    reference,
                    "not_found_in_crossref",
                    "doi",
                    "No record was found for this DOI in Crossref or OpenAlex. This does not prove the work does not exist.",
                    uncertainty=(
                        "These registries index most DOI-registered works but not "
                        "every publisher, every older edition, or every preprint."
                    ),
                )
            response.raise_for_status()
            body = response.json()
            work = body.get("message") if isinstance(body, dict) else None
            if not isinstance(work, dict):
                reference["status"] = "lookup_error"
                reference["message"] = (
                    "Crossref returned an unexpected response; verify this reference manually."
                )
                return reference
            returned_doi = work.get("DOI", "")
            if not isinstance(returned_doi, str) or returned_doi.lower() != doi:
                reference["status"] = "ambiguous"
                reference["message"] = (
                    "Crossref returned metadata that did not match the supplied DOI exactly."
                )
                return reference
            return _record_doi_match(reference, text, work, returned_doi, "Crossref")

        response = _api_get(
            CROSSREF_URL,
            params={
                "query.bibliographic": text[:1200],
                "rows": 3,
                "select": "DOI,title,author,published,published-print,published-online,issued",
            },
            headers=headers,
        )
        response.raise_for_status()
        body = response.json()
        message = body.get("message") if isinstance(body, dict) else None
        items = message.get("items") if isinstance(message, dict) else None
        if not isinstance(items, list) or not items:
            found = _select_search_match(text, _openalex_search_works(text))
            if len(found) == 1:
                work, reasons, title, author = found[0]
                work_doi = work.get("DOI", "")
                reference["matched_title"] = title
                reference["matched_author"] = author
                reference["matched_year"] = _crossref_year(work)
                if isinstance(work_doi, str) and work_doi:
                    reference["doi"] = work_doi
                    reference["url"] = f"https://doi.org/{quote(work_doi, safe='/')}"
                return _record_check(
                    reference,
                    "confirmed",
                    "bibliographic_search · OpenAlex",
                    f"An OpenAlex record matches the available title, first-author, and year metadata ({reasons}).",
                    matched_fields=reasons.split(", ") if reasons else [],
                    uncertainty=(
                        "Matched by metadata similarity, not by DOI. Confirm it "
                        "is the intended work before relying on it."
                    ),
                )
            if len(found) > 1:
                return _record_check(
                    reference,
                    "ambiguous",
                    "bibliographic_search · OpenAlex",
                    "Multiple plausible OpenAlex records were found; choose the intended work manually.",
                    uncertainty=(
                        "More than one record matched this entry, so no single "
                        "work can be identified automatically."
                    ),
                )
            return _record_check(
                reference,
                "not_found_in_crossref",
                "bibliographic_search",
                "No matching record was found in Crossref or OpenAlex. This does not prove the work does not exist or is not registered elsewhere.",
                uncertainty=(
                    "A bibliographic search matches on metadata only. A book "
                    "chapter, report, or non-DOI source may not be indexed by "
                    "either registry."
                ),
            )
        matches: list[tuple[dict[str, object], str, str, str]] = []
        plausible = 0
        for item in items:
            if not isinstance(item, dict):
                continue
            is_match, reasons, title, author = _metadata_agreement(text, item)
            if is_match:
                matches.append((item, reasons, title, author))
            elif (
                title
                and _reference_title(text)
                and SequenceMatcher(
                    None,
                    _normalized_text(_reference_title(text)),
                    _normalized_text(title),
                ).ratio()
                >= 0.68
            ):
                plausible += 1
        if len(matches) == 1:
            work, reasons, title, author = matches[0]
            work_doi = work.get("DOI", "")
            reference["matched_title"] = title
            reference["matched_author"] = author
            reference["matched_year"] = _crossref_year(work)
            if isinstance(work_doi, str) and work_doi:
                reference["doi"] = work_doi
                reference["url"] = (
                    f"https://doi.org/{quote(work_doi, safe='/')}"
                )
            return _record_check(
                reference,
                "confirmed",
                "bibliographic_search",
                f"A Crossref record matches the available title, first-author, and year metadata ({reasons}).",
                matched_fields=reasons.split(", ") if reasons else [],
                uncertainty=(
                    "Matched by metadata similarity, not by DOI. Confirm it is "
                    "the intended work before relying on it."
                ),
            )
        reference["status"] = "ambiguous"
        reference["message"] = (
            "Multiple plausible Crossref records were found; choose the intended work manually."
            if len(matches) > 1 or plausible > 1
            else "Crossref search results did not agree sufficiently with the available title, first-author, and year. Verify the reference manually."
        )
        if items and isinstance(items[0], dict):
            title, author, year, _ = _work_metadata(items[0])
            reference["matched_title"] = title
            reference["matched_author"] = author
            reference["matched_year"] = year
        return _record_check(
            reference,
            "ambiguous",
            "bibliographic_search",
            reference["message"],
            conflicting_fields=_conflicts(reference, items[0])
            if items and isinstance(items[0], dict)
            else [],
            uncertainty=(
                "More than one candidate matched, or none matched closely. The "
                "closest record is shown, but it may be a different work."
            ),
        )
    except requests.exceptions.RequestException as e:
        # Crossref being unreachable must not be the end of the audit. OpenAlex
        # is independent, so a resolver outage degrades coverage instead of
        # reporting every reference as unverifiable.
        log_failure("Crossref lookup", e)
        recovered = _openalex_recovery(reference, text, doi)
        if recovered is not None:
            return recovered
        response = e.response
        if response is not None:
            logging.warning(
                "Crossref lookup failed with HTTP %s after up to %s attempts.",
                response.status_code,
                CROSSREF_MAX_ATTEMPTS,
            )
            message = (
                f"Crossref returned HTTP {response.status_code} and this reference could not be verified. Try again later or verify the source manually."
            )
        else:
            logging.warning("Crossref lookup failed: %s", e)
            message = (
                "Crossref could not be reached within the lookup time limit. Try again later or verify this reference manually."
            )
        return _record_check(
            reference,
            "lookup_error",
            "doi" if doi else "bibliographic_search",
            message,
            uncertainty=(
                "This is a temporary lookup failure, not a statement about the "
                "reference. Re-run the audit later."
            ),
        )
    except (ValueError, TypeError, KeyError, AttributeError) as e:
        log_failure("Reading a Crossref response", e)
        return _record_check(
            reference,
            "lookup_error",
            "doi" if doi else "bibliographic_search",
            "Crossref returned data that could not be checked safely. Verify this reference manually.",
            uncertainty="The provider response could not be interpreted safely.",
        )
    return reference


def _strong_claim(text: str) -> bool:
    return bool(
        re.search(
            r"\b(always|never|guarantees?|proves?|eliminates?|all\s+(?:students|people|patients)|causes?\s+(?:all|every))\b",
            text,
            re.IGNORECASE,
        )
    )


def _title_context_score(claim: str, reference: ReferenceAudit) -> float:
    title_terms = set(
        _normalized_text(_reference_title(reference["text"])).split()
    )
    claim_terms = set(_normalized_text(claim).split())
    if not title_terms or not claim_terms:
        return 0.0
    return len(title_terms & claim_terms) / max(1, len(title_terms))


def _build_issues(
    paper: Paper, references: list[ReferenceAudit], section_found: bool
) -> list[AuditIssue]:
    issues: list[AuditIssue] = []
    body_passages = _body_passages(paper)
    body_texts = [passage["text"] for passage in body_passages]
    style = _citation_style(body_texts)
    style_supported = _citation_style_supported(style)
    if not style_supported:
        issues.append(
            issue(
                category="Citation style not fully supported",
                location="Document body",
                excerpt=_numeric_citation_excerpt(body_texts),
                explanation=(
                    "This paper uses bracketed numeric citations, which Paperproof "
                    "cannot map to reference entries. Author–year uncited and "
                    "missing-reference checks are therefore withheld rather than "
                    "reported inaccurately; every listed reference would otherwise "
                    "appear uncited by mistake."
                ),
                action=(
                    "Review the numbered citations against the reference list "
                    "manually. Numeric citation coverage is not implemented yet."
                ),
            )
        )
    if not style_supported:
        highest, _ = _numeric_citation_range(body_texts)
        if references and highest > len(references):
            issues.append(
                issue(
                    category="Citation number out of range",
                    location="Document body",
                    excerpt=_numeric_citation_excerpt(body_texts),
                    explanation=(
                        f"The body cites a numbered reference as high as "
                        f"[{highest}], but only {len(references)} entries "
                        "were separated from the reference list. Either the "
                        "reference list was truncated during extraction, or a "
                        "citation number is wrong."
                    ),
                    action=(
                        "Count the entries in the original reference list and "
                        "check the highest citation number against it."
                    ),
                )
            )
    if paper["source"] != "sample" and not section_found:
        excerpt = ""
        for passage in paper["passages"]:
            match = re.search(
                r"references|bibliography|works cited",
                passage["text"],
                re.IGNORECASE,
            )
            if match:
                excerpt = passage["text"][
                    max(0, match.start() - 100) : match.start() + 180
                ].strip()
                break
        issues.append(
            issue(
                category="Bibliography extraction",
                location="Reference section not detected",
                excerpt=excerpt
                or "No References, Bibliography, or Works Cited section was detected in the extracted text.",
                explanation="Paperproof could not find a recognizable bibliography heading, so cross-checks against listed sources may be incomplete.",
                action="Check that the document has a clearly labeled reference section and that its text is selectable or readable; then rerun the audit.",
            )
        )
    elif paper["source"] != "sample" and section_found and not references:
        issues.append(
            issue(
                category="Bibliography extraction",
                location="Detected reference section",
                excerpt="A bibliography heading was found, but no entries could be separated confidently.",
                explanation="The extracted layout did not provide reliable entry boundaries. No existence or uncited-reference conclusions can be drawn from this section.",
                action="Review the reference section in the source document, add clear paragraph breaks between entries, or upload a searchable copy.",
            )
        )

    cited_references: set[str] = set()
    for passage in body_passages:
        for author, year, start, end in _citation_records(passage["text"]):
            author_matches = [
                reference
                for reference in references
                if _citation_reference_matches(author, reference)
            ]
            matching_year = [
                reference
                for reference in author_matches
                if _reference_year(reference["text"]) == year[:4]
            ]
            excerpt = _sentence_excerpt(passage["text"], start, end)
            location = _location(passage["section"], passage["page"])
            if matching_year:
                cited_references.update(
                    reference["id"] for reference in matching_year
                )
                for reference in matching_year:
                    if (
                        _strong_claim(excerpt)
                        and _title_context_score(excerpt, reference) < 0.12
                    ):
                        issues.append(
                            issue(
                                category="Citation placement · manual review",
                                location=location,
                                excerpt=excerpt,
                                explanation=f"This sentence makes a broad or absolute claim near a citation to “{_reference_title(reference['text']) or reference['text'][:110]}.” The title alone does not establish whether that source supports the claim; this is a review flag, not a verified error.",
                                action="Open the cited source and check whether it supports this exact claim and its scope. Narrow the wording or cite direct evidence if needed.",
                            )
                        )
            elif author_matches:
                reference = author_matches[0]
                cited_references.add(reference["id"])
                listed_year = _reference_year(reference["text"])
                issues.append(
                    issue(
                        category="Conflicting publication year",
                        location=location,
                        excerpt=excerpt,
                        explanation=f"The in-text citation gives {year}, while the apparent {author} reference entry gives {listed_year or 'no readable year'}. This may reflect an edition or online/print date difference.",
                        action="Check the source record and use a consistent author–year form in the text and reference list.",
                    )
                )
            else:
                issues.append(
                    issue(
                        category="Citation missing from reference list",
                        location=location,
                        excerpt=excerpt,
                        explanation=f"The in-text citation to {author} ({year}) could not be matched to a listed reference by author and year.",
                        action="Add the complete source to the reference list, or correct the in-text author/year if it points to a different listed entry.",
                    )
                )

    for reference in references:
        if reference["id"] not in cited_references and style_supported:
            issues.append(
                issue(
                    category="Uncited reference",
                    location=reference["location"],
                    excerpt=reference["text"][:1000],
                    explanation="This listed reference was not matched to an author–year citation in the extracted paper text. Numeric citation styles and extraction gaps can cause a missed match.",
                    action="Confirm that the source is cited in the text; otherwise remove it or use a consistent citation style.",
                )
            )
        year = _reference_year(reference["text"])
        title = _reference_title(reference["text"])
        detail_markers = re.search(
            r"\b(?:journal|review|press|proceedings|publisher|doi|https?://|vol\.?|\d+\s*\(|\d+\s*[-–]\s*\d+)\b",
            reference["text"],
            re.IGNORECASE,
        )
        missing: list[str] = []
        if not year:
            missing.append("publication year")
        if not title:
            missing.append("title")
        if len(reference["text"].split()) < 9 or not detail_markers:
            missing.append("journal, publisher, DOI, or other source details")
        if missing:
            issues.append(
                issue(
                    category="Incomplete reference formatting",
                    location=reference["location"],
                    excerpt=reference["text"][:1000],
                    explanation=f"The entry may be missing or obscuring {', '.join(dict.fromkeys(missing))}. Completeness depends on the source type and citation style.",
                    action="Compare this entry with the required style and source record; restore available bibliographic details without guessing.",
                )
            )

    for index, reference in enumerate(references):
        current_author = _clean_author(_reference_author(reference["text"]))
        current_title = _normalized_text(_reference_title(reference["text"]))
        for other in references[index + 1 :]:
            other_author = _clean_author(_reference_author(other["text"]))
            other_title = _normalized_text(_reference_title(other["text"]))
            same_title = bool(current_title and other_title) and (
                SequenceMatcher(None, current_title, other_title).ratio() >= 0.9
                or current_title in other_title
                or other_title in current_title
            )
            current_terms = _reference_content_terms(reference["text"])
            other_terms = _reference_content_terms(other["text"])
            shared_ratio = len(current_terms & other_terms) / max(
                1, min(len(current_terms), len(other_terms))
            )
            overlapping_entry = (
                bool(current_terms and other_terms) and shared_ratio >= 0.85
            )
            same_entry = _normalized_text(
                reference["text"]
            ) == _normalized_text(other["text"])
            if same_entry or (
                current_author
                and current_author == other_author
                and (same_title or overlapping_entry)
            ):
                issues.append(
                    issue(
                        category="Possible duplicate reference",
                        location=f"{reference['location']} and {other['location']}",
                        excerpt=f"{reference['text'][:450]}  /  {other['text'][:450]}",
                        explanation="These entries have highly similar titles and author details, or identical normalized text. Similar editions can be legitimate, so this is a duplicate candidate rather than a certainty.",
                        action="Compare the original records and retain one entry unless they represent distinct works or editions.",
                    )
                )
    return issues


def _correction_prompt(
    paper: Paper,
    issues: list[AuditIssue],
    references: list[ReferenceAudit],
    limits: list[str] | None = None,
) -> str:
    paper_label = (
        f"{paper['title']} ({paper['year']})"
        if paper["year"]
        else paper["title"]
    )
    limits = limits or []

    def block(severity: str) -> str:
        lines = [
            f"- [{issue['category']}] {issue['location']}\n"
            f"  Why: {issue['explanation']}\n"
            f"  Excerpt: “{' '.join(issue['excerpt'].split())[:350]}”\n"
            f"  Suggested action: {issue['action']}"
            for issue in issues
            if issue["severity"] == severity
        ]
        return "\n".join(lines) if lines else "- None."

    verification_lines = "\n".join(
        f"- {reference['location']} — {reference['status']} "
        f"(looked up by {reference['lookup_method'] or 'no method'}): "
        f"{reference['message']} "
        f"Original entry: “{' '.join(reference['text'].split())[:700]}”"
        + (
            f" Conflicting fields: {', '.join(reference['conflicting_fields'])}."
            if reference["conflicting_fields"]
            else ""
        )
        for reference in references
        if reference["status"] not in {"confirmed", "pending"}
    ) or "- Every entry that was looked up matched an external record."

    scope = (
        "The audit compared author–year citations against separated bibliography "
        "entries, checked entry completeness, year consistency, and duplicate "
        "candidates, and looked up references externally where possible."
    )
    limitations = (
        "\n".join(f"- {limit}" for limit in limits)
        if limits
        else "- Every supported check ran to completion."
    )
    counts = _build_counts(paper, references, issues)
    return f"""Paper under review
Title: {paper_label}
Authors: {paper['authors']}

Audit scope
{scope}
{counts['citations_found']} in-text citation(s), {counts['references_parsed']} bibliography entries, {counts['references_checked']} externally checked.

Important limitations
{limitations}

These are leads for review, not automatic proof of error.

Findings grouped by severity

High severity — check these first
{block('high')}

Medium severity
{block('medium')}

Low severity
{block('low')}

Reference verification notes
{verification_lines}

Requested correction format
- For each change, quote the original text, give the proposed replacement, and cite the source record that justifies it.
- Preserve the paper's existing citation style exactly. Do not convert between styles.
- Keep the authors' intended claims. Narrow a claim rather than silently rewriting it.

Safety rules
- Do not invent, guess, or complete any bibliographic detail.
- Never fabricate a DOI, page range, author, or publication year.
- If a field cannot be verified from the source record, mark it explicitly as unresolved and say what is needed.
- If a finding turns out to be wrong after checking, say so rather than changing anything.
- Return only changes supported by evidence you have actually seen."""[:12000]


def _build_counts(
    paper: Paper,
    references: list[ReferenceAudit],
    issues: list[AuditIssue],
) -> AuditSummary:
    citations = sum(
        len(_citation_records(passage["text"]))
        for passage in _body_passages(paper)
    )
    citations += sum(
        len(NUMERIC_CITATION.findall(passage["text"]))
        for passage in _body_passages(paper)
    )
    checked = sum(
        1
        for reference in references
        if reference["status"] not in {"pending", "not_checked_limit"}
    )
    failed = sum(
        1
        for reference in references
        if reference["status"] == "lookup_error"
    )
    return AuditSummary(
        citations_found=citations,
        references_parsed=len(references),
        references_checked=checked,
        confirmed=sum(
            1 for reference in references if reference["status"] == "confirmed"
        ),
        needing_review=sum(
            1
            for reference in references
            if reference["status"]
            in {
                "ambiguous",
                "partial_match",
                "not_found_in_crossref",
                "not_enough_metadata",
                "lookup_error",
            }
        ),
        extraction_warnings=len(paper.get("extraction_warnings", []) or []),
        references_failed=failed,
    )


def _build_explanation(
    counts: AuditSummary,
    issues: list[AuditIssue],
    references: list[ReferenceAudit],
    limits: list[str],
) -> list[AuditNote]:
    """The six-part plain-language explanation the audit interface shows."""
    reliable = [
        reference
        for reference in references
        if reference["status"] == "confirmed"
    ]
    review = [
        issue
        for issue in issues
        if issue["severity"] in {"high", "medium"}
    ]
    checked = [r for r in references if r["checked_at"]]
    return [
        AuditNote(
            heading="What was checked",
            body=(
                f"{counts['citations_found']} in-text citation(s) were located "
                f"and compared against {counts['references_parsed']} "
                "bibliography entries. Entry completeness, duplicate "
                "candidates, and year consistency were checked for every entry. "
                f"{counts['references_checked']} entries were looked up "
                "externally."
                f" {counts['references_failed']} lookup"
                f"{'s' if counts['references_failed'] != 1 else ''} "
                "failed."
            ),
        ),
        AuditNote(
            heading="What was found",
            body=(
                f"{len(issues)} finding(s) need attention: "
                + (
                    ", ".join(
                        f"{sum(1 for i in issues if i['severity'] == level)} "
                        f"{level}-severity"
                        for level in ("high", "medium", "low")
                        if any(i["severity"] == level for i in issues)
                    )
                    or "none"
                )
                + "."
            ),
        ),
        AuditNote(
            heading="What appears reliable",
            body=(
                f"{counts['confirmed']} reference(s) matched an external "
                "record on title, first author, and year."
                if reliable
                else "Nothing could be confirmed externally in this run."
            ),
        ),
        AuditNote(
            heading="What needs manual review",
            body=(
                "; ".join(
                    f"{issue['category']} ({issue['location']})"
                    for issue in review[:6]
                )
                + (f"; plus {len(review) - 6} more." if len(review) > 6 else "")
            )
            if review
            else "Nothing was flagged for manual review."
        ),
        AuditNote(
            heading="What could not be checked",
            body=(
                "; ".join(limits[:6])
                if limits
                else "Every supported check ran to completion."
            ),
        ),
        AuditNote(
            heading="What to do next",
            body=(
                "Open each finding in the source document and check it against "
                "the cited work before changing anything. Treat every finding "
                "as a lead, not a confirmed error."
                if issues
                else "Spot-check a few citations against the source records; "
                "a clean audit is not a guarantee."
            ),
        ),
        AuditNote(
            heading="Lookup timestamps",
            body=(
                ", ".join(sorted({r["checked_at"] for r in checked}))[:300]
                if checked
                else "No external lookups completed."
            ),
        ),
    ]


def run_citation_audit(paper: Paper) -> AuditReport:
    references, section_found = _references_for_paper(paper)
    issues = _build_issues(paper, references, section_found)
    verified_count = min(len(references), MAX_VERIFIED_REFERENCES)
    for index in range(verified_count):
        if index:
            time.sleep(CROSSREF_REQUEST_INTERVAL)
        try:
            references[index] = _verify_reference(references[index])
        except Exception as e:
            # One bad lookup must never cost the user the whole audit. Record
            # it as a limit on that entry and carry on with the findings the
            # structural pass already produced.
            logging.exception("Unexpected error while verifying a reference")
            references[index] = _record_check(
                references[index],
                "lookup_error",
                "doi" if references[index]["doi"] else "bibliographic_search",
                "This reference could not be verified because an unexpected "
                "error interrupted the lookup.",
                uncertainty=(
                    "The lookup was abandoned mid-request. This says nothing "
                    "about the reference itself; re-run the audit later."
                ),
            )
        reference = references[index]
        # An entry with too little metadata to search on is reported as its
        # own status rather than as a lookup failure.
        if (
            reference["status"] == "not_found_in_crossref"
            and not reference["parsed_title"]
            and not reference["parsed_author"]
            and not reference["doi"]
        ):
            _record_check(
                reference,
                "not_enough_metadata",
                "none",
                "This entry has too little readable metadata to look up safely, "
                "so no search was attempted.",
                uncertainty="A human can often identify this entry; an automatic lookup cannot.",
            )
        elif (
            reference["status"] == "ambiguous"
            and reference["matched_fields"]
            and len(reference["matched_fields"]) < 3
        ):
            reference["status"] = "partial_match"
            reference["message"] = (
                f"Some metadata aligned ({', '.join(reference['matched_fields'])}) "
                "but not enough to confirm this entry. Review it manually."
            )
    for reference in references[verified_count:]:
        _record_check(
            reference,
            "not_checked_limit",
            "none",
            f"Verification is limited to the first {MAX_VERIFIED_REFERENCES} entries per audit to avoid bursts of public API requests.",
            uncertainty="This entry was skipped entirely, not judged.",
        )
    if len(references) > MAX_VERIFIED_REFERENCES:
        issues.append(
            issue(
                category="Verification limit",
                location="Reference list",
                excerpt=f"{len(references)} entries detected; {MAX_VERIFIED_REFERENCES} were checked.",
                explanation="The audit caps Crossref lookups to keep requests bounded and avoid bursts. Remaining entries were not checked.",
                action="Review unchecked entries manually or run a smaller excerpt as a separate audit.",
            )
        )
    confirmed_count = sum(
        reference["status"] == "confirmed" for reference in references
    )
    unresolved_count = len(references) - confirmed_count
    style = _citation_style([p["text"] for p in _body_passages(paper)])
    style_supported = _citation_style_supported(style)
    # Every reason the audit could not be complete, stated explicitly.
    limits: list[str] = []
    if not section_found:
        limits.append(
            "No bibliography heading was detected, so no cross-check was possible."
        )
    if not references:
        limits.append("No bibliography entries could be separated for comparison.")
    if not style_supported:
        limits.append(
            "Citation style not fully supported: bracketed numeric citations "
            "cannot be mapped to entries, so uncited and missing-reference "
            "checks were withheld rather than reported inaccurately."
        )
    if len(references) > MAX_VERIFIED_REFERENCES:
        limits.append(
            f"Only the first {MAX_VERIFIED_REFERENCES} of "
            f"{len(references)} entries were looked up externally."
        )
    skipped = [
        r
        for r in references
        if r["status"] == "not_checked_limit"
    ]
    if skipped:
        limits.append(f"{len(skipped)} entries were not checked at all.")
    failed = [
        r
        for r in references
        if r["status"] == "lookup_error"
    ]
    if failed:
        limits.append(
            f"{len(failed)} lookups failed, usually a temporary provider problem."
        )
    sparse = [
        r
        for r in references
        if r["status"] == "not_enough_metadata"
    ]
    if sparse:
        limits.append(
            f"{len(sparse)} entries had too little metadata to look up safely."
        )

    incomplete = bool(limits)
    counts = _build_counts(paper, references, issues)
    explanation = _build_explanation(counts, issues, references, limits)
    if not references:
        summary = "No bibliography entries were available to compare. Review the extraction note below and check the document manually."
    else:
        summary = f"Checked {len(paper['passages'])} text sections and found {len(references)} reference entr{'y' if len(references) == 1 else 'ies'}; {confirmed_count} confirmed and {unresolved_count} unresolved; {len(issues)} actionable finding{'s' if len(issues) != 1 else ''} need review. Crossref results are supporting metadata, not proof of nonexistence."
    if incomplete:
        summary = f"Partial audit. {summary}"
    report = AuditReport(
        paper_id=paper["id"],
        status="incomplete" if incomplete else "complete",
        summary=summary,
        error="",
        issues=issues,
        references=references,
        fix_prompt="",
        counts=counts,
        explanation=explanation,
        limits=limits,
    )
    report["fix_prompt"] = _correction_prompt(paper, issues, references, limits)
    return report


def failed_audit_report(paper_id: str, message: str) -> AuditReport:
    report = empty_audit_report(paper_id)
    report["status"] = "error"
    report["summary"] = "The citation audit could not be completed."
    report["error"] = message
    return report
