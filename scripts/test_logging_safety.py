"""Log safety.

The security requirements forbid logging API keys and forbid copying document
content into logs. These tests pin both, and pin that the filter is actually
installed rather than merely available.
"""

from __future__ import annotations

import io
import logging
import os
import unittest
from unittest.mock import patch

from app.logging_safety import (
    REDACTED,
    RedactingFilter,
    _redacting_factory,
    install_redaction,
    log_failure,
    redact,
)

_ORIGINAL = logging.getLogRecordFactory()

FAKE_OPENROUTER_KEY = "sk-or-v1-abcdef0123456789abcdef"
FAKE_GEMINI_KEY = "AIzaSyA1234567890abcdefghijklmnopqrstu"


class CaptureHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.lines.append(self.format(record))
        except Exception:  # pragma: no cover - mirrors logging's own behaviour
            self.handleError(record)


class RedactionTests(unittest.TestCase):
    def test_a_live_environment_key_is_removed(self) -> None:
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": FAKE_OPENROUTER_KEY}):
            cleaned = redact(f"request failed with key {FAKE_OPENROUTER_KEY}")
        self.assertNotIn(FAKE_OPENROUTER_KEY, cleaned)
        self.assertIn(REDACTED, cleaned)

    def test_gemini_key_shape_is_removed_without_any_environment(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GEMINI_API_KEY", None)
            cleaned = redact(f"url=https://x/?key={FAKE_GEMINI_KEY}")
        self.assertNotIn(FAKE_GEMINI_KEY, cleaned)

    def test_a_key_in_a_url_query_parameter_is_removed(self) -> None:
        cleaned = redact("GET https://api.example/v1?api_key=abc123def456ghi789")
        self.assertNotIn("abc123def456ghi789", cleaned)
        self.assertIn("api_key=", cleaned)

    def test_a_bearer_header_is_removed(self) -> None:
        cleaned = redact("headers={'Authorization': 'Bearer sk-or-v1-zzzzzzzzzzzzzzzz'}")
        self.assertNotIn("sk-or-v1-zzzzzzzzzzzzzzzz", cleaned)

    def test_an_openai_style_key_is_removed(self) -> None:
        cleaned = redact("token ghp_abcdefghijklmnopqrstuvwxyz012345")
        self.assertNotIn("ghp_abcdefghijklmnopqrstuvwxyz012345", cleaned)

    def test_ordinary_messages_are_left_alone(self) -> None:
        message = "Crossref lookup failed: connection reset by peer"
        self.assertEqual(redact(message), message)

    def test_prose_is_not_mangled(self) -> None:
        message = "Could not measure image colours: invalid mode"
        self.assertEqual(redact(message), message)


class FilterTests(unittest.TestCase):
    def test_filter_scrubs_the_message(self) -> None:
        record = logging.LogRecord(
            "test", logging.WARNING, __file__, 1,
            "failed using sk-or-v1-abcdef0123456789abcdef", None, None,
        )
        RedactingFilter().filter(record)
        self.assertNotIn("sk-or-v1-abcdef0123456789abcdef", record.msg)

    def test_filter_scrubs_interpolation_arguments(self) -> None:
        record = logging.LogRecord(
            "test", logging.WARNING, __file__, 1, "key is %s", ("sk-or-v1-abcdef0123456789abcdef",), None,
        )
        RedactingFilter().filter(record)
        self.assertNotIn("sk-or-v1-abcdef0123456789abcdef", record.args[0])

    def test_filter_keeps_the_record(self) -> None:
        record = logging.LogRecord(
            "test", logging.WARNING, __file__, 1, "hello", None, None
        )
        self.assertTrue(RedactingFilter().filter(record))


class InstalledFilterTests(unittest.TestCase):
    """Redaction has to be active, not merely available."""

    def setUp(self) -> None:
        install_redaction()
        self.handler = CaptureHandler()
        self.handler.setFormatter(logging.Formatter("%(message)s"))
        self.logger = logging.getLogger("paperproof.test.leak")
        self.logger.addHandler(self.handler)
        # Propagation off is the case a logger-level filter would miss.
        self.logger.propagate = False
        self.addCleanup(self.logger.removeHandler, self.handler)

    def test_the_record_factory_is_replaced(self) -> None:
        install_redaction()
        factory = logging.getLogRecordFactory()
        self.assertIsNot(factory, _ORIGINAL)
        self.assertIs(factory, _redacting_factory)

    def test_a_key_logged_by_a_module_with_propagation_off_is_still_redacted(
        self,
    ) -> None:
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": FAKE_OPENROUTER_KEY}):
            self.logger.error("authorization failed for %s", FAKE_OPENROUTER_KEY)
        joined = "\n".join(self.handler.lines)
        self.assertNotIn(FAKE_OPENROUTER_KEY, joined)
        self.assertIn(REDACTED, joined)

    def test_a_key_logged_by_a_third_party_logger_is_also_redacted(self) -> None:
        other = logging.getLogger("httpcore.connection")
        other.addHandler(self.handler)
        other.propagate = False
        self.addCleanup(other.removeHandler, self.handler)
        with patch.dict(os.environ, {"GEMINI_API_KEY": FAKE_GEMINI_KEY}):
            other.warning("url=%s", f"https://api.example/?key={FAKE_GEMINI_KEY}")
        joined = "\n".join(self.handler.lines)
        self.assertNotIn(FAKE_GEMINI_KEY, joined)

    def test_install_is_idempotent(self) -> None:
        install_redaction()
        install_redaction()
        self.assertIs(logging.getLogRecordFactory(), _redacting_factory)


class LogFailureTests(unittest.TestCase):
    """log_failure writes to the root logger, as a cross-cutting helper should."""

    def capture_root(self) -> str:
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
        root = logging.getLogger()
        previous_level = root.level
        root.setLevel(logging.DEBUG)
        root.addHandler(handler)
        self.addCleanup(root.removeHandler, handler)
        self.addCleanup(root.setLevel, previous_level)
        return stream

    def test_a_failure_names_the_operation_and_the_error_type(self) -> None:
        stream = self.capture_root()
        try:
            raise ValueError("no idea what this was")
        except ValueError as error:
            log_failure("Crossref lookup", error)

        output = stream.getvalue()
        self.assertIn("Crossref lookup", output)
        self.assertIn("ValueError", output)

    def test_a_failure_never_records_document_text(self) -> None:
        stream = self.capture_root()
        secret_text = "A confidential abstract sentence about participants."
        try:
            raise RuntimeError(secret_text)
        except RuntimeError as error:
            log_failure("Reading a document", error)

        output = stream.getvalue()
        self.assertNotIn(secret_text, output)
        self.assertIn("RuntimeError", output)
        # The call path is recorded so the failure is still actionable.
        self.assertIn("test_logging_safety.py:", output)

    def test_a_failure_does_not_log_a_credential_from_the_error_text(self) -> None:
        stream = self.capture_root()
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": FAKE_OPENROUTER_KEY}):
            try:
                raise RuntimeError(f"auth failed for {FAKE_OPENROUTER_KEY}")
            except RuntimeError as error:
                log_failure("Grounded answer request", error)
        self.assertNotIn(FAKE_OPENROUTER_KEY, stream.getvalue())


class NoSecretInSourceTests(unittest.TestCase):
    """A guard against committing a real key in the first place."""

    def test_env_example_has_placeholders_not_credentials(self) -> None:
        from pathlib import Path

        template = (
            Path(__file__).resolve().parent.parent / ".env.example"
        ).read_text(encoding="utf-8")
        for name in ("OPENROUTER_API_KEY", "GEMINI_API_KEY"):
            for line in template.splitlines():
                if line.strip().startswith(f"{name}="):
                    value = line.split("=", 1)[1].strip()
                    with self.subTest(name=name):
                        self.assertIn(
                            value,
                            {"", "your-key-here", "your-gemini-key-here"},
                            f"{name} in .env.example must be a placeholder",
                        )


if __name__ == "__main__":
    unittest.main()