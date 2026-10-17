import reflex as rx

from copy import deepcopy
from io import BytesIO
import logging
import re
from collections import Counter
from pathlib import Path
import time
from typing import NotRequired, TypedDict
from uuid import uuid4
from zipfile import BadZipFile, ZipFile

import pymupdf
import pytesseract
from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph
from faker import Faker
from PIL import Image
from pypdf import PdfReader

from app.image_extraction import (
    ExtractionWarning,
    PaperImage,
    ResearchClassification,
    extract_docx_images,
    extract_pdf_images,
    warning,
)
from app.logging_safety import log_failure
from app.paper_classification import classify_research_paper


class Passage(TypedDict):
    id: str
    section: str
    page: int
    text: str


class RetrievedPassage(TypedDict):
    id: str
    passage_id: str
    section: str
    page: int
    text: str


class AnswerEvidence(TypedDict):
    id: str
    passage_id: str
    section: str
    page: int
    text: str
    kind: str
    detail: str


class Reference(TypedDict):
    id: str
    text: str
    order: NotRequired[int]
    raw_text: NotRequired[str]
    authors: NotRequired[list[str]]
    first_author: NotRequired[str]
    year: NotRequired[str]
    title: NotRequired[str]
    doi: NotRequired[str]
    url: NotRequired[str]


class Paper(TypedDict):
    id: str
    title: str
    authors: str
    year: str
    topic: str
    source: str
    filename: str
    page_count: int
    word_count: int
    note: str
    passages: list[Passage]
    references: list[Reference]
    images: NotRequired[list[PaperImage]]
    extraction_warnings: NotRequired[list[ExtractionWarning]]
    research_classification: NotRequired[ResearchClassification]
    bibliography_parsed: NotRequired[bool]
    bibliography_detected: NotRequired[bool]


MAX_BYTES = 10 * 1024 * 1024
MAX_PAGES = 120
MAX_TEXT = 300_000
MAX_OCR_PAGES = 20
MAX_OCR_SECONDS = 90
OCR_TIMEOUT_SECONDS = 12


def _paper(
    title: str,
    topic: str,
    passages: list[Passage],
    references: list[str],
    authors: str,
    identifier: str,
) -> Paper:
    return Paper(
        id=identifier,
        title=title,
        authors=authors,
        year="2024",
        topic=topic,
        source="sample",
        filename="",
        page_count=max(p["page"] for p in passages),
        word_count=sum(len(p["text"].split()) for p in passages),
        note="Fictional teaching paper with intentionally mixed citation issues. Study results are illustrative, not research evidence. References have not been verified by Paperproof.",
        passages=passages,
        references=[
            Reference(id=f"r{i + 1}", text=text)
            for i, text in enumerate(references)
        ],
        images=[],
        extraction_warnings=[],
        research_classification=ResearchClassification(
            outcome="accepted",
            signals=[],
            missing_signals=[],
            message="Fictional teaching paper.",
        ),
    )


