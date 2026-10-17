"""Tests for the external reference lookup that reaches the web.

The rest of the citation-audit suite stubs `_verify_reference` out, so the code
that actually talks to Crossref — DOI extraction, metadata agreement, retry
handling, and the honest failure states — had no coverage at all. These tests
drive that path for real and intercept only the HTTP call, so the matching and
error-reporting logic is genuinely exercised.

One test is live rather than mocked. It is skipped unless
`PAPERPROOF_LIVE_CROSSREF=1` is set, so the default suite stays deterministic
and offline, and anyone can opt in to prove the provider is reachable.
"""

import os
import unittest
from unittest.mock import Mock, patch

from requests import HTTPError

from app.citation_audit import (
    CROSSREF_MAX_ATTEMPTS,
    CROSSREF_URL,
    _api_get,
    _doi_from_text,
    _reference_title,
    _verify_reference,
    run_citation_audit,
)
from app.states.paper_data import Paper, get_sample_papers

# A real IEEE-format entry: title in quotes, year late, DOI trailing. Taken from
# the kind of bibliography an engineering paper actually carries.
IEEE_ENTRY = (
    "S. Bhatia, Z. A. Jaffery, and S. Mehfuz, \u201cGSO-BiLSTM: performance "
    "assessment of IoT enable smart irrigation system using intelligent "
    "algorithms,\u201d International Journal of Machine Learning and "
    "Cybernetics, 2025, doi: 10.1007/s13042-025-02775-x."
)
IEEE_TITLE = (
    "GSO-BiLSTM: performance assessment of IoT enable smart irrigation system "
    "using intelligent algorithms"
)
IEEE_DOI = "10.1007/s13042-025-02775-x"


def _work(**overrides) -> dict:
    """A minimal Crossref `message` payload for a matching journal article."""
    work = {
        "DOI": IEEE_DOI,
        "title": [IEEE_TITLE],
        "author": [{"family": "Bhatia", "given": "Sneha"}],
        "published": {"date-parts": [[2025, 4, 18]]},
    }
    work.update(overrides)
    return work


def _response(status: int = 200, payload: dict | None = None, headers=None):
    response = Mock()
    response.status_code = status
    response.json.return_value = payload if payload is not None else {}
    response.headers = headers or {}
    response.raise_for_status = Mock()
    if status >= 400:
        # Must be a real RequestException subclass, because that is what
        # `requests` raises and what `_verify_reference` actually handles.
        response.raise_for_status.side_effect = HTTPError(f"HTTP {status}")
    return response


def _reference(text: str = IEEE_ENTRY) -> dict:
    return {
        "id": "r1",
        "text": text,
        "doi": _doi_from_text(text),
        "parsed_title": _reference_title(text),
        "parsed_author": "Bhatia",
        "parsed_year": "2025",
        "status": "pending",
        "message": "",
        "lookup_method": "",
        "matched_fields": [],
        "conflicting_fields": [],
        "matched_title": "",
        "matched_author": "",
        "matched_year": "",
        "checked_at": "",
        "uncertainty": "",
    }


class ReferenceTitleParsingTests(unittest.TestCase):
    """Titles must come from the quoted form when the entry has one."""

    def test_ieee_style_title_is_not_read_from_the_trailing_doi(self):
        # Regression: the year-based fallback took everything after "2025",
        # split it at the first ".", and returned "doi: 10". Every IEEE
        # reference then scored zero against Crossref and was reported
        # ambiguous however well it actually matched.
        self.assertEqual(_reference_title(IEEE_ENTRY), IEEE_TITLE)

    def test_ieee_style_doi_is_still_extracted(self):
        self.assertEqual(_doi_from_text(IEEE_ENTRY), IEEE_DOI)

    def test_apa_style_title_is_still_supported(self):
        entry = "Bhatia, S. (2025). Smart irrigation telemetry. In Press."
        self.assertEqual(_reference_title(entry), "Smart irrigation telemetry")

    def test_quoted_doi_is_not_taken_as_a_title(self):
        entry = f'Reference listed as "10.1007/s13042-025-02775-x" with no title, 2020.'
        self.assertNotEqual(_reference_title(entry), "10.1007/s13042-025-02775-x")

    def test_straight_quotes_are_handled_too(self):
        entry = (
            'A. Author, "A plain quoted article title," Journal of Things, 2021.'
        )
        self.assertEqual(_reference_title(entry), "A plain quoted article title")


