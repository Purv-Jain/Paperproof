"""Image, caption, and extraction-warning handling for uploaded papers.

Images are first-class objects kept separate from the text passages. Nothing
here calls a model or a remote service: figure understanding is limited to
local OCR, caption text, and nearby paper text, so image-derived claims stay
traceable to text a reader can check.

Generated paths never contain user input. Each paper owns a directory named
after its unguessable paper id, and files are named by a running counter, so
no uploaded filename can influence a path on disk.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import time
from io import BytesIO
from pathlib import Path
from typing import Any, Literal, TypedDict

import pymupdf
import pytesseract
from docx.document import Document as DocxDocument
from docx.oxml.ns import qn
from PIL import Image

# Extraction limits. These bound work per upload so a hostile or unusual
# document cannot stall the workspace.
MAX_IMAGES = 200
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_TOTAL_IMAGE_BYTES = 40 * 1024 * 1024
MAX_IMAGE_OCR_SECONDS = 60.0
MAX_IMAGE_OCR_CHARACTERS = 4000
OCR_TIMEOUT_SECONDS = 12
MIN_IMAGE_DIMENSION = 80
MIN_IMAGE_OCR_PIXELS = 20_000
SURROUNDING_TEXT_LIMIT = 600

# An embedded object that appears on this many or more distinct pages is page
# furniture, not a figure. Publisher templates (for example an IEEE two-column
# layout) split background artwork into strips and composite the same set onto
# every page; showing those tiles as "figures" buries the real ones. A genuine
# figure belongs to the page it is printed on.
MAX_PAGES_PER_FIGURE = 2

Severity = Literal["info", "warning", "error"]


class ExtractionWarning(TypedDict):
    code: str
    location: str
    severity: Severity
    message: str
    recommended_action: str


class PaperImage(TypedDict):
    id: str
    page: int
    order: int
    filename: str
    local_path: str
    mime_type: str
    width: int
    height: int
    caption: str
    surrounding_text: str
    section: str
    image_kind: str
    ocr_text: str
    extraction_status: str
    analysis_status: str
    analysis_summary: str
    analysis_warnings: list[str]


class ResearchClassification(TypedDict):
    """Structural judgement about whether a document looks like research.

    The classifier is implemented in a later phase; the shape is fixed here so
    the paper model does not change again.
    """

    outcome: str
    signals: list[str]
    missing_signals: list[str]
    message: str


# "Figure 1.", "Fig. 2:", "Table 3 –", "Tab. 4", "Figure A1." and similar.
CAPTION_PATTERN = re.compile(
    r"^\s*(?:figure|fig\.?|table|tab\.)\s*"
    r"(?:[A-Z]?\.?\d{1,3}[a-z]?|[IVXivx]{1,4})\s*[.:\)\-–—]?",
    re.IGNORECASE,
)

IMAGE_KIND_BY_CAPTION = (
    ("table_image", re.compile(r"^\s*table\b|^\s*tab\.?\s", re.IGNORECASE)),
    (
        "equation_image",
        re.compile(r"\bequations?\b|\bformula\b", re.IGNORECASE),
    ),
    (
        "chart",
        re.compile(
            r"\b(chart|graph|plot|histogram|scatter|bar chart|line graph)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "diagram",
        re.compile(
            r"\b(diagram|schematic|workflow|flowchart|framework|architecture)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "photograph",
        re.compile(
            r"\b(photograph|photo|image|micrograph|photomicrograph|"
            r"radiograph|stain(?:ed)?|gel|blot)\b",
            re.IGNORECASE,
        ),
    ),
)


def warning(
    code: str,
    location: str,
    severity: Severity,
    message: str,
    recommended_action: str,
) -> ExtractionWarning:
    return ExtractionWarning(
        code=code,
        location=location,
        severity=severity,
        message=message,
        recommended_action=recommended_action,
    )


def media_root() -> Path:
    """Directory that holds session image folders.

    Defaults to Reflex's uploaded-files directory, which the framework already
    serves at /_upload/. Placing images there means no public URL is invented
    for session content: a figure is only reachable through the unguessable
    paper id in its path. Read on every call so deployments and tests can
    redirect it without reimporting this module.
    """
    override = os.getenv("PAPERPROOF_MEDIA_DIR", "").strip()
    if override:
        return Path(override)
    try:
        import reflex as rx

        return rx.get_upload_dir()
    except Exception as e:  # pragma: no cover - reflex is a hard dependency
        logging.warning("Falling back to local media directory: %s", e)
        return Path(".session_media")


UPLOAD_URL_PREFIX = "/_upload"

# The only directory-name shape this module ever creates.
_PAPER_ID = re.compile(r"upload-[0-9a-f]{32}")

# Anything written after this instant belongs to a live tab of this process.
_PROCESS_START = time.time()


def media_dir(paper_id: str) -> Path:
    """Return the session-scoped directory that stores one paper's images."""
    # paper_id is generated internally as "upload-<uuid4 hex>". Reject anything
    # else so this can never be driven by an uploaded filename.
    if not re.fullmatch(r"upload-[0-9a-f]{32}", paper_id):
        raise ValueError("Unexpected paper id for image storage.")
    return media_root() / paper_id