def get_sample_papers() -> list[Paper]:
    fake = Faker()
    fake.seed_instance(41)
    authors = [f"{fake.name()} & {fake.name()}" for _ in range(3)]
    return deepcopy(
        [
            _paper(
                "Does putting your phone away help you learn?",
                "Learning & attention",
                [
                    Passage(
                        id="p1",
                        section="Abstract",
                        page=1,
                        text="This illustrative study examines whether keeping a smartphone out of sight is associated with better recall during independent study. Eighty-four undergraduate students completed a 25-minute reading task with their phone either on the desk or in a separate room. The separate-room group recalled an average of 7.8 of 12 concepts, compared with 6.9 in the desk group. The result concerns short-term recall, not long-term academic performance.",
                    ),
                    Passage(
                        id="p2",
                        section="Introduction",
                        page=2,
                        text="Attention is a limited resource. Ward et al. (2017) found that the mere presence of a smartphone can reduce available cognitive capacity. Notifications may also interrupt attention even when the device is not actively used (Stothart et al., 2015). These findings motivate a practical question: can changing the study environment support comprehension?",
                    ),
                    Passage(
                        id="p3",
                        section="Methods",
                        page=3,
                        text="Participants were recruited from two introductory psychology classes and randomly assigned to a phone-location condition. All participants read the same 1,600-word passage and answered twelve short-answer questions. Two raters scored the responses without knowing condition. Participants with urgent communication needs were excluded. The sample was drawn from one university, and prior familiarity with the reading topic was not measured.",
                    ),
                    Passage(
                        id="p4",
                        section="Results & discussion",
                        page=4,
                        text="The mean recall difference was 0.9 concepts (95% confidence interval: 0.1 to 1.7). The findings are consistent with reduced distraction but do not identify the mechanism. Putting a phone in another room guarantees higher grades for all students (Ward et al., 2017). This interpretation exceeds the short-term recall outcome measured here. A related classroom effect was reported by Chen and Patel (2022), although that source is absent from the reference list.",
                    ),
                    Passage(
                        id="p5",
                        section="Limitations & conclusion",
                        page=5,
                        text="The study used a small convenience sample and a single reading task. Participants knew where their phones were, which could influence expectations. No semester grades or delayed recall were collected. Future research should preregister a larger study and measure retention after one week. For now, the results suggest a modest short-term benefit of keeping phones out of sight, not a universal study rule.",
                    ),
                ],
                [
                    "Ward, A. F., Duke, K., Gneezy, A., & Bos, M. W. (2017). Brain drain: The mere presence of one's own smartphone reduces available cognitive capacity. Journal of the Association for Consumer Research, 2(2), 140–154.",
                    "Stothart, C., Mitchum, A., & Yehnert, C. (2015). The attentional cost of receiving a cell phone notification. Journal of Experimental Psychology: Human Perception and Performance, 41(4), 893–897.",
                    "Ward, A. F. et al. Brain drain. 2017. (Duplicate entry; incomplete journal details.)",
                ],
                authors[0],
                "sample-attention",
            ),
            _paper(
                "Small green spaces, everyday wellbeing",
                "Environment & wellbeing",
                [
                    Passage(
                        id="p1",
                        section="Abstract",
                        page=1,
                        text="This fictional campus study explores the association between time in small green spaces and self-reported wellbeing. A two-week diary study followed  sixty students. Days with at least fifteen minutes outdoors were associated with higher wellbeing ratings. The observational design does not establish that green spaces caused the improvement.",
                    ),
                    Passage(
                        id="p2",
                        section="Background",
                        page=2,
                        text="Urban nature may provide opportunities for psychological restoration. Hartig et al. (2014) reviewed pathways linking nature and health. Bratman et al. (2015) studied nature experience and rumination. Their work motivates measuring everyday outdoor exposure, but neither study directly evaluates this campus.",
                    ),
                    Passage(
                        id="p3",
                        section="Methods",
                        page=3,
                        text="Sixty volunteers recorded outdoor minutes and wellbeing each evening for fourteen days. Wellbeing was rated from 1 to 7. The analysis compared each student's higher- and lower-exposure days and adjusted for reported sleep duration. Outdoor minutes were self-reported, not tracked by GPS. Weather and examination stress were not measured.",
                    ),
                    Passage(
                        id="p4",
                        section="Findings",
                        page=4,
                        text="Higher-exposure days averaged 0.4 points higher wellbeing on the seven-point scale. Missing diary entries accounted for 18% of potential observations. Parks eliminate clinical depression (Bratman et al., 2016). That statement goes beyond the diary measure and uses a year that differs from the listed reference. A campus intervention is described by Rivera (2023), but the supplied DOI is a fictional placeholder.",
                    ),
                    Passage(
                        id="p5",
                        section="Limitations & next steps",
                        page=5,
                        text="Students who felt better may have chosen to spend more time outdoors. Selection effects and unmeasured weather could explain part of the association. The sample does not represent all students, and the diary did not measure clinical symptoms. A randomized study could compare scheduled outdoor breaks with indoor breaks using the same wellbeing measure.",
                    ),
                ],
                [
                    "Hartig, T., Mitchell, R., de Vries, S., & Frumkin, H. (2014). Nature and health. Annual Review of Public Health, 35, 207–228.",
                    "Bratman, G. N., Hamilton, J. P., Hahn, K. S., Daily, G. C., & Gross, J. J. (2015). Nature experience reduces rumination and subgenual prefrontal cortex activation. Proceedings of the National Academy of Sciences, 112(28), 8567–8572.",
                    "Rivera, L. (2023). Campus microparks and wellbeing. Fictional teaching reference. https://doi.org/10.0000/paperproof.example",
                ],
                authors[1],
                "sample-green",
            ),
            _paper(
                "Learning by explaining: peer discussion in class",
                "Education & collaboration",
                [
                    Passage(
                        id="p1",
                        section="Abstract",
                        page=1,
                        text="This fictional pilot examines peer discussion in a first-year biology class. Forty-eight students answered concept questions individually, discussed them in pairs, and answered again. Correct responses increased from 54% to 71%. Without a comparison group, the improvement cannot be attributed solely to peer discussion.",
                    ),
                    Passage(
                        id="p2",
                        section="Introduction",
                        page=2,
                        text="Explaining an idea can reveal gaps in understanding. Smith et al. (2009) describe how peer discussion can improve performance on concept questions. Freeman et al. (2014) report evidence on active learning across undergraduate science courses. These findings provide background rather than a direct test of this classroom activity.",
                    ),
                    Passage(
                        id="p3",
                        section="Study design",
                        page=3,
                        text="The activity took place during one scheduled class. Students answered eight questions before and after paired discussion. Partners were chosen by seating position. The instructor did not provide correct answers until both rounds were complete. Scores were anonymous, so the analysis used class-level proportions rather than paired individual changes.",
                    ),
                    Passage(
                        id="p4",
                        section="Results & interpretation",
                        page=4,
                        text="The class-level proportion of correct responses rose by seventeen percentage points. Repeated exposure to the questions could account for some improvement. All students learn twice as fast through discussion (Freeman et al., 2014). Learning speed was not measured in this pilot. Smith et al. (2009) is also cited as evidence about online discussion, although the listed study concerns classroom concept questions.",
                    ),
                    Passage(
                        id="p5",
                        section="Conclusion",
                        page=5,
                        text="Peer discussion is a promising teaching practice, but this pilot supports only a limited claim about performance during a single class. A comparison condition, linked individual responses, and a delayed test would strengthen the design. The results should not be interpreted as evidence about online teaching or long-term retention.",
                    ),
                ],
                [
                    "Smith, M. K., Wood, W. B., Adams, W. K., Wieman, C., Knight, J. K., Guild, N., & Su, T. T. (2009). Why peer discussion improves student performance on in-class concept questions. Science, 323(5910), 122–124.",
                    "Freeman et al. (2014). Active learning increases student performance in science, engineering, and mathematics. PNAS. (Incomplete author, volume, and page details.)",
                    "Dunlosky, J., et al. (2013). Improving students' learning with effective learning techniques. Psychological Science in the Public Interest, 14(1), 4–58.",
                ],
                authors[2],
                "sample-peers",
            ),
        ]
    )


