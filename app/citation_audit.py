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


class AuditIssue(TypedDict):
    category: str
    location: str
    excerpt: str
    explanation: str
    action: str


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


class AuditReport(TypedDict):
    paper_id: str
    status: str
    summary: str
    error: str
    issues: list[AuditIssue]
    references: list[ReferenceAudit]
    fix_prompt: str


def empty_audit_report(paper_id: str = "") -> AuditReport:
    return AuditReport(
        paper_id=paper_id,
        status="not_run",
        summary="Run an audit to compare in-text citations with the reference list.",
        error="",
        issues=[],
        references=[],
        fix_prompt="",
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
                doi="",
                url="",
                matched_title="",
                matched_author="",
                matched_year="",
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


def _reference_title(text: str) -> str:
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
            except (TypeError, ValueError, OverflowError):
                logging.exception("Unexpected error")
                requested_delay = 0.0
        delay = max(delay, min(requested_delay, CROSSREF_MAX_RETRY_AFTER))
    return min(delay, CROSSREF_MAX_RETRY_AFTER)


def _crossref_get(
    url: str,
    *,
    headers: dict[str, str],
    params: dict[str, str | int] | None = None,
) -> requests.Response:
    for attempt in range(CROSSREF_MAX_ATTEMPTS):
        response = requests.get(
            url, params=params, headers=headers, timeout=(3, 8)
        )
        if response.status_code not in CROSSREF_RETRYABLE_STATUSES:
            return response
        if attempt + 1 == CROSSREF_MAX_ATTEMPTS:
            return response
        time.sleep(_crossref_retry_delay(response, attempt + 1))
    raise RuntimeError("Crossref request retry loop ended unexpectedly.")


def _verify_reference(reference: ReferenceAudit) -> ReferenceAudit:
    text = reference["text"]
    doi = _doi_from_text(text)
    headers = {
        "User-Agent": "Paperproof/1.0 (citation audit; https://reflex.dev)"
    }
    try:
        if doi:
            response = _crossref_get(
                f"{CROSSREF_URL}/{quote(doi, safe='')}",
                headers=headers,
            )
            if response.status_code == 404:
                reference["status"] = "not_found_in_crossref"
                reference["message"] = (
                    "No Crossref record was found for this DOI. This does not prove the work does not exist."
                )
                return reference
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
            matches, reasons, title, author = _metadata_agreement(text, work)
            reference["doi"] = returned_doi
            reference["matched_title"] = title
            reference["matched_author"] = author
            reference["matched_year"] = _crossref_year(work)
            if matches:
                reference["status"] = "confirmed"
                reference["url"] = (
                    f"https://doi.org/{quote(returned_doi, safe='/')}"
                )
                reference["message"] = (
                    f"Exact DOI found in Crossref; {reasons}."
                )
            else:
                reference["status"] = "ambiguous"
                reference["message"] = (
                    "The DOI resolves in Crossref, but available title, first-author, or year metadata does not sufficiently match this entry. Review it manually."
                )
            return reference

        response = _crossref_get(
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
            reference["status"] = "not_found_in_crossref"
            reference["message"] = (
                "No matching Crossref record was found. This does not prove the work does not exist or is not registered elsewhere."
            )
            return reference
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
            reference["status"] = "confirmed"
            reference["message"] = (
                f"A Crossref record matches the available title, first-author, and year metadata ({reasons})."
            )
            reference["matched_title"] = title
            reference["matched_author"] = author
            reference["matched_year"] = _crossref_year(work)
            if isinstance(work_doi, str) and work_doi:
                reference["doi"] = work_doi
                reference["url"] = (
                    f"https://doi.org/{quote(work_doi, safe='/')}"
                )
            return reference
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
        return reference
    except requests.exceptions.RequestException as e:
        logging.exception("Unexpected error")
        response = e.response
        if response is not None:
            logging.warning(
                "Crossref lookup failed with HTTP %s after up to %s attempts.",
                response.status_code,
                CROSSREF_MAX_ATTEMPTS,
            )
            reference["message"] = (
                f"Crossref returned HTTP {response.status_code} and this reference could not be verified. Try again later or verify the source manually."
            )
        else:
            logging.warning("Crossref lookup failed: %s", e)
            reference["message"] = (
                "Crossref could not be reached within the lookup time limit. Try again later or verify this reference manually."
            )
        reference["status"] = "lookup_error"
    except (ValueError, TypeError, KeyError, AttributeError) as e:
        logging.exception(f"Error: {e}")
        reference["status"] = "lookup_error"
        reference["message"] = (
            "Crossref returned data that could not be checked safely. Verify this reference manually."
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
            AuditIssue(
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
            AuditIssue(
                category="Bibliography extraction",
                location="Detected reference section",
                excerpt="A bibliography heading was found, but no entries could be separated confidently.",
                explanation="The extracted layout did not provide reliable entry boundaries. No existence or uncited-reference conclusions can be drawn from this section.",
                action="Review the reference section in the source document, add clear paragraph breaks between entries, or upload a searchable copy.",
            )
        )

    cited_references: set[str] = set()
    for passage in _body_passages(paper):
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
                            AuditIssue(
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
                    AuditIssue(
                        category="Conflicting publication year",
                        location=location,
                        excerpt=excerpt,
                        explanation=f"The in-text citation gives {year}, while the apparent {author} reference entry gives {listed_year or 'no readable year'}. This may reflect an edition or online/print date difference.",
                        action="Check the source record and use a consistent author–year form in the text and reference list.",
                    )
                )
            else:
                issues.append(
                    AuditIssue(
                        category="Citation missing from reference list",
                        location=location,
                        excerpt=excerpt,
                        explanation=f"The in-text citation to {author} ({year}) could not be matched to a listed reference by author and year.",
                        action="Add the complete source to the reference list, or correct the in-text author/year if it points to a different listed entry.",
                    )
                )

    for reference in references:
        if reference["id"] not in cited_references:
            issues.append(
                AuditIssue(
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
                AuditIssue(
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
                    AuditIssue(
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
) -> str:
    paper_label = (
        f"{paper['title']} ({paper['year']})"
        if paper["year"]
        else paper["title"]
    )
    issue_lines = "\n".join(
        f"- {issue['category']} — {issue['location']}: {issue['explanation']} Excerpt: “{issue['excerpt'][:350]}” Suggested action: {issue['action']}"
        for issue in issues[:16]
    )
    if not issue_lines:
        issue_lines = "- No actionable citation inconsistencies were detected by this automated audit. Please still verify every citation and reference against the source document."
    verification_notes = [
        f"- {reference['location']} — {reference['status']}: {reference['message']} Original reference entry: “{reference['text'][:700]}”"
        for reference in references
        if reference["status"]
        in {
            "lookup_error",
            "not_checked_limit",
            "not_found_in_crossref",
            "ambiguous",
        }
    ]
    if verification_notes:
        issue_lines = f"{issue_lines}\n" + "\n".join(verification_notes)
    return (
        f"Please review the citation and reference list in the paper “{paper_label}” by {paper['authors']}. "
        "Use the audit notes below as leads, not as proof. Check every proposed change against the actual cited source and the paper's chosen citation style. "
        "Do not invent, replace, or complete bibliographic details from guesswork; mark information that cannot be verified and ask for the source record. "
        "Preserve the authors' intended claims, distinguish a possible mismatch from a verified mistake, and return only changes supported by evidence.\n\n"
        f"Grounded audit findings:\n{issue_lines}"
    )[:12000]


def run_citation_audit(paper: Paper) -> AuditReport:
    references, section_found = _references_for_paper(paper)
    issues = _build_issues(paper, references, section_found)
    verified_count = min(len(references), MAX_VERIFIED_REFERENCES)
    for index in range(verified_count):
        if index:
            time.sleep(CROSSREF_REQUEST_INTERVAL)
        references[index] = _verify_reference(references[index])
    for reference in references[verified_count:]:
        reference["status"] = "not_checked_limit"
        reference["message"] = (
            f"Verification is limited to the first {MAX_VERIFIED_REFERENCES} entries per audit to avoid bursts of public API requests."
        )
    if len(references) > MAX_VERIFIED_REFERENCES:
        issues.append(
            AuditIssue(
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
    incomplete = (
        not section_found
        or not references
        or len(references) > MAX_VERIFIED_REFERENCES
        or any(
            reference["status"] in {"lookup_error", "not_checked_limit"}
            for reference in references
        )
    )
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
    )
    report["fix_prompt"] = _correction_prompt(paper, issues, references)
    return report


def failed_audit_report(paper_id: str, message: str) -> AuditReport:
    report = empty_audit_report(paper_id)
    report["status"] = "error"
    report["summary"] = "The citation audit could not be completed."
    report["error"] = message
    return report