class DoiLookupTests(unittest.TestCase):
    def test_exact_doi_match_is_confirmed(self):
        with patch(
            "app.citation_audit.requests.get",
            return_value=_response(200, {"message": _work()}),
        ):
            result = _verify_reference(_reference())
        self.assertEqual(result["status"], "confirmed")
        self.assertEqual(result["lookup_method"], "doi")
        self.assertEqual(result["matched_year"], "2025")
        self.assertIn("title aligns", result["matched_fields"])
        self.assertIn("first author aligns", result["matched_fields"])
        self.assertIn("year aligns", result["matched_fields"])

    def test_missing_doi_reports_not_found_without_claiming_the_work_is_fake(self):
        with patch(
            "app.citation_audit.requests.get", return_value=_response(404)
        ):
            result = _verify_reference(_reference())
        self.assertEqual(result["status"], "not_found_in_crossref")
        self.assertIn("does not prove the work does not exist", result["message"])
        self.assertTrue(result["uncertainty"])

    def test_doi_that_resolves_to_a_different_work_is_ambiguous(self):
        other = _work(DOI="10.1007/some-other-work")
        with patch(
            "app.citation_audit.requests.get",
            return_value=_response(200, {"message": other}),
        ):
            result = _verify_reference(_reference())
        self.assertEqual(result["status"], "ambiguous")
        self.assertIn("did not match the supplied DOI", result["message"])

    def test_year_disagreement_is_ambiguous_and_names_the_conflict(self):
        stale = _work(published={"date-parts": [[2019, 1, 1]]})
        with patch(
            "app.citation_audit.requests.get",
            return_value=_response(200, {"message": stale}),
        ):
            result = _verify_reference(_reference())
        self.assertEqual(result["status"], "ambiguous")
        self.assertIn("year", result["conflicting_fields"])

    def test_doi_lookup_is_preferred_over_a_bibliographic_search(self):
        with patch(
            "app.citation_audit.requests.get",
            return_value=_response(200, {"message": _work()}),
        ) as get:
            _verify_reference(_reference())
        self.assertEqual(get.call_count, 1)
        # The DOI is percent-encoded into the path, so it is not a plain suffix.
        self.assertIn("/works/10.1007%2Fs13042-025-02775-x", get.call_args.args[0])
        self.assertNotIn(
            "query.bibliographic", get.call_args.kwargs.get("params") or {}
        )

    def test_unreadable_response_is_reported_not_raised(self):
        bad = _response(200, {"message": "not-a-dict"})
        with patch("app.citation_audit.requests.get", return_value=bad):
            result = _verify_reference(_reference())
        self.assertEqual(result["status"], "lookup_error")
        self.assertIn("verify this reference manually", result["message"])


class BibliographicSearchTests(unittest.TestCase):
    ENTRY_WITHOUT_DOI = (
        "S. Bhatia, \u201cGSO-BiLSTM: performance assessment of IoT enable smart "
        "irrigation system using intelligent algorithms,\u201d International "
        "Journal of Machine Learning and Cybernetics, 2025."
    )

    def test_entry_without_a_doi_falls_back_to_a_metadata_search(self):
        payload = {
            "message": {"items": [_work(DOI="10.1007/found-by-search")]}
        }
        with patch(
            "app.citation_audit.requests.get",
            return_value=_response(200, payload),
        ) as get:
            result = _verify_reference(_reference(self.ENTRY_WITHOUT_DOI))
        self.assertEqual(result["lookup_method"], "bibliographic_search")
        self.assertEqual(get.call_args.kwargs["params"]["rows"], 3)
        self.assertIn("query.bibliographic", get.call_args.kwargs["params"])
        self.assertEqual(result["status"], "confirmed")
        # Provenance must record that this was a metadata match, not a DOI
        # verification, so the reader does not over-trust it.
        self.assertIn("matches the available title", result["message"])

    def test_weak_metadata_match_is_labelled_as_not_a_doi_match(self):
        payload = {
            "message": {"items": [_work(DOI="10.1007/only-similar")]}
        }
        with patch(
            "app.citation_audit.requests.get",
            return_value=_response(200, payload),
        ):
            result = _verify_reference(
                _reference(
                    "S. Bhatia, \u201cAn entirely different subject about marine "
                    "coral reef acoustics,\u201d Journal of Oceanography, 2025."
                )
            )
        self.assertEqual(result["status"], "ambiguous")
        self.assertEqual(result["lookup_method"], "bibliographic_search")
        self.assertIn("did not agree sufficiently", result["message"])
        self.assertTrue(result["uncertainty"])

    def test_no_search_results_is_reported_honestly(self):
        with patch(
            "app.citation_audit.requests.get",
            return_value=_response(200, {"message": {"items": []}}),
        ):
            result = _verify_reference(_reference(self.ENTRY_WITHOUT_DOI))
        self.assertEqual(result["status"], "not_found_in_crossref")
        self.assertIn("does not prove the work does not exist", result["message"])


