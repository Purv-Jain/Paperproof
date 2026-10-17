import os
import unittest
from unittest.mock import Mock, patch

from app.model_config import (
    DEFAULT_MODEL,
    ROUTER_MODEL,
    check_all,
    check_capability,
    resolve_model,
    supports_parameter,
)
from app.search_provenance import (
    MAX_SOURCES,
    parse_gemini_annotations,
    parse_url_citations,
    provenance_warning,
)
from app.states.workspace_state import SearchUnavailable


class ModelConfigTests(unittest.TestCase):
    def setUp(self):
        for name in (
            "OPENROUTER_TEXT_MODEL",
            "OPENROUTER_REFERENCE_MODEL",
            "OPENROUTER_WEB_SEARCH_MODEL",
            "OPENROUTER_VISION_MODEL",
        ):
            os.environ.pop(name, None)

    def test_unset_capabilities_fall_back_to_the_text_model(self):
        self.assertEqual(resolve_model("text"), DEFAULT_MODEL)
        self.assertEqual(resolve_model("reference"), DEFAULT_MODEL)
        self.assertEqual(resolve_model("web_search"), DEFAULT_MODEL)

    def test_each_capability_reads_its_own_variable(self):
        os.environ["OPENROUTER_TEXT_MODEL"] = "vendor/text"
        os.environ["OPENROUTER_REFERENCE_MODEL"] = "vendor/reference"
        os.environ["OPENROUTER_WEB_SEARCH_MODEL"] = "vendor/search"
        self.assertEqual(resolve_model("text"), "vendor/text")
        self.assertEqual(resolve_model("reference"), "vendor/reference")
        self.assertEqual(resolve_model("web_search"), "vendor/search")

    def test_whitespace_only_value_is_ignored(self):
        os.environ["OPENROUTER_TEXT_MODEL"] = "   "
        self.assertEqual(resolve_model("text"), DEFAULT_MODEL)

    def test_vision_is_unavailable_by_design(self):
        check = check_capability("vision")
        self.assertFalse(check["available"])
        self.assertIn("does not use a vision model", check["detail"])

    def test_unknown_model_is_reported_not_used(self):
        os.environ["OPENROUTER_TEXT_MODEL"] = "vendor/does-not-exist"
        index = {
            "vendor/real": {
                "id": "vendor/real",
                "supported_parameters": ["temperature"],
                "architecture": {"input_modalities": ["text"]},
            }
        }
        with patch("app.model_config.model_index", return_value=(index, "")):
            check = check_capability("text")
        self.assertFalse(check["available"])
        self.assertIn("not in OpenRouter's current model list", check["detail"])

    def test_web_search_requires_tool_support(self):
        index = {
            "vendor/no-tools": {
                "id": "vendor/no-tools",
                "supported_parameters": ["temperature"],
                "architecture": {"input_modalities": ["text"]},
            },
            "vendor/tools": {
                "id": "vendor/tools",
                "supported_parameters": ["temperature", "tools"],
                "architecture": {"input_modalities": ["text"]},
            },
            "vendor/native": {
                "id": "vendor/native",
                "supported_parameters": ["temperature", "web_search_options"],
                "architecture": {"input_modalities": ["text"]},
            },
        }
        with patch.dict(os.environ, {"OPENROUTER_WEB_SEARCH_MODEL": "vendor/no-tools"}):
            with patch("app.model_config.model_index", return_value=(index, "")):
                self.assertFalse(check_capability("web_search")["available"])
        with patch.dict(os.environ, {"OPENROUTER_WEB_SEARCH_MODEL": "vendor/tools"}):
            with patch("app.model_config.model_index", return_value=(index, "")):
                check = check_capability("web_search")
                self.assertTrue(check["available"])
                self.assertIn("web plugin", check["detail"])
        with patch.dict(os.environ, {"OPENROUTER_WEB_SEARCH_MODEL": "vendor/native"}):
            with patch("app.model_config.model_index", return_value=(index, "")):
                check = check_capability("web_search")
                self.assertTrue(check["available"])
                self.assertIn("Native web search", check["detail"])

    def test_free_router_is_not_claimed_as_verified(self):
        with patch.dict(os.environ, {"OPENROUTER_WEB_SEARCH_MODEL": ROUTER_MODEL}):
            check = check_capability("web_search")
        self.assertTrue(check["available"])
        self.assertIn("cannot be verified in advance", check["detail"])

    def test_default_model_is_a_verified_free_model(self):
        self.assertEqual(resolve_model("text"), DEFAULT_MODEL)
        self.assertTrue(DEFAULT_MODEL.endswith(":free"))
        self.assertNotEqual(DEFAULT_MODEL, ROUTER_MODEL)

    def test_auto_router_is_not_claimed_as_verified(self):
        with patch.dict(
            os.environ,
            {
                "OPENROUTER_TEXT_MODEL": "openrouter/free",
                "OPENROUTER_REFERENCE_MODEL": "openrouter/free",
            },
        ):
            check = check_capability("text")
        self.assertTrue(check["available"])
        self.assertIn("cannot be verified in advance", check["detail"])

    def test_default_model_is_checked_against_the_live_index(self):
        index = {
            DEFAULT_MODEL: {
                "id": DEFAULT_MODEL,
                "supported_parameters": ["temperature", "tools"],
                "architecture": {"input_modalities": ["text"]},
            }
        }
        with patch("app.model_config.model_index", return_value=(index, "")):
            check = check_capability("text")
        self.assertTrue(check["available"])
        self.assertEqual(check["model"], DEFAULT_MODEL)
        self.assertNotIn("not in OpenRouter's current model list", check["detail"])

    def test_capability_report_covers_every_capability_without_network(self):
        with patch("app.model_config.model_index", return_value=({}, "")):
            checks = check_all()
        self.assertEqual(
            {check["capability"] for check in checks},
            {"text", "reference", "vision", "web_search"},
        )

    def test_supports_parameter_checks_the_live_index(self):
        index = {
            "vendor/structured": {
                "id": "vendor/structured",
                "supported_parameters": ["temperature", "structured_outputs"],
            },
            "vendor/plain": {
                "id": "vendor/plain",
                "supported_parameters": ["temperature"],
            },
        }
        with patch("app.model_config.model_index", return_value=(index, "")):
            self.assertTrue(
                supports_parameter("vendor/structured", "structured_outputs")
            )
            self.assertFalse(
                supports_parameter("vendor/plain", "structured_outputs")
            )
            self.assertFalse(supports_parameter("vendor/unknown", "tools"))
            self.assertFalse(supports_parameter("", "tools"))

    def test_unverifiable_index_does_not_block_use(self):
        os.environ["OPENROUTER_TEXT_MODEL"] = "vendor/whatever"
        with patch("app.model_config.model_index", return_value=({}, "could not check")):
            check = check_capability("text")
        self.assertTrue(check["available"])
        self.assertIn("could not check", check["detail"])

    def test_check_all_reports_every_capability(self):
        with patch("app.model_config.model_index", return_value=({}, "")):
            checks = check_all()
        capabilities = {check["capability"] for check in checks}
        self.assertEqual(
            capabilities, {"text", "reference", "vision", "web_search"}
        )