def discard_media(paper_id: str) -> None:
    """Delete the stored images for one paper. Used when an upload is removed."""
    try:
        shutil.rmtree(media_dir(paper_id))
    except FileNotFoundError:
        # The paper stored no figures, or it was already removed.
        return
    except (ValueError, OSError) as e:
        logging.warning("Could not remove session media for %s: %s", paper_id, e)


def prune_media(active_ids: set[str]) -> list[str]:
    """Delete stored figures written before this process started.

    Reflex keeps session state in memory, so figures written by a previous
    process have no paper to belong to: a restart, a redeploy, or a container
    replacement orphans them. They are swept here so "session only" stays true
    on disk rather than being true only in the running process.

    Age is the criterion, deliberately, not membership in ``active_ids``.
    Reflex runs one state per browser tab, so a second tab knows nothing about
    the first tab's papers. A sweep driven by "not in my paper list" would let
    the second tab delete figures the first is still displaying. Because state
    is memory-only, no live tab can hold an id for a paper it never loaded, so
    anything written before startup is provably orphaned. ``active_ids`` is kept
    as a belt-and-braces exclusion: a listed id is never swept.

    Anything written by this process belongs to some live tab and is removed
    only by an explicit :func:`discard_media` call from the tab that owns it.

    Only directories this module created are considered. A path that does not
    match the expected id shape is left untouched rather than deleted.
    """
    root = media_root()
    try:
        entries = list(root.iterdir())
    except FileNotFoundError:
        return []
    except OSError as e:
        logging.warning("Could not read the session media directory: %s", e)
        return []
    keep = {
        identifier for identifier in active_ids if _PAPER_ID.fullmatch(identifier)
    }
    removed: list[str] = []
    for entry in entries:
        if not entry.is_dir() or entry.name in keep:
            continue
        if not _PAPER_ID.fullmatch(entry.name):
            # Never delete a directory this module did not create.
            continue
        try:
            if entry.stat().st_mtime >= _PROCESS_START:
                # Written by this process: some live tab still owns it.
                continue
        except OSError as e:
            logging.warning("Could not stat session media %s: %s", entry, e)
            continue
        try:
            shutil.rmtree(entry)
            removed.append(entry.name)
        except OSError as e:
            logging.warning("Could not remove stale session media %s: %s", entry, e)
    if removed:
        logging.info("Removed figures for %s closed session paper(s).", len(removed))
    return removed


def session_media_bytes() -> int:
    """Total size of everything stored for the current session's figures."""
    root = media_root()
    total = 0
    try:
        entries = list(root.iterdir())
    except OSError:
        return 0
    for entry in entries:
        if not entry.is_dir() or not _PAPER_ID.fullmatch(entry.name):
            continue
        for path in entry.rglob("*"):
            try:
                if path.is_file():
                    total += path.stat().st_size
            except OSError:
                continue
    return total


def _caption_for(text: str) -> str:
    return " ".join(text.split())[:600]


def _is_caption(text: str) -> bool:
    return bool(CAPTION_PATTERN.match(text.strip()))


def _classify_image(caption: str, ocr_text: str, colour_count: int) -> str:
    """Infer an image kind from caption text and cheap pixel statistics.

    This is a heuristic, never a document assertion. Callers record that fact.
    """
    probe = f"{caption} {ocr_text}"[:400]
    for kind, pattern in IMAGE_KIND_BY_CAPTION:
        if pattern.search(probe):
            return kind
    # A labelled caption that names no specific kind is still a figure.
    if _is_caption(caption):
        return "figure"
    # Without a caption, a colourful image with almost no readable text is more
    # likely a photograph than a labelled plot.
    if colour_count >= 64 and len(ocr_text) < 40:
        return "photograph"
    return "unknown"