def _has_meaningful_text(text: str) -> bool:
    words = text.split()
    alphanumeric_count = sum(character.isalnum() for character in text)
    return alphanumeric_count >= 20 and len(words) >= 3


class ExtractionLine(TypedDict):
    text: str
    page: int
    prominent: bool
    heading: bool
    table: bool


def _heading_label(text: str) -> str:
    text = re.sub(r"^\s*(?:\d+(?:\.\d+)*[.)]?|[IVX]+[.)])\s+", "", text)
    return " ".join(text.strip().rstrip(":").split())


def _is_bibliography_heading(text: str) -> bool:
    return _heading_label(text).casefold() in {
        "references",
        "bibliography",
        "works cited",
        "literature cited",
        "references and notes",
    }


def _is_bibliography_end(text: str) -> bool:
    return (
        bool(
            re.fullmatch(
                r"(?:appendi(?:x|ces)\b.*|supplement(?:s|ary)?\b.*|supporting information\b.*|"
                r"author contributions|acknowledg(?:e)?ments?|funding|conflicts? of interest)",
                _heading_label(text),
                re.IGNORECASE,
            )
        )
        and len(text) < 160
    )


def _looks_like_heading(line: ExtractionLine, isolated: bool = False) -> bool:
    text = line["text"].strip()
    label = _heading_label(text)
    if (
        line["table"]
        or not label
        or len(label) > 120
        or len(label.split()) > 14
    ):
        return False
    if _is_bibliography_heading(text) or _is_bibliography_end(text):
        return True
    if line["heading"]:
        return True
    if re.search(r"[.!?;]$|\b(?:19|20)\d{2}\b|https?://|[|]", label):
        return False
    if label.casefold() in {
        "abstract",
        "summary",
        "synopsis",
        "introduction",
        "background",
        "methods",
        "method",
        "methodology",
        "materials and methods",
        "results",
        "findings",
        "discussion",
        "conclusion",
        "conclusions",
        "limitations",
        "results and discussion",
        "results & discussion",
    }:
        return True
    if re.match(r"^\d+(?:\.\d+)*[.)]?\s+[A-Za-z]", text):
        return len(label.split()) <= 10 and not re.search(r"[,()]", label)
    if label.isupper() and len(label.split()) <= 10 and len(label) > 2:
        return True
    headline = len(label.split()) >= 2 and all(
        word[0].isupper()
        or word.lower() in {"and", "of", "the", "in", "for", "to", "a", "&"}
        for word in label.split()
    )
    return (line["prominent"] or (isolated and headline)) and not re.search(
        r"[,()]", label
    )