class GeminiSearchTests(unittest.TestCase):
    """The Gemini path must behave the same way without needing a key."""

    def setUp(self):
        self._env = {
            "GEMINI_API_KEY": os.environ.pop("GEMINI_API_KEY", None),
            "OPENROUTER_API_KEY": os.environ.pop("OPENROUTER_API_KEY", None),
        }

    def tearDown(self):
        for name, value in self._env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    @staticmethod
    def response(status_code=200, body=None, text=""):
        response = Mock()
        response.status_code = status_code
        response.text = text or ""
        response.json.return_value = body if body is not None else {}
        return response

    def body(self):
        return {
            "steps": [
                {"type": "thought", "summary": []},
                {
                    "type": "google_search_call",
                    "arguments": {"queries": ["green space wellbeing"]},
                },
                {
                    "type": "model_output",
                    "content": [
                        {
                            "type": "text",
                            "text": "Recent reviews report mixed findings.",
                            "annotations": [
                                {
                                    "type": "url_citation",
                                    "url": "https://www.nature.com/articles/x",
                                    "title": "nature.com",
                                    "start_index": 0,
                                    "end_index": 10,
                                },
                                {
                                    "type": "url_citation",
                                    "url": "https://example.org/review",
                                    "title": "example.org",
                                    "start_index": 11,
                                    "end_index": 20,
                                },
                            ],
                        }
                    ],
                },
            ]
        }

    def test_gemini_answer_and_sources_are_parsed(self):
        from app.states.workspace_state import _call_gemini_search

        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-only"}):
            with patch("requests.post", return_value=self.response(200, self.body())):
                text, sources = _call_gemini_search("What is the latest evidence?")
        self.assertEqual(text, "Recent reviews report mixed findings.")
        self.assertEqual(len(sources), 2)
        self.assertEqual(sources[0]["publisher"], "nature.com")
        self.assertEqual(sources[0]["url"], "https://www.nature.com/articles/x")
        # Gemini returns no excerpt; the record must not invent one.
        self.assertEqual(sources[0]["excerpt"], "")
        self.assertFalse(sources[0]["verified"])

    def test_search_suggestions_html_is_never_used(self):
        from app.states.workspace_state import _call_gemini_search

        body = self.body()
        body["steps"].insert(
            2,
            {
                "type": "google_search_result",
                "result": [{"search_suggestions": "<script>tracking</script>"}],
            },
        )
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-only"}):
            with patch("requests.post", return_value=self.response(200, body)):
                text, sources = _call_gemini_search("question")
        self.assertNotIn("script", text)
        for source in sources:
            self.assertNotIn("script", source["excerpt"])
            self.assertNotIn("script", source["title"])

    def test_billing_failure_is_explained_actionably(self):
        from app.states.workspace_state import _call_gemini_search

        body = {
            "error": {
                "message": "Grounding with Google Search is not available on the free tier. Enable billing."
            }
        }
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-only"}):
            with patch("requests.post", return_value=self.response(400, body)):
                with self.assertRaises(SearchUnavailable) as caught:
                    _call_gemini_search("question")
        self.assertIn("free tier", str(caught.exception))
        self.assertIn("Enable billing", str(caught.exception))
        self.assertIn("paper-only answer", str(caught.exception))

    def test_rate_limit_is_reported_without_pretending(self):
        from app.states.workspace_state import _call_gemini_search

        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-only"}):
            with patch("requests.post", return_value=self.response(429)):
                with self.assertRaises(SearchUnavailable):
                    _call_gemini_search("question")

    def test_empty_result_is_not_reported_as_success(self):
        from app.states.workspace_state import _call_gemini_search

        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-only"}):
            with patch(
                "requests.post",
                return_value=self.response(200, {"steps": [{"type": "thought"}]}),
            ):
                with self.assertRaises(SearchUnavailable):
                    _call_gemini_search("question")

    def test_missing_key_raises_before_any_request(self):
        from app.states.workspace_state import _call_gemini_search

        with patch("requests.post") as post:
            with self.assertRaises(SearchUnavailable):
                _call_gemini_search("question")
        post.assert_not_called()

    def test_dispatch_prefers_gemini_and_reports_the_provider(self):
        from app.states.workspace_state import _call_search

        env = {"GEMINI_API_KEY": "k1", "OPENROUTER_API_KEY": "k2"}
        with patch.dict(os.environ, env):
            with patch(
                "app.states.workspace_state._call_gemini_search",
                return_value=("text", []),
            ) as gemini:
                with patch(
                    "app.states.workspace_state._call_openrouter_search"
                ) as openrouter:
                    _, _, provider = _call_search("question")
        gemini.assert_called_once()
        openrouter.assert_not_called()
        self.assertIn("Gemini", provider)

    def test_dispatch_falls_back_to_openrouter_when_gemini_fails(self):
        from app.states.workspace_state import _call_search

        env = {"GEMINI_API_KEY": "k1", "OPENROUTER_API_KEY": "k2"}
        with patch.dict(os.environ, env):
            with patch(
                "app.states.workspace_state._call_gemini_search",
                side_effect=SearchUnavailable("billing"),
            ):
                with patch(
                    "app.states.workspace_state._call_openrouter_search",
                    return_value=("text", []),
                ) as openrouter:
                    _, _, provider = _call_search("question")
        openrouter.assert_called_once()
        self.assertIn("OpenRouter", provider)

    def test_dispatch_fails_clearly_when_no_provider_exists(self):
        from app.states.workspace_state import _call_search

        with patch("requests.post") as post:
            with self.assertRaises(SearchUnavailable) as caught:
                _call_search("question")
        post.assert_not_called()
        self.assertIn("no search provider is configured", str(caught.exception))

    def test_capability_report_follows_the_configured_provider(self):
        from app.model_config import check_capability, search_provider

        with patch.dict(os.environ, {"GEMINI_API_KEY": "k1"}):
            self.assertEqual(search_provider(), "gemini")
            check = check_capability("web_search")
            self.assertTrue(check["available"])
            self.assertTrue(check["model"].startswith("gemini-"))
            self.assertIn("paid tier", check["detail"])
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "k2"}):
            self.assertEqual(search_provider(), "openrouter")


