"""Logging safeguards.

Two rules from the security requirements apply to every log line this project
writes:

* API keys must never reach a log file, a console, or a traceback.
* A failure must be recorded with enough context to act on, without copying
  document text into the log.

Redaction is applied by replacing the process-wide log record factory rather
than by attaching a filter to a logger. That distinction matters: a
``logging.Filter`` only sees records logged on the exact logger it is attached
to, so any module or library that disables propagation would bypass it. A
record factory runs for every record the process creates, whatever logger,
handler, or propagation setting is in play. It is therefore installed once at
import time and cannot be forgotten at a call site.
"""

from __future__ import annotations

import logging
import os
import re
import traceback
from pathlib import Path

# Environment variables whose values are credentials.
SECRET_ENV_VARS = (
    "OPENROUTER_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
)

REDACTED = "[redacted]"

# Credential shapes that can appear in a URL, a header dump, or a provider's
# error text, even when no environment variable is at fault. Each entry pairs a
# pattern with the number of leading capture groups to keep, so a match becomes
# "<kept text>[redacted]" instead of being dropped whole or raising on a missing
# group.
_SECRET_PATTERNS: tuple[tuple[re.Pattern[str], int], ...] = (
    # sk-or-v1-..., sk-...
    (re.compile(r"sk-[A-Za-z0-9_\-]{12,}"), 0),
    # Google API keys.
    (re.compile(r"AIza[A-Za-z0-9_\-]{20,}"), 0),
    # GitHub tokens.
    (re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"), 0),
    # Authorization headers.
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{16,}"), 0),
    # key= / api_key= / token= query parameters: keep the name, drop the value.
    (
        re.compile(
            r"(?i)\b((?:api[-_]?key|apikey|access[-_]?token|token))"
            r"(=)([A-Za-z0-9._\-]{8,})"
        ),
        2,
    ),
    # "API key: abc123" style: keep the label and separator, drop the value.
    (
        re.compile(
            r"(?i)\b(api[-_ ]?key|authorization|secret|password)"
            r"([\":=]\s*\"?)([A-Za-z0-9._\-]{8,})"
        ),
        2,
    ),
)


def _live_secrets() -> list[str]:
    """Credential values currently set in the environment.

    Read at call time, never cached: a key can be set after this module is
    imported.
    """
    values = []
    for name in SECRET_ENV_VARS:
        value = os.getenv(name, "").strip()
        if len(value) >= 8:
            values.append(value)
    return values


def redact(text: str) -> str:
    """Remove anything that looks like a credential from a log line."""
    for secret in _live_secrets():
        if secret in text:
            text = text.replace(secret, REDACTED)
    for pattern, keep in _SECRET_PATTERNS:
        text = pattern.sub(
            lambda m, _keep=keep: "".join(m.group(i) for i in range(1, _keep + 1))
            + REDACTED,
            text,
        )
    return text


def _scrub(record: logging.LogRecord) -> logging.LogRecord:
    if isinstance(record.msg, str):
        record.msg = redact(record.msg)
    if record.args:
        # args are interpolated later, so scrub each string in place. Non-string
        # arguments are left alone: formatting them here would lose structure
        # that a handler or traceback may still need.
        record.args = tuple(
            redact(arg) if isinstance(arg, str) else arg for arg in record.args
        )
    return record


class RedactingFilter(logging.Filter):
    """Scrub credentials from a record.

    Useful when attached directly to a specific handler. The global guarantee
    comes from the record factory installed by :func:`install_redaction`.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        _scrub(record)
        return True


_ORIGINAL_FACTORY = logging.getLogRecordFactory()
_INSTALLED = False


def _redacting_factory(*args: object, **kwargs: object) -> logging.LogRecord:
    return _scrub(_ORIGINAL_FACTORY(*args, **kwargs))  # type: ignore[arg-type]


def install_redaction() -> None:
    """Make every log record in this process credential-free, once."""
    global _INSTALLED
    if _INSTALLED:
        return
    logging.setLogRecordFactory(_redacting_factory)
    _INSTALLED = True


def error_location(error: BaseException) -> str:
    """A compact call path for a failure, with no source text.

    ``traceback.extract_tb`` returns the stack frames only. It deliberately does
    not include the exception message or the offending source line, either of
    which can carry paper text or a provider response body.
    """
    if error.__traceback__ is None:
        return "unknown location"
    frames = traceback.extract_tb(error.__traceback__)
    if not frames:
        return "unknown location"
    return " <- ".join(
        f"{Path(frame.filename).name}:{frame.lineno}" for frame in frames
    )


def log_failure(operation: str, error: BaseException) -> None:
    """Record a failure with usable context and no document content.

    This replaces the bare ``logging.exception(f"Error: {e}")`` pattern.

    ``logging.exception`` is deliberately not used. It renders the exception's
    own message and the offending source line into the log, and neither passes
    through the record factory, so a provider error body or a line of paper text
    built into an exception message would be written to disk verbatim. Logging
    the operation, the exception type, and the call path keeps the line
    actionable while guaranteeing nothing else is recorded.
    """
    logging.error(
        "%s failed: %s at %s",
        operation,
        type(error).__name__,
        error_location(error),
    )