def _reference_start(text: str) -> bool:
    if " | " in text:
        return False
    numbered = bool(re.match(r"^(?:\[\d+\]|\d+[.)])\s*", text))
    cleaned = re.sub(r"^(?:\[\d+\]|\d+[.)])\s*", "", text)
    author = bool(
        re.match(
            r"^[A-ZÀ-ÖØ-Þ][\w’'\-]+,\s*(?:[A-Z]\.|[A-Z][a-z]+)|"
            r"^[A-ZÀ-ÖØ-Þ][\w’'\-]+\s+(?:et al\.|[A-Z]\.)(?:\s|,)",
            cleaned,
        )
    )
    return author or (numbered and bool(re.match(r"[A-ZÀ-ÖØ-Þ]", cleaned)))


def _credible_reference(text: str) -> bool:
    if not _reference_start(text) or len(text.split()) < 4:
        return False
    cleaned = re.sub(r"^(?:\[\d+\]|\d+[.)])\s*", "", text)
    author_shape = bool(
        re.match(
            r"^[A-ZÀ-ÖØ-Þ][\w’'\-]+(?:,\s*[A-Z]|\s+[A-Z]\.|\s+et al\.)", cleaned
        )
    )
    source_detail = bool(
        re.search(
            r"\b10\.\d{4,9}/|https?://|\b(?:journal|press|proceedings|publisher)\b",
            text,
            re.IGNORECASE,
        )
    )
    return (
        author_shape
        and bool(
            re.search(
                r"\b(?:18|19|20)\d{2}[a-z]?\b|https?://|\b10\.\d{4,9}/", text
            )
        )
    ) or (
        bool(re.match(r"^(?:\[\d+\]|\d+[.)])\s*[A-Z]", text)) and source_detail
    )


def _partition_lines(
    lines: list[ExtractionLine], fallback: str
) -> tuple[list[Passage], list[Reference], bool]:
    passages: list[Passage] = []
    references: list[Reference] = []
    section = fallback
    chunk: list[str] = []
    page = 0
    in_references = False
    detected = False
    entry: list[ExtractionLine] = []

    def flush_body():
        nonlocal chunk
        text = "\n".join(chunk).strip()
        if text:
            passages.append(
                Passage(
                    id=f"p{len(passages) + 1}",
                    section=section,
                    page=page,
                    text=text,
                )
            )
        chunk = []

    def flush_entry():
        nonlocal entry, section, page
        text = " ".join(line["text"] for line in entry).strip()
        if text and _credible_reference(text):
            references.append(
                Reference(id=f"r{len(references) + 1}", text=text)
            )
        elif text:
            flush_body()
            saved_section = section
            section = "Reference notes"
            for line in entry:
                if chunk and page != line["page"]:
                    flush_body()
                page = line["page"]
                chunk.append(line["text"])
            flush_body()
            section = saved_section
        entry = []

    for index, line in enumerate(lines):
        text = line["text"].strip()
        isolated = (index == 0 or not lines[index - 1]["text"].strip()) and (
            index + 1 == len(lines) or not lines[index + 1]["text"].strip()
        )
        heading = _looks_like_heading(line, isolated)
        if not line["table"] and _is_bibliography_heading(text):
            flush_body()
            if not in_references:
                flush_entry()
            detected = True
            in_references = True
            continue
        if in_references and heading and _is_bibliography_end(text):
            flush_entry()
            in_references = False
        if in_references and not line["table"]:
            if not text:
                continue
            if re.fullmatch(r"(?:page\s+)?\d+", text, re.IGNORECASE):
                continue
            if _reference_start(text):
                flush_entry()
                flush_body()
                entry = [line]
            elif entry:
                if re.match(
                    r"^(?:This|These|We|Our|The study|In this|Note:)\b", text
                ) and not re.search(
                    r"\b(?:journal|press|proceedings|doi)\b",
                    text,
                    re.IGNORECASE,
                ):
                    flush_entry()
                    flush_body()
                    section = "Reference notes"
                    page = line["page"]
                    chunk.append(text)
                else:
                    entry.append(line)
            else:
                if chunk and page != line["page"]:
                    flush_body()
                page = line["page"]
                section = "Reference notes"
                chunk.append(text)
            continue
        if line["table"]:
            flush_entry()
            flush_body()
            saved_section = section
            section = "Extracted table"
            page = line["page"]
            chunk.append(text)
            flush_body()
            section = saved_section
        elif heading:
            flush_body()
            section = _heading_label(text)
            page = line["page"]
        else:
            if chunk and page != line["page"]:
                flush_body()
            page = line["page"]
            chunk.append(text)
    flush_entry()
    flush_body()
    return passages, references, detected