class SearchProvenanceTests(unittest.TestCase):
    def test_annotations_become_checkable_sources(self):
        sources = parse_url_citations(
            [
                {
                    "type": "url_citation",
                    "url_citation": {
                        "url": "https://www.example.org/study",
                        "title": "A relevant study",
                        "content": "An excerpt from the page.",
                    },
                }
            ],
            "Reader requested a comparison.",
            retrieved_at="2026-01-01T00:00:00+00:00",
        )
        self.assertEqual(len(sources), 1)
        source = sources[0]
        self.assertEqual(source["url"], "https://www.example.org/study")
        self.assertEqual(source["title"], "A relevant study")
        self.assertEqual(source["publisher"], "example.org")
        self.assertEqual(source["retrieved_at"], "2026-01-01T00:00:00+00:00")
        self.assertEqual(source["excerpt"], "An excerpt from the page.")
        self.assertEqual(source["reason"], "Reader requested a comparison.")
        # A snippet must never be presented as a verified fact.
        self.assertFalse(source["verified"])

    def test_unsafe_and_unusable_citations_are_dropped(self):
        sources = parse_url_citations(
            [
                {"url_citation": {"url": "javascript:alert(1)", "title": "x"}},
                {"url_citation": {"url": "file:///etc/passwd", "title": "x"}},
                {"url_citation": {"url": "", "title": "x"}},
                {"url_citation": {"title": "no url"}},
                {"not_a_citation": {}},
                "a string",
                {"url_citation": {"url": "https://ok.example/a"}},
            ],
            "reason",
        )
        self.assertEqual([s["url"] for s in sources], ["https://ok.example/a"])

    def test_duplicate_urls_are_collapsed(self):
        citation = {
            "url_citation": {
                "url": "https://example.org/a",
                "title": "A",
            }
        }
        sources = parse_url_citations([citation, dict(citation)], "reason")
        self.assertEqual(len(sources), 1)

    def test_source_count_is_bounded(self):
        annotations = [
            {"url_citation": {"url": f"https://example.org/{i}", "title": "t"}}
            for i in range(MAX_SOURCES + 10)
        ]
        self.assertEqual(len(parse_url_citations(annotations, "reason")), MAX_SOURCES)

    def test_long_excerpts_are_trimmed(self):
        sources = parse_url_citations(
            [
                {
                    "url_citation": {
                        "url": "https://example.org/a",
                        "title": "T",
                        "content": "word " * 2000,
                    }
                }
            ],
            "reason",
        )
        self.assertLessEqual(len(sources[0]["excerpt"]), 600)

    def test_missing_title_falls_back_to_the_url(self):
        sources = parse_url_citations(
            [{"url_citation": {"url": "https://example.org/a"}}], "reason"
        )
        self.assertEqual(sources[0]["title"], "https://example.org/a")

    def test_malformed_input_returns_nothing(self):
        for value in (None, "text", 42, {"a": 1}):
            with self.subTest(value=value):
                self.assertEqual(parse_url_citations(value, "reason"), [])

    def test_provenance_warning_is_shown_only_with_sources(self):
        self.assertEqual(provenance_warning(False), "")
        self.assertIn("not pages that Paperproof read", provenance_warning(True))


