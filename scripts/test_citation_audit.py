import reflex as rx

import unittest
from io import BytesIO
from unittest.mock import patch

from docx import Document

from app.citation_audit import (
    _build_issues,
    _references_for_paper,
    run_citation_audit,
)
from app.states.paper_data import extract_uploaded_paper, get_sample_papers


def skipped_crossref(reference):
    reference["status"] = "lookup_error"
    reference["message"] = "Crossref disabled in unit test."
    return reference


class CitationAuditTests(unittest.TestCase):
    @patch("app.citation_audit._verify_reference", side_effect=skipped_crossref)
    def test_sample_findings_are_derived_from_paper_text(self, _verify):
        paper = get_sample_papers()[0]
        report = run_citation_audit(paper)
        categories = {issue["category"] for issue in report["issues"]}
        self.assertEqual(report["status"], "incomplete")
        self.assertIn("Citation missing from reference list", categories)
        self.assertIn("Possible duplicate reference", categories)
        self.assertIn("Citation placement · manual review", categories)
        self.assertTrue(all(issue["excerpt"] for issue in report["issues"]))
        self.assertIn(paper["title"], report["fix_prompt"])
        self.assertTrue(
            all(
                reference["status"] == "lookup_error"
                for reference in report["references"]
            )
        )

    @patch("app.citation_audit._verify_reference", side_effect=skipped_crossref)
    def test_docx_bibliography_is_parsed_and_compared(self, _verify):
        document = Document()
        document.add_heading("Introduction", level=1)
        document.add_paragraph(
            "Prior work supports this question (Lee et al., 2021). A second source is noted (Miller, 2018)."
        )
        document.add_heading("References", level=1)
        document.add_paragraph(
            "Lee, A. (2021). Learning through explanation. Journal of Learning, 12(2), 20–31."
        )
        document.add_paragraph(
            "Unused, R. (2016). A separate source. Research Press."
        )
        stream = BytesIO()
        document.save(stream)
        paper = extract_uploaded_paper("audit.docx", stream.getvalue())
        report = run_citation_audit(paper)
        self.assertEqual(len(report["references"]), 2)
        self.assertTrue(
            any("References" in ref["location"] for ref in report["references"])
        )
        self.assertTrue(
            any(
                issue["category"] == "Citation missing from reference list"
                for issue in report["issues"]
            )
        )
        self.assertTrue(
            any(
                issue["category"] == "Uncited reference"
                for issue in report["issues"]
            )
        )
        self.assertTrue(all(issue["excerpt"] for issue in report["issues"]))

    def test_upload_references_are_authoritative_and_body_only_is_scanned(self):
        document = Document()
        document.add_paragraph("Introduction")
        document.add_paragraph("We cite Lee (2021) in the study text.")
        document.add_paragraph("References")
        document.add_paragraph("Lee, A. (2021). A study. Research Press.")
        document.add_paragraph(
            "Unused, R. (2016). Review of Other (2019). Research Press."
        )
        stream = BytesIO()
        document.save(stream)
        paper = extract_uploaded_paper("body.docx", stream.getvalue())
        references, found = _references_for_paper(paper)
        self.assertTrue(found)
        self.assertEqual(
            [r["text"] for r in references],
            [r["text"] for r in paper["references"]],
        )
        issues = _build_issues(paper, references, found)
        self.assertFalse(
            any(
                i["category"] == "Citation missing from reference list"
                for i in issues
            )
        )
        self.assertEqual(
            sum(i["category"] == "Uncited reference" for i in issues), 1
        )
        paper["references"] = []
        self.assertEqual(_references_for_paper(paper), ([], True))

    def test_legacy_upload_bibliography_is_not_scanned_as_body(self):
        paper = get_sample_papers()[0]
        paper["source"] = "upload"
        paper["references"] = []
        paper["passages"] = [
            {
                "id": "p1",
                "section": "Extracted page",
                "page": 1,
                "text": "Introduction\nWe cite Lee (2021).\nReferences\nLee, A. (2021). A study. Research Press.\nUnused, R. (2016). Review of Other (2019). Research Press.\nAppendix A\nAdditional observations remain available.",
            }
        ]
        references, found = _references_for_paper(paper)
        self.assertTrue(found)
        self.assertEqual(len(references), 2)
        issues = _build_issues(paper, references, found)
        self.assertFalse(
            any(
                i["category"] == "Citation missing from reference list"
                for i in issues
            )
        )
        self.assertEqual(
            sum(i["category"] == "Uncited reference" for i in issues), 1
        )

    @patch("app.citation_audit._verify_reference", side_effect=skipped_crossref)
    def test_missing_bibliography_is_reported_as_incomplete(self, _verify):
        document = Document()
        document.add_heading("Findings", level=1)
        document.add_paragraph("An assertion appears here (Lopez, 2020).")
        stream = BytesIO()
        document.save(stream)
        paper = extract_uploaded_paper("no_references.docx", stream.getvalue())
        report = run_citation_audit(paper)
        self.assertEqual(report["status"], "incomplete")
        self.assertTrue(
            any(
                issue["category"] == "Bibliography extraction"
                for issue in report["issues"]
            )
        )
        self.assertEqual(report["references"], [])


if __name__ == "__main__":
    unittest.main()
