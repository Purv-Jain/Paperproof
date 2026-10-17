"""End-to-end tests for the whole paper workflow.

These exercise the real pipeline in the order the application runs it:
validate and classify, extract text plus figures, route a question, build the
model context, call the model at the HTTP boundary, ground the answer, and run
the audit. Only the network is replaced, so a break anywhere between two steps
fails a test rather than passing silently.

Flows follow the integration list in the completion spec, section 16.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import pymupdf
from docx import Document
from PIL import Image

from app.citation_audit import run_citation_audit
from app.components.workspace import image_src
from app.image_extraction import UPLOAD_URL_PREFIX, discard_media, media_dir
from app.model_config import search_provider
from app.paper_classification import classify_research_paper
from app.states.paper_data import (
    Passage,
    Paper,
    Reference,
    extract_uploaded_paper,
)
from app.states.workspace_state import (
    OpenRouterError,
    SearchUnavailable,
    _build_grounded_answer,
    _call_openrouter,
    _call_search,
    _retrieve_passages,
    build_answer_context,
    paper_extraction_warnings,
    paper_images,
    route_question,
    section_count,
)

UNSUPPORTED = (
    "This paper does not establish an answer to that question in the available text."
)


# --------------------------------------------------------------------------
# Fake network layer
# --------------------------------------------------------------------------


class FakeResponse:
    """Minimal stand-in for a requests.Response."""

    def __init__(self, status_code: int, payload: object | None = None) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload) if payload is not None else ""
        self.content = self.text.encode("utf-8")

    def json(self) -> object:
        if self._payload is None:
            raise ValueError("no json body")
        return self._payload


def model_reply(payload: dict[str, object]) -> FakeResponse:
    """A successful OpenRouter chat completion carrying an answer contract."""
    return FakeResponse(
        200,
        {
            "choices": [
                {"message": {"content": json.dumps(payload)}}
            ]
        },
    )


def answer_payload(
    answer: str,
    evidence_ids: list[str],
    *,
    confidence: str = "high",
    limitations: list[str] | None = None,
    unsupported_parts: list[str] | None = None,
) -> dict[str, object]:
    return {
        "answer": answer,
        "evidence_ids": evidence_ids,
        "confidence": confidence,
        "limitations": limitations or [],
        "unsupported_parts": unsupported_parts or [],
    }


class AnswerRecorder:
    """Stands in for the OpenRouter transport and records what was sent.

    `reply` may be a finished FakeResponse, an exception to raise, or a bare
    answer payload, which is wrapped into a successful completion.
    """

    def __init__(self, reply: object) -> None:
        if isinstance(reply, dict):
            reply = model_reply(reply)
        self.reply = reply
        self.requests: list[dict] = []

    def __call__(self, url: str, **kwargs: object) -> FakeResponse:
        self.requests.append({"url": url, **kwargs})
        if isinstance(self.reply, Exception):
            raise self.reply
        if callable(self.reply):
            return self.reply(kwargs)
        return self.reply


# --------------------------------------------------------------------------
# Document fixtures
# --------------------------------------------------------------------------


def png_bytes(
    size: tuple[int, int] = (240, 160),
    colour: tuple[int, int, int] = (210, 60, 40),
) -> bytes:
    """A figure-sized image. Anything under MIN_IMAGE_DIMENSION is discarded
    by design as a glyph or logo fragment, so test figures must be larger."""
    stream = BytesIO()
    Image.new("RGB", size, colour).save(stream, format="PNG")
    return stream.getvalue()


def text_pdf() -> bytes:
    """A normal text PDF with a body, an abstract, and a reference list."""
    with pymupdf.open() as document:
        first = document.new_page()
        first.insert_textbox(
            pymupdf.Rect(50, 50, 545, 760),
            "Attention and Retention\n"
            "Abstract\n"
            "Ninety undergraduates completed a reading task in a controlled "
            "laboratory study. The spaced condition recalled more items than "
            "the massed condition within the same total study time.\n"
            "Methods\n"
            "Participants were assigned to spaced or massed schedules by a "
            "randomized procedure and completed three sessions in the same "
            "week.\n"
            "References\n"
            "Lee, A. (2021). Learning through explanation. Journal of Learning, "
            "12(2), 20-31.",
            fontsize=11,
        )
        second = document.new_page()
        second.insert_textbox(
            pymupdf.Rect(50, 50, 545, 760),
            "Results\n"
            "Recall accuracy was higher in the spaced condition, and the gap "
            "widened across the three sessions.",
            fontsize=11,
        )
        return document.tobytes()


def pdf_with_figures() -> bytes:
    """A PDF whose pages carry embedded figures with captions below them."""
    figure = png_bytes()
    with pymupdf.open() as document:
        page = document.new_page()
        page.insert_textbox(
            pymupdf.Rect(50, 50, 545, 120),
            "Figure Analysis",
            fontsize=13,
        )
        page.insert_image(pymupdf.Rect(60, 140, 260, 300), stream=figure)
        page.insert_textbox(
            pymupdf.Rect(60, 310, 545, 380),
            "Figure 1. Recall accuracy by condition and session.",
            fontsize=10,
        )
        page.insert_image(pymupdf.Rect(60, 400, 260, 540), stream=figure)
        page.insert_textbox(
            pymupdf.Rect(60, 550, 545, 640),
            "Figure 2. Response time distribution across conditions.",
            fontsize=10,
        )
        return document.tobytes()


def scanned_pdf() -> bytes:
    """A mixed PDF: a readable text page, then an image-only scanned page.

    OCR has to run on the second page, and both pages must still yield figures.
    """
    page_image = Image.new("RGB", (900, 1200), (250, 250, 248))
    stream = BytesIO()
    page_image.save(stream, format="PNG")
    with pymupdf.open() as document:
        text_page = document.new_page()
        text_page.insert_textbox(
            pymupdf.Rect(50, 50, 545, 760),
            "Scanned Study\n"
            "Abstract\n"
            "Participants completed three sessions under a spaced schedule "
            "and recalled more items than a massed comparison group.\n"
            "Methods\n"
            "All participants attended the same laboratory sessions.",
            fontsize=11,
        )
        scanned_page = document.new_page(width=612, height=816)
        scanned_page.insert_image(
            pymupdf.Rect(0, 0, 612, 816), stream=stream.getvalue()
        )
        return document.tobytes()


def rich_docx() -> bytes:
    """A DOCX with headings, a table, and two embedded images."""
    document = Document()
    document.add_heading("Attention and Retention", level=1)
    document.add_heading("Abstract", level=1)
    document.add_paragraph(
        "Ninety undergraduates completed a reading task in a controlled "
        "laboratory study. The spaced condition recalled more items than the "
        "massed condition within the same total study time."
    )
    document.add_heading("Methods", level=1)
    document.add_paragraph(
        "Participants were assigned to spaced or massed schedules by a "
        "randomized procedure and completed three sessions in the same week, "
        "following the schedule design used by Miller (2019)."
    )
    table = document.add_table(rows=3, cols=2)
    table.cell(0, 0).text = "Condition"
    table.cell(0, 1).text = "Recall"
    table.cell(1, 0).text = "Spaced"
    table.cell(1, 1).text = "0.81"
    table.cell(2, 0).text = "Massed"
    table.cell(2, 1).text = "0.64"
    document.add_paragraph("Table 1. Mean recall accuracy by condition.")
    document.add_picture(BytesIO(png_bytes()))
    document.add_paragraph("Figure 1. Recall accuracy by condition.")
    document.add_picture(BytesIO(png_bytes((240, 160), (40, 80, 200))))
    document.add_paragraph("Figure 2. Typical response time by condition.")
    document.add_heading("Results", level=1)
    document.add_paragraph(
        "Recall accuracy was higher in the spaced condition, consistent with "
        "the explanation account given by Lee (2021)."
    )
    document.add_heading("References", level=1)
    document.add_paragraph(
        "Lee, A. (2021). Learning through explanation. Journal of Learning, "
        "12(2), 20-31."
    )
    document.add_paragraph(
        "Miller, B. (2019). Spacing effects in classroom recall. Review of "
        "Educational Psychology, 14(1), 5-22."
    )
    stream = BytesIO()
    document.save(stream)
    return stream.getvalue()


def make_paper(**overrides: object) -> Paper:
    """Build a Paper by hand, for tests that do not need a real file."""
    passages = [
        Passage(
            id="p1",
            section="Abstract",
            page=1,
            text="A spaced schedule improved recall over the same study time.",
        ),
        Passage(
            id="p2",
            section="Methods",
            page=2,
            text=(
                "Participants were assigned to spaced or massed schedules by a "
                "randomized procedure and completed three sessions."
            ),
        ),
    ]
    reference = Reference(
        id="ref-1",
        text="Lee, A. (2021). Learning through explanation. Journal of Learning.",
        section="References",
    )
    paper = Paper(
        id="upload-" + "0" * 32,
        filename="hand.docx",
        title="Hand Built Paper",
        authors="A. Lee",
        year="2021",
        source="upload",
        passages=passages,
        references=[reference],
    )
    paper.update(overrides)  # type: ignore[typeddict-item]
    return paper


# --------------------------------------------------------------------------
# Base class
# --------------------------------------------------------------------------


class FlowTestCase(unittest.TestCase):
    """Points figure storage at a scratch directory for each test."""

    def setUp(self) -> None:
        # C: is full on this machine, so scratch files go wherever D: allows.
        base = os.getenv("PAPERPROOF_TEST_TMP", tempfile.gettempdir())
        self.media_root = Path(tempfile.mkdtemp(prefix="paperproof-media-", dir=base))
        self._previous = os.environ.get("PAPERPROOF_MEDIA_DIR")
        os.environ["PAPERPROOF_MEDIA_DIR"] = str(self.media_root)

    def tearDown(self) -> None:
        if self._previous is None:
            os.environ.pop("PAPERPROOF_MEDIA_DIR", None)
        else:
            os.environ["PAPERPROOF_MEDIA_DIR"] = self._previous
        shutil.rmtree(self.media_root, ignore_errors=True)

    def ask(
        self,
        paper: Paper,
        question: str,
        reply: object,
    ) -> tuple[dict, AnswerRecorder]:
        """Run one question through the real pipeline with a fake model.

        Mirrors `WorkspaceState.save_question`: route, retrieve, build context,
        call the model at the HTTP boundary, then ground the answer.
        """
        recorder = AnswerRecorder(reply)
        intent = route_question(question)
        retrieved = _retrieve_passages(paper["passages"], question)
        context = build_answer_context(
            paper, intent, retrieved, question=question
        )
        payload = None
        if context:
            with patch(
                "app.states.workspace_state.requests.post", recorder
            ):
                os.environ["OPENROUTER_API_KEY"] = "test-key"
                try:
                    payload = _call_openrouter(
                        question, retrieved, context=context
                    )
                finally:
                    os.environ.pop("OPENROUTER_API_KEY", None)
        grounded = _build_grounded_answer(
            question, retrieved, payload, UNSUPPORTED, paper
        )
        return grounded, recorder


# --------------------------------------------------------------------------
# Flow 1-3: upload, validate, classify, extract
# --------------------------------------------------------------------------


class UploadFlowTests(FlowTestCase):
    def test_1_normal_text_pdf_opens_all_three_reader_areas(self) -> None:
        paper = extract_uploaded_paper("attention.pdf", text_pdf())
        outcome = paper["research_classification"]["outcome"]
        self.assertIn(outcome, {"accepted", "accepted_with_warnings"})
        self.assertTrue(paper["passages"])
        self.assertTrue(paper["references"])
        sections = [p["section"] for p in paper["passages"]]
        self.assertTrue(any("Abstract" in s for s in sections))
        self.assertTrue(any("Methods" in s for s in sections))
        self.assertGreater(section_count(paper["passages"]), 0)
        self.assertTrue(paper_images(paper) is not None)

    def test_2_scanned_pdf_yields_figures_or_an_explicit_warning(self) -> None:
        paper = extract_uploaded_paper("scanned.pdf", scanned_pdf())
        images = paper_images(paper)
        warnings = paper_extraction_warnings(paper)
        self.assertTrue(images or warnings)
        if images:
            for image in images:
                self.assertTrue(image["filename"])
                self.assertTrue(
                    image_src(paper["id"], image["filename"]).startswith(
                        f"{UPLOAD_URL_PREFIX}/{paper['id']}/"
                    )
                )
                stored = media_dir(paper["id"]) / image["filename"]
                self.assertTrue(stored.exists(), stored)
        # A scanned page was detected, so the outcome must be stated rather than
        # left for the reader to guess at.
        codes = {warning["code"] for warning in warnings}
        self.assertTrue(
            codes & {"ocr_partial", "ocr_failed"},
            f"a scanned page must produce an OCR notice, got {codes}",
        )

    def test_3_docx_with_headings_tables_and_images(self) -> None:
        paper = extract_uploaded_paper("rich.docx", rich_docx())
        sections = " ".join(p["section"] for p in paper["passages"])
        self.assertIn("Abstract", sections)
        self.assertIn("Methods", sections)
        body = " ".join(p["text"] for p in paper["passages"])
        self.assertIn("Table 1", body)
        images = paper_images(paper)
        self.assertGreaterEqual(len(images), 1)
        self.assertEqual(
            [image["order"] for image in images],
            sorted(image["order"] for image in images),
            "figures must stay in document order",
        )
        self.assertEqual(len(paper["references"]), 2)
        # A DOCX cannot supply page numbers; that must be stated, not faked.
        self.assertIn(
            "docx_page_numbers_unavailable",
            {warning["code"] for warning in paper_extraction_warnings(paper)},
        )

    def test_unrelated_document_is_held_back_not_opened(self) -> None:
        document = Document()
        document.add_heading("Grocery list", level=1)
        for item in ("Bread", "Milk", "Coffee beans", "Dish soap"):
            document.add_paragraph(item)
        stream = BytesIO()
        document.save(stream)
        paper = extract_uploaded_paper("list.docx", stream.getvalue())
        outcome = paper["research_classification"]["outcome"]
        self.assertIn(outcome, {"needs_review", "rejected"})
        if outcome == "needs_review":
            self.assertTrue(paper["research_classification"]["message"])

    def test_unsupported_file_type_is_refused_with_a_readable_reason(self) -> None:
        with self.assertRaises(ValueError) as caught:
            extract_uploaded_paper("notes.txt", b"plain text")
        self.assertIn("PDF or DOCX", str(caught.exception))

    def test_corrupt_pdf_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            extract_uploaded_paper("broken.pdf", b"%PDF-1.4 truncated garbage")


# --------------------------------------------------------------------------
# Flow 4-6: questions
# --------------------------------------------------------------------------


class QuestionFlowTests(FlowTestCase):
    def test_4_methods_question_is_grounded_in_the_body(self) -> None:
        paper = make_paper()
        grounded, recorder = self.ask(
            paper,
            "How was the study designed?",
            answer_payload(
                "Participants were assigned by a randomized procedure and "
                "completed three sessions.",
                ["p2"],
            ),
        )
        self.assertFalse(grounded["unsupported"])
        self.assertTrue(grounded["evidence"])
        self.assertEqual(grounded["evidence"][0]["passage_id"], "p2")
        self.assertEqual(grounded["confidence"], "high")
        sent = json.dumps(recorder.requests[0]["json"])
        # The supplied context is the Methods passage and nothing else: no
        # abstract, and no bibliography data for an ordinary methods question.
        self.assertIn("randomized procedure", sent)
        self.assertNotIn("A spaced schedule", sent)
        self.assertNotIn("Lee, A. (2021)", sent)

    def test_4a_the_model_only_sees_the_passages_it_was_given(self) -> None:
        paper = make_paper()
        grounded, recorder = self.ask(
            paper,
            "What is the main finding?",
            answer_payload("Spacing improved recall.", ["p1"]),
        )
        self.assertFalse(grounded["unsupported"])
        sent = json.dumps(recorder.requests[0]["json"])
        self.assertIn("A spaced schedule", sent)
        self.assertNotIn("randomized procedure", sent)
        # Never the whole document, and never a reference list.
        self.assertNotIn("Hand Built Paper Methods", sent)

    def test_4b_unsupported_question_says_so_instead_of_guessing(self) -> None:
        paper = make_paper(
            passages=[
                Passage(
                    id="p1",
                    section="Abstract",
                    page=1,
                    text="Spacing improved recall.",
                )
            ]
        )
        grounded, _ = self.ask(
            paper,
            "What is the melting point of tungsten?",
            answer_payload(
                "Tungsten melts at 3422 degrees Celsius.",
                [],
                confidence="high",
                limitations=["No melting-point data appears in this paper."],
            ),
        )
        self.assertTrue(grounded["unsupported"])
        self.assertIn("does not establish", grounded["answer"])
        self.assertEqual(grounded["confidence"], "low")

    def test_4c_hallucinated_ids_are_discarded_as_a_contract_violation(self) -> None:
        paper = make_paper()
        grounded, _ = self.ask(
            paper,
            "What does the abstract establish?",
            answer_payload("The paper proves causation.", ["p999"]),
        )
        self.assertTrue(grounded["unsupported"])
        self.assertEqual(grounded["evidence"], [])
        self.assertNotIn("proves causation", grounded["answer"])

    def test_5_figure_question_routes_to_images_and_stays_local(self) -> None:
        paper = extract_uploaded_paper("figures.pdf", pdf_with_figures())
        images = paper_images(paper)
        self.assertTrue(images, "fixture must produce at least one figure")
        intent = route_question("What does Figure 1 show?")
        self.assertTrue(intent["images"])
        context = build_answer_context(paper, intent, [])
        kinds = {item["kind"] for item in context}
        self.assertIn("image", kinds)
        image_block = next(i for i in context if i["kind"] == "image")
        self.assertIn("was not interpreted", image_block["label"])
        # No pixel data may ever leave the machine.
        self.assertNotIn("data:image", image_block["text"])
        self.assertNotIn("base64", image_block["text"].lower())

    def test_6_reference_question_receives_the_bibliography(self) -> None:
        paper = make_paper()
        intent = route_question("Is the Lee reference real?")
        self.assertTrue(intent["references"])
        context = build_answer_context(paper, intent, [], question="Is the Lee reference real?")
        reference_block = next(
            (item for item in context if item["kind"] == "reference"), None
        )
        self.assertIsNotNone(reference_block)
        self.assertEqual(reference_block["id"], "ref-1")
        self.assertIn("Lee, A. (2021)", reference_block["text"])

    def test_6b_ordinary_question_never_receives_the_bibliography(self) -> None:
        paper = make_paper()
        intent = route_question("What is the main finding?")
        self.assertFalse(intent["references"])
        context = build_answer_context(paper, intent, [])
        self.assertNotIn("reference", {item["kind"] for item in context})


# --------------------------------------------------------------------------
# Flow 7-8: audit and correction prompt
# --------------------------------------------------------------------------


class AuditFlowTests(FlowTestCase):
    def audit(self, paper: Paper) -> dict:
        with patch(
            "app.citation_audit._verify_reference",
            side_effect=_no_crossref,
        ):
            return run_citation_audit(paper)

    def test_7_audit_runs_over_an_uploaded_paper(self) -> None:
        paper = extract_uploaded_paper("rich.docx", rich_docx())
        report = self.audit(paper)
        self.assertIn(report["status"], {"complete", "incomplete"})
        self.assertEqual(report["paper_id"], paper["id"])
        self.assertGreater(report["counts"]["references_parsed"], 0)
        self.assertGreater(report["counts"]["citations_found"], 0)
        self.assertTrue(report["explanation"])
        for issue in report["issues"]:
            self.assertIn(issue["severity"], {"high", "medium", "low"})
            self.assertTrue(issue["excerpt"], issue["category"])

    def test_8_correction_prompt_is_complete_and_safe(self) -> None:
        paper = extract_uploaded_paper("rich.docx", rich_docx())
        prompt = self.audit(paper)["fix_prompt"]
        for section in (
            "Paper under review",
            "Audit scope",
            "Important limitations",
            "Findings grouped by severity",
            "Reference verification notes",
            "Requested correction format",
            "Safety rules",
        ):
            self.assertIn(section, prompt)
        self.assertIn("Do not invent", prompt)
        self.assertIn("leads for review", prompt)
        self.assertIn(paper["title"], prompt)
        self.assertLessEqual(len(prompt), 12000)

    def test_audit_explains_a_failure_instead_of_crashing(self) -> None:
        paper = extract_uploaded_paper("rich.docx", rich_docx())
        with patch(
            "app.citation_audit._verify_reference",
            side_effect=RuntimeError("crossref exploded"),
        ):
            report = run_citation_audit(paper)
        self.assertIn(report["status"], {"complete", "incomplete", "error"})
        if report["status"] == "error":
            self.assertTrue(report["error"])


def _no_crossref(reference: dict) -> dict:
    from datetime import UTC, datetime

    reference["status"] = "lookup_error"
    reference["message"] = "Crossref is disabled in this test."
    reference["lookup_method"] = "bibliographic_search"
    reference["checked_at"] = datetime.now(UTC).isoformat(timespec="seconds")
    reference["uncertainty"] = "The provider was never contacted."
    return reference


# --------------------------------------------------------------------------
# Flow 9: external-service failures
# --------------------------------------------------------------------------


class ExternalFailureTests(FlowTestCase):
    def test_model_http_failures_each_produce_a_specific_message(self) -> None:
        cases = {
            401: "authorize",
            402: "usage limit",
            429: "too many requests",
            503: "temporarily unavailable",
        }
        for status, expected in cases.items():
            with self.subTest(status=status):
                paper = make_paper()
                with patch(
                    "app.states.workspace_state.requests.post",
                    return_value=FakeResponse(status, {"error": {}}),
                ), patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}):
                    with self.assertRaises(OpenRouterError) as caught:
                        _call_openrouter("What?", [])
                self.assertIn(expected, str(caught.exception).lower())

    def test_model_transport_failure_surfaces_as_a_readable_error(self) -> None:
        import requests

        paper = make_paper()
        with self.assertRaises(OpenRouterError) as caught:
            self.ask(
                paper,
                "What is the main finding?",
                requests.exceptions.ConnectionError("network down"),
            )
        self.assertIn("couldn't reach", str(caught.exception).lower())

    def test_missing_api_key_is_a_clear_message(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OPENROUTER_API_KEY", None)
            with self.assertRaises(OpenRouterError) as caught:
                _call_openrouter("What?", [])
        self.assertIn("not configured", str(caught.exception).lower())

    def test_search_provider_reports_what_will_actually_run(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            for key in ("GEMINI_API_KEY", "OPENROUTER_API_KEY"):
                os.environ.pop(key, None)
            self.assertEqual(search_provider(), "")
            os.environ["GEMINI_API_KEY"] = "gemini-test-key"
            try:
                self.assertEqual(search_provider(), "gemini")
            finally:
                os.environ.pop("GEMINI_API_KEY", None)

    def test_search_unavailable_is_its_own_state(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            for key in ("GEMINI_API_KEY", "OPENROUTER_API_KEY"):
                os.environ.pop(key, None)
            self.assertEqual(search_provider(), "")
            with self.assertRaises(SearchUnavailable):
                _call_search("recent work on spacing effects", None)

    def test_crossref_failure_never_claims_a_work_is_fake(self) -> None:
        paper = make_paper()
        with patch(
            "app.citation_audit._verify_reference",
            side_effect=_no_crossref,
        ):
            report = run_citation_audit(paper)
        self.assertEqual(report["status"], "incomplete")
        self.assertTrue(report["limits"])
        for reference in report["references"]:
            self.assertIn("lookup_error", reference["message"] + reference["status"])
        self.assertNotIn("does not exist", report["summary"].lower())

    def test_search_failure_leaves_the_paper_answer_alone(self) -> None:
        paper = make_paper()
        grounded, _ = self.ask(
            paper,
            "What is the main finding?",
            answer_payload("Spacing improved recall.", ["p1"]),
        )
        # With a provider configured, a search fault is raised so the caller can
        # record a "failed" status against the external section only.
        with patch.dict(
            os.environ, {"GEMINI_API_KEY": "test-key"}, clear=False
        ), patch(
            "app.states.workspace_state.requests.post",
            side_effect=RuntimeError("search broke"),
        ):
            with self.assertRaises(RuntimeError):
                _call_search("recent work", None)
        # The grounded answer survives the search failure untouched.
        self.assertFalse(grounded["unsupported"])
        self.assertEqual(grounded["evidence"][0]["passage_id"], "p1")


# --------------------------------------------------------------------------
# Flow 10: a failed upload must not disturb the open paper
# --------------------------------------------------------------------------


class UploadIsolationTests(FlowTestCase):
    def test_rejected_upload_leaves_the_previous_paper_intact(self) -> None:
        opened = extract_uploaded_paper("rich.docx", rich_docx())
        before = (opened["id"], opened["title"], len(opened["passages"]))

        for name, payload in (
            ("notes.txt", b"plain text"),
            ("empty.pdf", b""),
            ("broken.docx", b"PK\x03\x04 not really a docx"),
        ):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    extract_uploaded_paper(name, payload)
                self.assertEqual(
                    (opened["id"], opened["title"], len(opened["passages"])),
                    before,
                )

    def test_failed_extraction_leaves_no_media_on_disk(self) -> None:
        with self.assertRaises(ValueError):
            extract_uploaded_paper("empty.pdf", b"")
        self.assertEqual(list(self.media_root.iterdir()), [])

    def test_held_back_paper_media_is_removed_when_discarded(self) -> None:
        paper = extract_uploaded_paper("figures.pdf", pdf_with_figures())
        self.assertTrue(paper_images(paper))
        self.assertTrue(media_dir(paper["id"]).exists())
        discard_media(paper["id"])
        self.assertFalse(media_dir(paper["id"]).exists())

    def test_removing_a_paper_deletes_its_images(self) -> None:
        paper = extract_uploaded_paper("figures.pdf", pdf_with_figures())
        discard_media(paper["id"])
        remaining = [
            entry for entry in self.media_root.iterdir() if entry.is_dir()
        ]
        self.assertEqual(remaining, [])


# --------------------------------------------------------------------------
# Classification is part of the upload pipeline
# --------------------------------------------------------------------------


class ClassificationFlowTests(FlowTestCase):
    def test_paper_missing_its_abstract_is_never_hard_rejected(self) -> None:
        document = Document()
        document.add_heading("Results", level=1)
        document.add_paragraph("Recall accuracy differed between conditions.")
        document.add_heading("References", level=1)
        document.add_paragraph("Lee, A. (2021). A study. Research Press.")
        stream = BytesIO()
        document.save(stream)
        paper = extract_uploaded_paper("noabstract.docx", stream.getvalue())
        outcome = classify_research_paper(
            paper["passages"], paper["references"]
        )["outcome"]
        self.assertIn(outcome, {"accepted", "accepted_with_warnings", "needs_review"})
        self.assertNotEqual(outcome, "rejected")

    def test_a_paper_with_abstract_and_references_is_accepted(self) -> None:
        paper = extract_uploaded_paper("rich.docx", rich_docx())
        outcome = classify_research_paper(
            paper["passages"], paper["references"]
        )["outcome"]
        self.assertIn(outcome, {"accepted", "accepted_with_warnings"})


if __name__ == "__main__":
    unittest.main()