class GeminiProvenanceTests(unittest.TestCase):
    def test_flat_annotations_become_sources(self):
        sources = parse_gemini_annotations(
            [
                {
                    "type": "url_citation",
                    "url": "https://www.nature.com/articles/x",
                    "title": "nature.com",
                    "start_index": 0,
                    "end_index": 10,
                }
            ],
            "Reader requested a comparison.",
            retrieved_at="2026-01-01T00:00:00+00:00",
        )
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0]["publisher"], "nature.com")
        self.assertEqual(sources[0]["title"], "nature.com")
        self.assertEqual(sources[0]["excerpt"], "")
        self.assertFalse(sources[0]["verified"])

    def test_unsafe_urls_are_dropped(self):
        sources = parse_gemini_annotations(
            [
                {"type": "url_citation", "url": "javascript:alert(1)"},
                {"type": "url_citation", "url": ""},
                {"type": "image", "url": "https://ok.example/a"},
                {"type": "url_citation", "url": "https://ok.example/a"},
            ],
            "reason",
        )
        self.assertEqual([s["url"] for s in sources], ["https://ok.example/a"])

    def test_malformed_input_returns_nothing(self):
        for value in (None, "text", 7, {"a": 1}):
            with self.subTest(value=value):
                self.assertEqual(parse_gemini_annotations(value, "reason"), [])


if __name__ == "__main__":
    unittest.main()