def _colour_count(png_bytes: bytes) -> int:
    try:
        with Image.open(BytesIO(png_bytes)) as image:
            return len(image.convert("RGB").getcolors(maxcolors=256) or [])
    except Exception as e:
        logging.warning("Could not measure image colours: %s", e)
        return 0


class OcrAvailability(TypedDict):
    """Whether local Tesseract OCR can actually run on this machine."""

    available: bool
    version: str
    detail: str


# Probed once per process. `ocr_availability` is read from a computed var, which
# Reflex re-evaluates on every render, so an uncached probe would spawn a
# Tesseract subprocess per frame.
_ocr_probe: OcrAvailability | None = None


def ocr_availability(force: bool = False) -> OcrAvailability:
    """Report whether figure OCR will work, before any paper is opened.

    OCR is the one extraction step that fails quietly. Without Tesseract the
    paper still opens, captions and surrounding text still work, and the only
    evidence is a log line nobody reads, so figure text simply disappears and
    the reader has no way to know why a figure looks empty. Probing up front
    lets the upload panel say so before a document is ever parsed.

    The English language pack is checked as well as the binary: Tesseract
    installs successfully without `eng` on some systems, and every OCR call
    here asks for `lang="eng"`, so a missing pack is a silent loss in exactly
    the same way.
    """
    global _ocr_probe
    if _ocr_probe is not None and not force:
        return _ocr_probe
    result: OcrAvailability
    try:
        version = str(pytesseract.get_tesseract_version())
    except Exception as e:
        # Logged by operation, not by message: the failure can include a path
        # from the host, which must not reach a handler.
        logging.warning("Tesseract OCR probe failed: %s", type(e).__name__)
        result = OcrAvailability(
            available=False,
            version="",
            detail=(
                "Local OCR is unavailable, so figures will be read from their "
                "captions and nearby paper text only. Install Tesseract OCR "
                "with the English language pack to read text inside figures."
            ),
        )
    else:
        try:
            languages = pytesseract.get_languages(config="")
        except Exception as e:
            logging.warning(
                "Tesseract language probe failed: %s", type(e).__name__
            )
            languages = []
        if "eng" not in languages:
            result = OcrAvailability(
                available=False,
                version=version,
                detail=(
                    f"Tesseract {version} is installed but its English "
                    "language pack is missing, so figures will be read from "
                    "their captions and nearby paper text only."
                ),
            )
        else:
            result = OcrAvailability(
                available=True,
                version=version,
                detail=f"Local OCR is available (Tesseract {version}).",
            )
    _ocr_probe = result
    return result


def _ocr_image(path: Path) -> str:
    try:
        with Image.open(path) as image:
            if image.width * image.height < MIN_IMAGE_OCR_PIXELS:
                return ""
            return pytesseract.image_to_string(
                image, lang="eng", config="--psm 6", timeout=OCR_TIMEOUT_SECONDS
            ).strip()[:MAX_IMAGE_OCR_CHARACTERS]
    except Exception as e:
        logging.warning("Could not OCR extracted image: %s", e)
        return ""


def _build_image(
    paper_id: str,
    order: int,
    page: int,
    blob: bytes,
    extension: str,
    mime_type: str,
    caption: str,
    surrounding_text: str,
    section: str,
    status: str,
) -> PaperImage:
    identifier = f"img-{order + 1:02d}"
    directory = media_dir(paper_id)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{identifier}.{extension}"
    path.write_bytes(blob)
    width = height = 0
    try:
        with Image.open(path) as image:
            width, height = image.size
    except Exception as e:
        logging.warning("Could not read extracted image size: %s", e)
    return PaperImage(
        id=identifier,
        page=page,
        order=order,
        filename=path.name,
        local_path=str(path),
        mime_type=mime_type,
        width=width,
        height=height,
        caption=caption,
        surrounding_text=surrounding_text,
        section=section,
        image_kind=_classify_image(caption, "", _colour_count(blob)),
        ocr_text="",
        extraction_status=status,
        analysis_status="not_run",
        analysis_summary="",
        analysis_warnings=[],
    )


def _run_ocr(images: list[PaperImage], warnings: list[ExtractionWarning]) -> None:
    """OCR extracted images under a shared time budget."""
    if not images:
        return
    started = time.monotonic()
    read = 0
    for image in images:
        if time.monotonic() - started >= MAX_IMAGE_OCR_SECONDS:
            warnings.append(
                warning(
                    "image_ocr_limit",
                    "Figures and images",
                    "info",
                    "Text could not be read from every extracted image because "
                    "the OCR time limit was reached.",
                    "Open the figure in the source document to read its labels.",
                )
            )
            break
        text = _ocr_image(Path(image["local_path"]))
        if text:
            image["ocr_text"] = text
            image["image_kind"] = _classify_image(image["caption"], text, 0)
            read += 1
    if read:
        logging.info("OCR recovered text from %s extracted image(s).", read)