class OpenAlexFallbackTests(unittest.TestCase):
    """Crossref has nothing, so the free second resolver is consulted."""

    OA_WORK = {
        "id": "https://openalex.org/W4412882196",
        "doi": "https://doi.org/10.1007/s13042-025-02775-x",
        "title": IEEE_TITLE,
        "publication_year": 2025,
        "authorships": [
            {"author": {"display_name": "Sandeep Bhatia"}},
            {"author": {"display_name": "Zainul Abdin Jaffery"}},
        ],
    }

    def _split_by_host(self, crossref, openalex):
        def by_host(url, **kwargs):
            return openalex if "openalex" in url else crossref

        return by_host

    def test_openalex_record_is_normalized_into_the_crossref_shape(self):
        from app.citation_audit import _openalex_to_work

        work = _openalex_to_work(self.OA_WORK)
        self.assertEqual(work["DOI"], IEEE_DOI)
        self.assertEqual(work["title"], [IEEE_TITLE])
        self.assertEqual(work["author"][0]["family"], "Bhatia")
        # The existing Crossref-shaped readers must understand it unchanged.
        from app.citation_audit import _crossref_year, _work_metadata

        title, author, year, doi = _work_metadata(work)
        self.assertEqual(title, IEEE_TITLE)
        self.assertEqual(author, "Bhatia")
        self.assertEqual(year, "2025")
        self.assertEqual(doi, IEEE_DOI)
        self.assertEqual(_crossref_year(work), "2025")

    def test_a_crossref_404_is_recovered_by_openalex(self):
        with patch(
            "app.citation_audit.requests.get",
            side_effect=self._split_by_host(_response(404), _response(200, self.OA_WORK)),
        ):
            result = _verify_reference(_reference())
        self.assertEqual(result["status"], "confirmed")
        self.assertEqual(result["lookup_method"], "doi · OpenAlex")
        self.assertIn("OpenAlex", result["message"])
        self.assertEqual(result["matched_year"], "2025")

    def test_openalex_is_never_reported_as_proving_absence(self):
        with patch(
            "app.citation_audit.requests.get",
            side_effect=self._split_by_host(_response(404), _response(404)),
        ):
            result = _verify_reference(_reference())
        self.assertEqual(result["status"], "not_found_in_crossref")
        self.assertIn("Crossref or OpenAlex", result["message"])
        self.assertIn("does not prove the work does not exist", result["message"])
        self.assertTrue(result["uncertainty"])

    def test_openalex_outage_is_reported_as_a_lookup_error_not_as_missing(self):
        # A resolver being down says nothing about the reference, so it must
        # never be laundered into "not found".
        from requests import ConnectionError as RequestsConnectionError

        with patch(
            "app.citation_audit.requests.get",
            side_effect=RequestsConnectionError("openalex down"),
        ):
            with patch("app.citation_audit.time.sleep"):
                result = _verify_reference(_reference())
        self.assertEqual(result["status"], "lookup_error")
        self.assertNotEqual(result["status"], "not_found_in_crossref")

    def test_a_crossref_outage_still_lets_openalex_settle_the_entry(self):
        from requests import ConnectionError as RequestsConnectionError

        def by_host(url, **kwargs):
            if "openalex" in url:
                return _response(200, self.OA_WORK)
            raise RequestsConnectionError("crossref down")

        with patch("app.citation_audit.requests.get", side_effect=by_host):
            with patch("app.citation_audit.time.sleep"):
                result = _verify_reference(_reference())
        self.assertEqual(result["status"], "confirmed")
        self.assertIn("OpenAlex", result["message"])
        self.assertIn("Crossref was unreachable", result["message"])

    def test_bibliographic_search_falls_back_to_openalex(self):
        entry = (
            "S. Bhatia, \u201cGSO-BiLSTM: performance assessment of IoT enable "
            "smart irrigation system using intelligent algorithms,\u201d "
            "International Journal of Machine Learning and Cybernetics, 2025."
        )

        def by_host(url, **kwargs):
            if "openalex" in url:
                return _response(200, {"results": [self.OA_WORK]})
            return _response(200, {"message": {"items": []}})

        with patch("app.citation_audit.requests.get", side_effect=by_host):
            result = _verify_reference(_reference(entry))
        self.assertEqual(result["status"], "confirmed")
        self.assertEqual(result["lookup_method"], "bibliographic_search · OpenAlex")
        self.assertIn("not by DOI", result["uncertainty"])

    def test_several_openalex_matches_are_ambiguous_not_confirmed(self):
        entry = (
            "S. Bhatia, \u201cGSO-BiLSTM: performance assessment of IoT enable "
            "smart irrigation system using intelligent algorithms,\u201d "
            "International Journal of Machine Learning and Cybernetics, 2025."
        )
        duplicate = {**self.OA_WORK, "id": "https://openalex.org/W2"}

        def by_host(url, **kwargs):
            if "openalex" in url:
                return _response(200, {"results": [self.OA_WORK, duplicate]})
            return _response(200, {"message": {"items": []}})

        with patch("app.citation_audit.requests.get", side_effect=by_host):
            result = _verify_reference(_reference(entry))
        self.assertEqual(result["status"], "ambiguous")
        self.assertIn("Multiple plausible", result["message"])

    def test_a_confirmed_crossref_hit_never_asks_openalex(self):
        with patch(
            "app.citation_audit.requests.get",
            return_value=_response(200, {"message": _work()}),
        ) as get:
            result = _verify_reference(_reference())
        self.assertEqual(result["status"], "confirmed")
        self.assertEqual(get.call_count, 1)
        self.assertNotIn("openalex", get.call_args.args[0])