def _pdf_prominent_lines(data: bytes) -> list[set[str]]:
    hints: list[set[str]] = []
    try:
        with pymupdf.open(stream=data, filetype="pdf") as document:
            for page in document:
                records: list[tuple[str, float, bool]] = []
                sizes: Counter[float] = Counter()
                for block in page.get_text("dict").get("blocks", []):
                    for line in block.get("lines", []):
                        spans = line.get("spans", [])
                        text = "".join(
                            span.get("text", "") for span in spans
                        ).strip()
                        size = max(
                            (float(span.get("size", 0)) for span in spans),
                            default=0.0,
                        )
                        bold = bool(spans) and all(
                            int(span.get("flags", 0)) & 16 for span in spans
                        )
                        sizes.update({round(size, 1): len(text)})
                        records.append((text, size, bold))
                baseline = sizes.most_common(1)[0][0] if sizes else 12.0
                hints.append(
                    {
                        " ".join(text.split())
                        for text, size, bold in records
                        if bold or size >= baseline + 1.5
                    }
                )
    except Exception as e:
        log_failure("PDF heading detection", e)
    return hints


def _docx_lines(document) -> list[ExtractionLine]:
    lines: list[ExtractionLine] = []
    normal_size = document.styles["Normal"].font.size
    baseline = normal_size.pt if normal_size else 11.0
    total = 0
    for child in document.element.body.iterchildren():
        if child.tag.endswith("}p"):
            paragraph = Paragraph(child, document)
            text = paragraph.text.strip()
            runs = [run for run in paragraph.runs if run.text.strip()]
            style_name = paragraph.style.name or ""
            style_size = paragraph.style.font.size
            prominent = bool(runs) and (
                all(
                    run.bold or (run.bold is None and paragraph.style.font.bold)
                    for run in runs
                )
                or all(
                    (
                        run.font.size.pt
                        if run.font.size
                        else style_size.pt
                        if style_size
                        else baseline
                    )
                    >= baseline + 1.5
                    for run in runs
                )
            )
            for raw_line in text.splitlines() or [""]:
                lines.append(
                    ExtractionLine(
                        text=raw_line,
                        page=0,
                        prominent=prominent,
                        heading=style_name.casefold().startswith("heading"),
                        table=False,
                    )
                )
            lines.append(
                ExtractionLine(
                    text="", page=0, prominent=False, heading=False, table=False
                )
            )
        elif child.tag.endswith("}tbl"):
            table = Table(child, document)
            text = "\n".join(
                " | ".join(cell.text for cell in row.cells)
                for row in table.rows
            ).strip()
            lines.append(
                ExtractionLine(
                    text=text,
                    page=0,
                    prominent=False,
                    heading=False,
                    table=True,
                )
            )
        else:
            continue
        total += len(text)
        if total > MAX_TEXT:
            raise ValueError(
                "This document contains too much text. Upload a shorter paper or excerpt."
            )
    return lines