def _section_for_page(sections_by_page: dict[int, str], page: int) -> str:
    """Best-effort section name for an image, from the passage stream."""
    if page in sections_by_page:
        return sections_by_page[page]
    for candidate in range(page - 1, 0, -1):
        if candidate in sections_by_page:
            return sections_by_page[candidate]
    return ""


def _sections_by_page(passages: list[dict[str, Any]]) -> dict[int, str]:
    sections: dict[int, str] = {}
    for passage in passages:
        page = passage["page"]
        if page > 0 and passage["section"]:
            sections[page] = passage["section"]
    return sections


def extract_pdf_images(
    paper_id: str,
    data: bytes,
    passages: list[dict[str, Any]],
) -> tuple[list[PaperImage], list[ExtractionWarning]]:
    """Extract embedded images from a PDF and associate nearby captions."""
    images: list[PaperImage] = []
    warnings: list[ExtractionWarning] = []
    sections = _sections_by_page(passages)
    seen_xrefs: set[int] = set()
    total_bytes = 0
    truncated = False
    recurring: set[int] = set()
    try:
        document = pymupdf.open(stream=data, filetype="pdf")
    except Exception as e:
        logging.warning("Could not open PDF for image extraction: %s", e)
        return [], [
            warning(
                "image_extraction_failed",
                "Figures and images",
                "warning",
                "Images could not be read from this PDF.",
                "Text analysis still works. Open the PDF directly to view figures.",
            )
        ]
    # Counted before extraction so a background strip composited onto every
    # page can be recognised and skipped rather than presented as a figure.
    page_occurrences: dict[int, int] = {}
    for page in document:
        for info in page.get_images(full=True):
            xref = info[0]
            page_occurrences[xref] = page_occurrences.get(xref, 0) + 1
    recurring = {
        xref for xref, count in page_occurrences.items()
        if count > MAX_PAGES_PER_FIGURE
    }
    try:
        for page_number, page in enumerate(document, start=1):
            lines = _page_text_lines(page)
            for info in page.get_images(full=True):
                if len(images) >= MAX_IMAGES or total_bytes >= MAX_TOTAL_IMAGE_BYTES:
                    truncated = True
                    break
                xref = info[0]
                if xref in recurring:
                    continue
                if xref in seen_xrefs:
                    # The same embedded object reused on another page is one
                    # figure, not two.
                    continue
                seen_xrefs.add(xref)
                try:
                    pixmap = pymupdf.Pixmap(document, xref)
                except Exception as e:
                    logging.warning("Skipping unreadable image xref %s: %s", xref, e)
                    continue
                if pixmap.width < MIN_IMAGE_DIMENSION or pixmap.height < MIN_IMAGE_DIMENSION:
                    # Rules, bullet glyphs, and logo fragments are not figures.
                    continue
                try:
                    if pixmap.colorspace and pixmap.colorspace.n >= 4:
                        pixmap = pymupdf.Pixmap(pymupdf.csRGB, pixmap)
                    png = pixmap.tobytes("png")
                except Exception as e:
                    logging.warning("Skipping unconvertible image xref %s: %s", xref, e)
                    continue
                finally:
                    pixmap = None
                if len(png) > MAX_IMAGE_BYTES:
                    warnings.append(
                        warning(
                            "image_too_large",
                            f"page {page_number}",
                            "info",
                            "One figure was too large to store and was skipped.",
                            "Open it in the source PDF.",
                        )
                    )
                    continue
                rect = _image_rect(page, xref)
                caption = _nearest_caption(lines, rect)
                surrounding = _surrounding_text(lines, rect, caption)
                total_bytes += len(png)
                images.append(
                    _build_image(
                        paper_id=paper_id,
                        order=len(images),
                        page=page_number,
                        blob=png,
                        extension="png",
                        mime_type="image/png",
                        caption=caption,
                        surrounding_text=surrounding,
                        section=_section_for_image(
                            lines,
                            rect,
                            _section_for_page(sections, page_number),
                        ),
                        status="extracted",
                    )
                )
            if truncated:
                break
    finally:
        document.close()
    if recurring:
        warnings.append(
            warning(
                "page_furniture_skipped",
                "Figures and images",
                "info",
                (
                    f"{len(recurring)} repeating background or template images "
                    "were left out because they are drawn on more than "
                    f"{MAX_PAGES_PER_FIGURE} pages."
                ),
                "Those are page artwork rather than figures, and including them "
                "would push the real figures out of view.",
            )
        )
    if truncated:
        warnings.append(
            warning(
                "image_limit_reached",
                "Figures and images",
                "info",
                f"Only the first {MAX_IMAGES} figures were extracted.",
                "Remaining figures are still readable in the source document.",
            )
        )
    if images:
        warnings.append(
            warning(
                "image_kind_inferred",
                "Figures and images",
                "info",
                "Figure types were inferred from caption text and pixel "
                "statistics. The document does not label them.",
                "Treat the figure type as a suggestion.",
            )
        )
    _run_ocr(images, warnings)
    return images, warnings