class RetryTests(unittest.TestCase):
    def test_transient_failure_is_retried_then_succeeds(self):
        responses = [
            _response(503),
            _response(429, headers={"Retry-After": "0"}),
            _response(200, {"message": _work()}),
        ]
        with patch("app.citation_audit.requests.get", side_effect=responses) as get:
            with patch("app.citation_audit.time.sleep"):
                result = _verify_reference(_reference())
        self.assertEqual(result["status"], "confirmed")
        self.assertEqual(get.call_count, 3)

    def test_retries_are_bounded_and_do_not_raise(self):
        # Each resolver gets its own bounded retry budget; the audit still ends
        # in an honest lookup_error rather than raising.
        with patch(
            "app.citation_audit.requests.get", return_value=_response(503)
        ) as get:
            with patch("app.citation_audit.time.sleep"):
                result = _verify_reference(_reference())
        self.assertEqual(get.call_count, CROSSREF_MAX_ATTEMPTS * 2)
        self.assertEqual(result["status"], "lookup_error")

    def test_a_404_is_not_retried_but_does_consult_the_second_resolver(self):
        # Crossref must not retry a 404, and the entry must still be given to
        # OpenAlex before anything is reported missing.
        def by_host(url, **kwargs):
            if "openalex" in url:
                return _response(404)
            return _response(404)

        with patch(
            "app.citation_audit.requests.get", side_effect=by_host
        ) as get:
            _verify_reference(_reference())
        hosts = [call.args[0] for call in get.call_args_list]
        self.assertEqual(len(hosts), 2)
        self.assertTrue(any("crossref" in host for host in hosts))
        self.assertTrue(any("openalex" in host for host in hosts))

    def test_a_network_error_is_recorded_rather_than_raised(self):
        from requests import ConnectionError as RequestsConnectionError

        with patch(
            "app.citation_audit.requests.get",
            side_effect=RequestsConnectionError("dns failure"),
        ):
            with patch("app.citation_audit.time.sleep"):
                result = _verify_reference(_reference())
        self.assertEqual(result["status"], "lookup_error")
        self.assertIn("could not be reached", result["message"])
        self.assertIn("not a statement about the reference", result["uncertainty"])

    def test_retry_after_is_capped(self):
        # An unbounded Retry-After from a provider must not stall an audit.
        response = _response(429, headers={"Retry-After": "9999"})
        with patch("app.citation_audit.requests.get", return_value=response) as get:
            with patch("app.citation_audit.time.sleep") as sleep:
                returned = _api_get(
                    f"{CROSSREF_URL}/x", headers={"User-Agent": "test"}
                )
        # The final attempt is returned to the caller rather than raised.
        self.assertEqual(get.call_count, CROSSREF_MAX_ATTEMPTS)
        self.assertEqual(returned.status_code, 429)
        self.assertTrue(sleep.called)
        for call in sleep.call_args_list:
            self.assertLessEqual(call.args[0], 30.0)