def extract_uploaded_paper(filename: str, data: bytes) -> Paper:
    suffix = Path(filename).suffix.lower()
    if suffix not in {".pdf", ".docx"}:
        raise ValueError(
            "Choose a PDF or DOCX file. Older .doc files are not supported."
        )
    if not data:
        raise ValueError("This file is empty. Please choose another copy.")
    if len(data) > MAX_BYTES:
        raise ValueError(
            "This file is larger than 10 MB. Export a smaller PDF or DOCX and try again."
        )
    passages: list[Passage] = []
    page_count = 0
    document_warnings: list[ExtractionWarning] = []
    if suffix == ".pdf":
        if b"%PDF-" not in data[:1024]:
            raise ValueError(
                "This file does not appear to be a PDF. Export it again from the original document."
            )
        try:
            reader = PdfReader(BytesIO(data))
        except Exception as e:
            # A truncated or structurally broken file raises a library-specific
            # error. Convert it so every unreadable upload reports the same way,
            # instead of surfacing an exception type the interface cannot read.
            logging.warning("Could not parse PDF structure: %s", e)
            raise ValueError(
                "This PDF could not be opened. It may be truncated or "
                "damaged. Export a fresh PDF and try again."
            ) from e
        if reader.is_encrypted:
            raise ValueError(
                "This PDF is password-protected. Upload an unlocked copy."
            )
        page_count = len(reader.pages)
        if page_count > MAX_PAGES:
            raise ValueError("Please upload a paper of 120 pages or fewer.")
        total = 0
        page_texts: list[str] = []
        for page in reader.pages:
            text = (page.extract_text() or "").strip()
            total += len(text)
            if total > MAX_TEXT:
                raise ValueError(
                    "This document contains too much text. Upload a shorter paper or excerpt."
                )
            page_texts.append(text)

        scanned_page_indexes = [
            index
            for index, text in enumerate(page_texts)
            if not _has_meaningful_text(text)
        ]
        ocr_pages_read = 0
        ocr_incomplete = len(scanned_page_indexes) > MAX_OCR_PAGES
        render_document = None
        if scanned_page_indexes:
            try:
                render_document = pymupdf.open(stream=data, filetype="pdf")
            except Exception as e:
                log_failure("Opening a PDF for OCR", e)
                ocr_incomplete = True

        ocr_started = time.monotonic()
        for index in scanned_page_indexes[:MAX_OCR_PAGES]:
            if render_document is None:
                ocr_incomplete = True
                break
            if time.monotonic() - ocr_started >= MAX_OCR_SECONDS:
                ocr_incomplete = True
                break
            try:
                page = render_document.load_page(index)
                pixmap = page.get_pixmap(
                    matrix=pymupdf.Matrix(2.5, 2.5), alpha=False
                )
                with Image.open(BytesIO(pixmap.tobytes("png"))) as image:
                    ocr_text = pytesseract.image_to_string(
                        image,
                        lang="eng",
                        config="--psm 3",
                        timeout=OCR_TIMEOUT_SECONDS,
                    ).strip()
                if _has_meaningful_text(ocr_text):
                    total += len(ocr_text) - len(page_texts[index])
                    page_texts[index] = ocr_text
                    ocr_pages_read += 1
                else:
                    ocr_incomplete = True
            except Exception as e:
                log_failure("OCR of a scanned page", e)
                ocr_incomplete = True
            if total > MAX_TEXT:
                if render_document is not None:
                    render_document.close()
                raise ValueError(
                    "This document contains too much text. Upload a shorter paper or excerpt."
                )

        if render_document is not None:
            render_document.close()
        hints = _pdf_prominent_lines(data)
        lines: list[ExtractionLine] = []
        for index, text in enumerate(page_texts):
            for raw_line in text.splitlines():
                lines.append(
                    ExtractionLine(
                        text=raw_line,
                        page=index + 1,
                        prominent=index < len(hints)
                        and " ".join(raw_line.split()) in hints[index],
                        heading=False,
                        table=False,
                    )
                )
        passages, references, bibliography_detected = _partition_lines(
            lines, "Document text"
        )

        note = "PDF sections and reference entries detected from text and heading cues; unusual layouts, equations, and tables may not be preserved. Page numbers match the file. Extracted references are as supplied, not verified."
        if ocr_pages_read and ocr_incomplete:
            note = f"{note} English OCR recovered text from {ocr_pages_read} scanned page(s), but some pages could not be read or were skipped because of processing limits. Try a clearer scan for the remaining pages."
            document_warnings.append(
                warning(
                    "ocr_partial",
                    "Scanned pages",
                    "warning",
                    "Text was recovered from some scanned pages only. The "
                    "remaining pages were skipped or could not be read.",
                    "Upload a clearer scan to recover the rest of this paper.",
                )
            )
        elif ocr_pages_read:
            note = f"{note} English OCR was used on {ocr_pages_read} scanned page(s)."
        elif scanned_page_indexes:
            note = f"{note} Automatic English OCR could not recover readable text from the scanned pages. Try a clearer scan or upload a searchable PDF."
            document_warnings.append(
                warning(
                    "ocr_failed",
                    "Scanned pages",
                    "warning",
                    "OCR could not recover readable text from the scanned "
                    "pages in this document.",
                    "Upload a clearer or higher-resolution scan.",
                )
            )
        if bibliography_detected and not references:
            document_warnings.append(
                warning(
                    "bibliography_entries_not_separated",
                    "References",
                    "warning",
                    "A bibliography heading was found, but entries could not be "
                    "separated into individual references.",
                    "Check the reference layout in the source document and add "
                    "clear paragraph breaks between entries.",
                )
            )
    else:
        try:
            with ZipFile(BytesIO(data)) as archive:
                if (
                    sum(info.file_size for info in archive.infolist())
                    > 40 * 1024 * 1024
                ):
                    raise ValueError(
                        "This DOCX expands beyond the safe processing limit. Upload a simpler copy."
                    )
        except BadZipFile as e:
            raise ValueError(
                "This file is not a readable DOCX document. If it opens in "
                "Word, export a fresh copy as .docx and try again."
            ) from e
        document = Document(BytesIO(data))
        passages, references, bibliography_detected = _partition_lines(
            _docx_lines(document), "Document text"
        )
        note = "DOCX sections detected from heading styles and standalone heading cues; paragraphs and tables retain document order. Page numbers are unavailable. Footnotes and text boxes may be omitted. Extracted references are as supplied, not verified."
        document_warnings.append(
            warning(
                "docx_page_numbers_unavailable",
                "Whole document",
                "info",
                "DOCX files do not carry reliable page numbers, so figure and "
                "section locations are reported without a page.",
                "Use the section heading to find a location in the source file.",
            )
        )
        if bibliography_detected and not references:
            document_warnings.append(
                warning(
                    "bibliography_entries_not_separated",
                    "References",
                    "warning",
                    "A bibliography heading was found, but entries could not be "
                    "separated into individual references.",
                    "Check the reference layout in the source document and add "
                    "clear paragraph breaks between entries.",
                )
            )
    if not passages or not any(
        any(c.isalnum() for c in p["text"]) for p in passages
    ):
        raise ValueError(
            "No readable text was found. Paperproof tries English OCR automatically for image-only PDFs; upload a clearer, higher-resolution scan or a searchable PDF if the text still cannot be read."
        )
    paper_id = f"upload-{uuid4().hex}"
    extraction_warnings = list(document_warnings)
    images: list[PaperImage] = []
    try:
        if suffix == ".pdf":
            images, image_warnings = extract_pdf_images(
                paper_id, data, passages
            )
        else:
            images, image_warnings = extract_docx_images(
                paper_id, document, passages
            )
    except Exception as e:
        log_failure("Figure extraction", e)
        images = []
        image_warnings = [
            warning(
                "image_extraction_failed",
                "Figures and images",
                "warning",
                "Images could not be read from this document. Text analysis is unaffected.",
                "Open the source document to view its figures.",
            )
        ]
    extraction_warnings.extend(image_warnings)
    classification = classify_research_paper(
        passages,
        references,
        images=images,
        bibliography_detected=bibliography_detected,
    )
    if not images:
        extraction_warnings.append(
            warning(
                "no_images_found",
                "Figures and images",
                "info",
                "No embedded figures were found in this document.",
                "Figures drawn as vector shapes, or a scanned paper whose pages "
                "are a single image, may not appear here.",
            )
        )
    return Paper(
        id=paper_id,
        title=Path(filename).stem,
        authors="Author details not extracted",
        year="",
        topic="Your document",
        source="upload",
        filename=Path(filename).name,
        page_count=page_count,
        word_count=sum(len(p["text"].split()) for p in passages),
        note=note,
        passages=passages,
        references=references,
        images=images,
        extraction_warnings=extraction_warnings,
        research_classification=classification,
        bibliography_parsed=True,
        bibliography_detected=bibliography_detected,
    )