def _page_text_lines(page) -> list[tuple[float, str, bool]]:
    """Return (vertical position, text, looks_like_heading) for each line."""
    lines: list[tuple[float, str, bool]] = []
    try:
        blocks = page.get_text("dict").get("blocks", [])
    except Exception as e:
        logging.warning("Could not read page text for captions: %s", e)
        return lines
    sizes: dict[float, int] = {}
    records: list[tuple[float, str, float, bool]] = []
    for block in blocks:
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            text = "".join(span.get("text", "") for span in spans).strip()
            if not text:
                continue
            size = max(
                (float(span.get("size", 0)) for span in spans), default=0.0
            )
            bold = bool(spans) and all(
                int(span.get("flags", 0)) & 16 for span in spans
            )
            records.append((line["bbox"][1], text, size, bold))
            sizes[round(size, 1)] = sizes.get(round(size, 1), 0) + len(text)
    baseline = max(sizes.items(), key=lambda item: item[1])[0] if sizes else 12.0
    for position, text, size, bold in records:
        heading = bold or size >= baseline + 1.5
        lines.append((position, text, heading))
    lines.sort(key=lambda item: item[0])
    return lines


def _heading_label(text: str) -> str:
    """Strip numbering and trailing punctuation from a heading line."""
    cleaned = re.sub(r"^\s*\d+(?:\.\d+)*[.)]?\s+", "", text.strip())
    return " ".join(cleaned.rstrip(":").split())


def _section_for_image(
    lines: list[tuple[float, str, bool]], rect, fallback: str
) -> str:
    """Section of the nearest heading above the figure on the same page."""
    if rect is None:
        return fallback
    centre = (rect.y0 + rect.y1) / 2
    above = [line for line in lines if line[2] and not _is_caption(line[1]) and line[0] <= centre]
    if not above:
        return fallback
    label = _heading_label(above[-1][1])
    return label or fallback


def _image_rect(page, xref: int):
    try:
        rects = page.get_image_rects(xref)
    except Exception:
        return None
    return rects[0] if rects else None


def _nearest_caption(lines: list[tuple[float, str, bool]], rect) -> str:
    if rect is None:
        return ""
    captions = [item for item in lines if _is_caption(item[1])]
    if not captions:
        return ""
    centre = (rect.y0 + rect.y1) / 2
    # A caption normally sits just above or just below its figure.
    best = min(captions, key=lambda item: abs(item[0] - centre))
    if abs(best[0] - centre) > 400:
        return ""
    return _caption_for(best[1])


def _surrounding_text(
    lines: list[tuple[float, str, bool]], rect, caption: str
) -> str:
    if rect is None:
        return ""
    centre = (rect.y0 + rect.y1) / 2
    nearby = [
        item
        for item in lines
        if not _is_caption(item[1])
        and abs(item[0] - centre) <= 200
        and _caption_for(item[1]) != caption
    ]
    if not nearby:
        return ""
    return " ".join(text for _, text, _ in nearby)[:SURROUNDING_TEXT_LIMIT]


