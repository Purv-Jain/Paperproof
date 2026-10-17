"""Model selection by capability, with live capability checks.

Model choice is deployment configuration, never UI logic. Each capability
resolves through its own environment variable so a deployment can use a
strong model for grounded answers and a different one for reference lookups.

The OpenRouter model list is public and needs no API key, so capabilities can
be verified before spending anything. A configured model that no longer exists
is reported as unavailable rather than failing later at request time.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Literal, TypedDict

import requests

MODELS_URL = "https://openrouter.ai/api/v1/models"
INDEX_TTL_SECONDS = 900.0
REQUEST_TIMEOUT = (3, 8)

Capability = Literal["text", "reference", "vision", "web_search"]

ENV_VARS: dict[str, str] = {
    "text": "OPENROUTER_TEXT_MODEL",
    "reference": "OPENROUTER_REFERENCE_MODEL",
    "vision": "OPENROUTER_VISION_MODEL",
    "web_search": "OPENROUTER_WEB_SEARCH_MODEL",
}

# Default text model. Chosen by probing OpenRouter's zero-cost tier against a
# real key: this one is available, is a capable 120B mixture-of-experts, has a
# 256k context window, and advertises `structured_outputs`, so Paperproof can
# enforce the answer contract with a real JSON schema instead of relying on
# prompt wording. Override per deployment with the variables above.
DEFAULT_MODEL = "nvidia/nemotron-3-super-120b-a12b:free"

# Known-good zero-cost fallbacks, also verified against a real key. They exist
# because free models are withdrawn or restricted without notice. Paperproof
# does not switch silently: it names the model it used.
FALLBACK_MODELS = (
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
    "poolside/laguna-s-2.1:free",
    "dots-studio/dots-3-note-preview:free",
)

# The auto-router. Support cannot be verified in advance because it picks a
# model at request time, so it is reported honestly rather than as verified.
ROUTER_MODEL = "openrouter/free"

# A capability with no configured model inherits the text model, except
# vision, which this application deliberately does not use: figures are read
# locally with OCR, caption text, and nearby paper text only.
FALLBACK: dict[str, str | None] = {
    "text": None,
    "reference": "text",
    "vision": None,
    "web_search": "text",
}

UNSUPPORTED_BY_DESIGN = {
    "vision": (
        "Paperproof does not use a vision model. Figures are read locally "
        "from OCR, caption, and nearby text, and image pixels are never sent "
        "to an external provider."
    )
}


class CapabilityCheck(TypedDict):
    capability: str
    model: str
    available: bool
    detail: str


def resolve_model(capability: str) -> str:
    """Return the model slug configured for a capability."""
    configured = os.getenv(ENV_VARS.get(capability, ""), "").strip()
    if configured:
        return configured
    fallback = FALLBACK.get(capability)
    if fallback:
        return resolve_model(fallback)
    if capability == "text":
        return DEFAULT_MODEL
    return ""


_index_cache: dict[str, dict] = {}
_index_cached_at = 0.0
_index_error: str = ""


def model_index(force: bool = False) -> tuple[dict[str, dict], str]:
    """Fetch (and briefly cache) the public OpenRouter model list.

    Returns the index keyed by model id plus an error message that is empty
    when the lookup succeeded. A failure is never fatal: the application keeps
    working with an unverified model.
    """
    global _index_cache, _index_cached_at, _index_error
    now = time.monotonic()
    if not force and _index_cache and now - _index_cached_at < INDEX_TTL_SECONDS:
        return _index_cache, _index_error
    try:
        response = requests.get(
            MODELS_URL,
            headers={"User-Agent": "Paperproof/1.0 (capability check)"},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        body = response.json()
        data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(data, list):
            raise ValueError("unexpected model list")
        _index_cache = {
            entry["id"]: entry
            for entry in data
            if isinstance(entry, dict) and isinstance(entry.get("id"), str)
        }
        _index_cached_at = now
        _index_error = "" if _index_cache else "OpenRouter returned an empty model list."
    except Exception as e:
        logging.warning("Model capability lookup failed: %s", e)
        _index_error = (
            "Paperproof could not check model availability with OpenRouter. "
            "Configured models are still used."
        )
    return _index_cache, _index_error


def _supports(entry: dict, parameter: str) -> bool:
    parameters = entry.get("supported_parameters")
    return isinstance(parameters, list) and parameter in parameters


def supports_parameter(model: str, parameter: str) -> bool:
    """Whether a configured model advertises a request parameter.

    Used to upgrade a request when the model can guarantee a machine-readable
    answer instead of relying on prompt wording alone. Returns False when the
    model cannot be verified, so callers keep their existing safe behaviour.
    """
    if not model:
        return False
    index, _ = model_index()
    entry = index.get(model)
    if not isinstance(entry, dict):
        return False
    return _supports(entry, parameter)


def search_provider() -> str:
    """Which provider will answer external-context searches.

    Gemini is preferred when a key is present; OpenRouter is the fallback.
    """
    if os.getenv("GEMINI_API_KEY", "").strip():
        return "gemini"
    if os.getenv("OPENROUTER_API_KEY", "").strip():
        return "openrouter"
    return ""


def check_capability(capability: str) -> CapabilityCheck:
    """Verify that the model for a capability exists and can do the job."""
    if capability in UNSUPPORTED_BY_DESIGN:
        return CapabilityCheck(
            capability=capability,
            model=resolve_model(capability),
            available=False,
            detail=UNSUPPORTED_BY_DESIGN[capability],
        )
    if capability == "web_search" and search_provider() == "gemini":
        return CapabilityCheck(
            capability=capability,
            model=os.getenv("GEMINI_SEARCH_MODEL", "").strip()
            or "gemini-3.8-flash",
            available=True,
            detail=(
                "Google Search grounding via Gemini. Note that current Gemini "
                "models require the paid tier for API search grounding; if it "
                "is not enabled, Paperproof falls back to OpenRouter."
            ),
        )
    model = resolve_model(capability)
    if not model:
        return CapabilityCheck(
            capability=capability,
            model="",
            available=False,
            detail=f"No model is configured for {capability}.",
        )
    index, error = model_index()
    if not index:
        return CapabilityCheck(
            capability=capability,
            model=model,
            available=True,
            detail=error or "Availability could not be verified.",
        )
    if model == ROUTER_MODEL:
        return CapabilityCheck(
            capability=capability,
            model=model,
            available=True,
            detail=(
                "OpenRouter free-tier router. Support cannot be verified in "
                "advance because the router picks a model at request time, so "
                "answer quality may vary between questions."
            ),
        )
    entry = index.get(model)
    if entry is None:
        return CapabilityCheck(
            capability=capability,
            model=model,
            available=False,
            detail=(
                f"{model} is not in OpenRouter's current model list. It may "
                "have been renamed or withdrawn."
            ),
        )
    if capability == "web_search":
        if _supports(entry, "web_search_options"):
            detail = "Native web search is available for this model."
        elif _supports(entry, "tools"):
            detail = (
                "Web search is available through OpenRouter's web plugin "
                "(provider search or Exa fallback). This costs extra."
            )
        else:
            return CapabilityCheck(
                capability=capability,
                model=model,
                available=False,
                detail=(
                    "This model does not advertise tool support, so OpenRouter "
                    "web search may fail. Choose a model that supports tools."
                ),
            )
    else:
        detail = "Model is available and accepts text input."
    return CapabilityCheck(
        capability=capability, model=model, available=True, detail=detail
    )


def check_all() -> list[CapabilityCheck]:
    return [check_capability(capability) for capability in ENV_VARS]


__all__ = [
    "DEFAULT_MODEL",
    "ENV_VARS",
    "ROUTER_MODEL",
    "CapabilityCheck",
    "check_all",
    "check_capability",
    "model_index",
    "resolve_model",
    "search_provider",
    "supports_parameter",
]