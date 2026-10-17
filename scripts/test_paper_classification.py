import shutil
import tempfile
import unittest
from io import BytesIO

from docx import Document

from app.paper_classification import (
    STRUCTURAL_SIGNALS,
    classify_research_paper,
)
from app.states.paper_data import extract_uploaded_paper, get_sample_papers


def build_docx(paragraphs: list[tuple[str, str]]) -> bytes:
    document = Document()
    for style, text in paragraphs:
        if style == "h1":
            document.add_heading(text, level=1)
        else:
            document.add_paragraph(text)
    stream = BytesIO()
    document.save(stream)
    return stream.getvalue()


FULL_PAPER = [
    ("h1", "Abstract"),
    ("p", "Sixty students completed a trial. Results were analysed with regression."),
    ("h1", "Introduction"),
    ("p", "Background on green space and wellbeing is reviewed here."),
    ("h1", "Methods"),
    ("p", "Participants were recruited and randomly assigned to a condition."),
    ("h1", "Results"),
    ("p", "Exposure was associated with higher scores (Lee et al., 2021)."),
    ("h1", "Discussion"),
    ("p", "The findings are limited by self-report."),
    ("h1", "Conclusion"),
    ("p", "Outdoor breaks appear promising."),
    ("h1", "References"),
    ("p", "Lee, A. (2021). Green space and wellbeing. Research Press."),
]

RECIPE = [
    ("h1", "Ingredients"),
    ("p", "Flour, butter, sugar, and a pinch of salt. Mix well."),
    ("p", "Bake until golden and serve warm."),
]

PROSE = [
    ("p", "It was a bright cold day in April, and the clocks were striking thirteen."),
    ("p", "Winston Smith slipped quickly through the glass doors of Victory Mansions."),
]


class ResearchClassificationTests(unittest.TestCase):
    def setUp(self):
        self.media = tempfile.mkdtemp(prefix="paperproof-cls-")
        self._previous = None

    def classify(self, paragraphs: list[tuple[str, str]]) -> dict:
        return extract_uploaded_paper(
            "doc.docx", build_docx(paragraphs)
        )["research_classification"]

    def test_full_paper_is_accepted(self):
        result = self.classify(FULL_PAPER)
        self.assertEqual(result["outcome"], "accepted")
        self.assertEqual(result["missing_signals"], [])
        self.assertTrue(result["signals"])
        self.assertIn("in-text citation", " ".join(result["signals"]))

    def test_missing_one_section_is_never_a_rejection(self):
        """Spec: never call a paper invalid solely for one absent section."""
        headings = [
            "Abstract",
            "Introduction",
            "Methods",
            "Results",
            "Discussion",
            "Conclusion",
            "References",
        ]
        for omitted in headings:
            with self.subTest(omitted=omitted):
                kept = [p for p in FULL_PAPER if p[1] != omitted]
                result = self.classify(kept)
                self.assertNotEqual(result["outcome"], "rejected")
                self.assertIn(
                    result["outcome"],
                    {"accepted", "accepted_with_warnings", "needs_review"},
                )

    def test_dropping_any_single_structural_group_still_accepted(self):
        groups = set(STRUCTURAL_SIGNALS)
        for label in groups:
            with self.subTest(group=label):
                result = classify_research_paper(
                    passages=[
                        {"id": "p1", "section": "Abstract", "page": 1, "text": "Study summary."},
                        {"id": "p2", "section": "Introduction", "page": 1, "text": "Background."},
                        {"id": "p3", "section": "Methods", "page": 2, "text": "Participants were recruited."},
                        {"id": "p4", "section": "Results", "page": 2, "text": "Scores rose (Lee et al., 2021)."},
                        {"id": "p5", "section": "Discussion", "page": 3, "text": "Limits noted."},
                        {"id": "p6", "section": "Conclusion", "page": 3, "text": "Worth adopting."},
                        {"id": "p7", "section": "References", "page": 3, "text": "Lee, A. (2021). A study. Press."},
                    ],
                    references=[{"id": "r1", "text": "Lee, A. (2021). A study. Press."}],
                    bibliography_detected=True,
                )
                self.assertNotEqual(result["outcome"], "rejected")
                self.assertIn(label, " ".join(result["signals"]) + " ".join(result["missing_signals"]))

    def test_short_report_is_accepted_with_warnings(self):
        result = self.classify(
            [
                ("h1", "Abstract"),
                ("p", "A short report describing a classroom activity."),
                ("h1", "Methods"),
                ("p", "Students answered concept questions before and after discussion."),
                ("h1", "Results"),
                ("p", "Correct responses rose after discussion."),
            ]
        )
        self.assertEqual(result["outcome"], "accepted_with_warnings")
        self.assertIn("bibliography heading", result["missing_signals"])

    def test_abstract_only_document_needs_review(self):
        result = self.classify(
            [
                ("h1", "Abstract"),
                ("p", "Preliminary results from an ongoing study of coastal erosion."),
            ]
        )
        self.assertEqual(result["outcome"], "needs_review")
        self.assertIn("Confirm to open it", result["message"])

    def test_unrelated_documents_are_rejected(self):
        for label, paragraphs in (("recipe", RECIPE), ("prose", PROSE)):
            with self.subTest(document=label):
                result = self.classify(paragraphs)
                self.assertEqual(result["outcome"], "rejected")
                self.assertIn("not been opened", result["message"])

    def test_numeric_citation_paper_with_structure_is_accepted(self):
        result = self.classify(
            [
                ("h1", "Abstract"),
                ("p", "A randomised trial of two delivery methods was conducted."),
                ("h1", "Methods"),
                ("p", "Participants were randomly assigned [1]."),
                ("h1", "Results"),
                ("p", "Scores were higher in one group [2, 3]."),
                ("h1", "References"),
                ("p", "Lee, A. (2021). A trial. Research Press."),
            ]
        )
        self.assertIn(
            result["outcome"], {"accepted", "accepted_with_warnings"}
        )
        self.assertIn("numeric", " ".join(result["signals"]))

    def test_every_result_explains_itself(self):
        for label, paragraphs in (
            ("full", FULL_PAPER),
            ("short", FULL_PAPER[:4]),
            ("abstract", FULL_PAPER[:2]),
            ("recipe", RECIPE),
        ):
            with self.subTest(document=label):
                result = self.classify(paragraphs)
                self.assertIn(
                    result["outcome"],
                    {
                        "accepted",
                        "accepted_with_warnings",
                        "needs_review",
                        "rejected",
                    },
                )
                self.assertTrue(result["message"].strip())
                self.assertTrue(result["signals"])
                # Only an incomplete paper has anything to report missing.
                if result["outcome"] != "accepted":
                    self.assertTrue(result["missing_signals"])

    def test_sample_papers_are_accepted(self):
        for paper in get_sample_papers():
            with self.subTest(paper=paper["id"]):
                self.assertEqual(
                    paper["research_classification"]["outcome"], "accepted"
                )

    def test_classification_is_recorded_on_uploaded_paper(self):
        paper = extract_uploaded_paper("doc.docx", build_docx(FULL_PAPER))
        self.assertIn("research_classification", paper)
        self.assertEqual(
            paper["research_classification"]["outcome"], "accepted"
        )


if __name__ == "__main__":
    unittest.main()