def extract_docx_images(
    paper_id: str,
    document: DocxDocument,
    passages: list[dict[str, Any]],
) -> tuple[list[PaperImage], list[ExtractionWarning]]:
    """Extract embedded images from a DOCX in document order."""
    images: list[PaperImage] = []
    warnings: list[ExtractionWarning] = []
    total_bytes = 0
    truncated = False
    section = ""
    paragraphs = list(document.element.body.iterchildren())
    for index, child in enumerate(paragraphs):
        if not child.tag.endswith("}p"):
            continue
        text = "".join(
            node.text or ""
            for node in child.iter(qn("w:t"))
        ).strip()
        if text and not _is_caption(text):
            paragraph = _as_paragraph(document, child)
            style = (paragraph.style.name or "") if paragraph is not None else ""
            if style.casefold().startswith("heading"):
                section = " ".join(text.split())
        blips = list(child.iter(qn("a:blip")))
        if not blips:
            continue
        if len(images) >= MAX_IMAGES or total_bytes >= MAX_TOTAL_IMAGE_BYTES:
            truncated = True
            break
        caption = _docx_caption(paragraphs, index)
        surrounding = _docx_surrounding(paragraphs, index, caption)
        for blip in blips:
            if len(images) >= MAX_IMAGES or total_bytes >= MAX_TOTAL_IMAGE_BYTES:
                truncated = True
                break
            blob, extension, mime_type = _docx_blob(document, blip)
            if blob is None:
                continue
            if len(blob) > MAX_IMAGE_BYTES:
                continue
            total_bytes += len(blob)
            images.append(
                _build_image(
                    paper_id=paper_id,
                    order=len(images),
                    page=0,
                    blob=blob,
                    extension=extension,
                    mime_type=mime_type,
                    caption=caption,
                    surrounding_text=surrounding,
                    section=section,
                    status="extracted",
                )
            )
    if truncated:
        warnings.append(
            warning(
                "image_limit_reached",
                "Figures and images",
                "info",
                f"Only the first {MAX_IMAGES} figures were extracted.",
                "Remaining figures are still readable in the source document.",
            )
        )
    if images:
        warnings.append(
            warning(
                "image_kind_inferred",
                "Figures and images",
                "info",
                "Figure types were inferred from caption text and pixel "
                "statistics. The document does not label them.",
                "Treat the figure type as a suggestion.",
            )
        )
    _run_ocr(images, warnings)
    return images, warnings


def _as_paragraph(document: DocxDocument, element):
    from docx.text.paragraph import Paragraph

    try:
        return Paragraph(element, document)
    except Exception:
        return None


def _docx_text(child) -> str:
    return "".join(node.text or "" for node in child.iter(qn("w:t"))).strip()


def _docx_caption(paragraphs: list[Any], index: int) -> str:
    """A DOCX caption is the nearest caption paragraph before or after."""
    for offset in (1, 2, 3):
        for candidate in (
            index - offset,
            index + offset,
        ):
            if 0 <= candidate < len(paragraphs):
                text = _docx_text(paragraphs[candidate]).strip()
                if _is_caption(text):
                    return _caption_for(text)
    return ""


def _docx_surrounding(
    paragraphs: list[Any], index: int, caption: str
) -> str:
    collected: list[str] = []
    for offset in (1, 2):
        for candidate in (index - offset, index + offset):
            if 0 <= candidate < len(paragraphs):
                text = _docx_text(paragraphs[candidate]).strip()
                if not text or _is_caption(text) or text == caption:
                    continue
                collected.append(" ".join(text.split()))
    if not collected:
        return ""
    return " ".join(collected)[:SURROUNDING_TEXT_LIMIT]


def _docx_blob(
    document: DocxDocument, blip
) -> tuple[bytes | None, str, str]:
    try:
        relationship_id = blip.get(qn("r:embed"))
    except Exception:
        return None, "", ""
    if not relationship_id:
        return None, "", ""
    try:
        part = document.part.related_parts[relationship_id]
        blob = part.blob
    except Exception as e:
        logging.warning("Could not read DOCX image part: %s", e)
        return None, "", ""
    content_type = getattr(part, "content_type", "") or ""
    extension = {
        "image/png": "png",
        "image/jpeg": "jpeg",
        "image/gif": "gif",
        "image/bmp": "bmp",
        "image/tiff": "tiff",
    }.get(content_type)
    if extension is None:
        extension = Path(str(content_type).split("/")[-1]).name or "png"
        extension = re.sub(r"[^a-z0-9]", "", extension.lower()) or "png"
    return blob, extension, content_type or f"image/{extension}"


__all__ = [
    "CAPTION_PATTERN",
    "ExtractionWarning",
    "OcrAvailability",
    "PaperImage",
    "ResearchClassification",
    "UPLOAD_URL_PREFIX",
    "discard_media",
    "extract_docx_images",
    "extract_pdf_images",
    "media_dir",
    "media_root",
    "prune_media",
    "session_media_bytes",
    "warning",
]