class AuditSurvivesBadLookupsTests(unittest.TestCase):
    """One failed reference must never cost the user the whole audit."""

    def _paper_with_reference(self, text: str) -> Paper:
        paper = dict(get_sample_papers()[0])
        paper["references"] = [{"id": "r1", "text": text}]
        return paper

    def test_audit_completes_when_the_provider_is_unreachable(self):
        from requests import ConnectionError as RequestsConnectionError

        paper = self._paper_with_reference(IEEE_ENTRY)
        with patch(
            "app.citation_audit.requests.get",
            side_effect=RequestsConnectionError("offline"),
        ):
            with patch("app.citation_audit.time.sleep"):
                report = run_citation_audit(paper)
        self.assertEqual(report["references"][0]["status"], "lookup_error")
        self.assertIn(
            "not a statement about the reference",
            report["references"][0]["uncertainty"],
        )

    def test_structural_findings_survive_an_unexpected_error(self):
        paper = dict(get_sample_papers()[0])
        paper["passages"] = [
            {
                "id": "p1",
                "section": "Body",
                "page": 1,
                "text": "As shown by Doe [1], the system improves yield.",
            }
        ]
        paper["references"] = [{"id": "r1", "text": IEEE_ENTRY}]
        with patch(
            "app.citation_audit.requests.get",
            side_effect=RuntimeError("provider down"),
        ):
            with patch("app.citation_audit.time.sleep"):
                report = run_citation_audit(paper)
        self.assertTrue(report["issues"])
        self.assertEqual(report["references"][0]["status"], "lookup_error")
        self.assertIn("abandoned mid-request", report["references"][0]["uncertainty"])


@unittest.skipUnless(
    os.getenv("PAPERPROOF_LIVE_CROSSREF") == "1",
    "set PAPERPROOF_LIVE_CROSSREF=1 to hit api.crossref.org for real",
)
class LiveCrossrefTests(unittest.TestCase):
    """Opt-in proof that the web lookup works against the real provider."""

    def test_a_real_ieee_doi_resolves_and_matches(self):
        result = _verify_reference(_reference())
        self.assertEqual(result["status"], "confirmed", result["message"])
        self.assertEqual(result["matched_year"], "2025")

    def test_a_known_absent_doi_is_reported_not_found(self):
        # 10.9999/this-doi-does-not-exist is not in Crossref's registry.
        bogus = _reference(
            "A. Nobody, A study that was never registered anywhere, "
            "Journal of Nowhere, 2020, doi: 10.9999/paperproof-absent-doi."
        )
        result = _verify_reference(bogus)
        self.assertEqual(result["status"], "not_found_in_crossref")


if __name__ == "__main__":
    unittest.main()