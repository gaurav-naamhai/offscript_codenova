"""Reusable Google Gemini API client for Inkloom AI Intelligence.

Provides structured multimodal AI generation via Google GenAI SDK (google-genai).
Strictly separates live Gemini execution from explicit mock testing mode.
"""

from datetime import datetime, timezone
import json
import logging
import os
import re
import time
from typing import Any, Callable, Dict, Optional, Type, TypeVar
from pydantic import BaseModel

from app.config import Settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


# ============================================================================
# EXCEPTION HIERARCHY
# ============================================================================


class GeminiError(Exception):
    """Base exception for all Gemini intelligence module errors."""


class GeminiConfigurationError(GeminiError):
    """Raised when client is misconfigured (e.g., missing API key in real mode)."""


class GeminiAPIError(GeminiError):
    """Raised when the Gemini API service returns an error."""

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


class GeminiTimeoutError(GeminiError):
    """Raised when an API call times out."""


class GeminiModelNotFoundError(GeminiError):
    """Raised when the specified model does not exist or is inaccessible."""


class GeminiQuotaError(GeminiError):
    """Raised when API rate limits or quota limits are exhausted."""


# ============================================================================
# REUSABLE GEMINI CLIENT
# ============================================================================


class GeminiClient:
    """Enterprise client for Google Gemini models with structured JSON schemas.

    Attributes:
        model: Model name string (e.g. 'gemini-2.5-flash').
        mock_mode: If True, uses registered mock responses instead of network calls.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        mock_mode: Optional[bool] = None,
        settings: Optional[Settings] = None,
        http_options: Optional[Dict[str, Any]] = None,
    ):
        cfg = settings or Settings()

        # Determine mock mode: explicit param overrides settings
        if mock_mode is not None:
            self.mock_mode = bool(mock_mode)
        else:
            self.mock_mode = bool(cfg.mock_ai)

        self.model = model or cfg.gemini_model or "gemini-3.5-flash-lite"

        raw_key = api_key or cfg.gemini_api_key or os.getenv("GEMINI_API_KEY", "")
        self._api_key = raw_key.strip() if raw_key else ""

        # Custom mock response handlers (schema_type -> callable or instance)
        self._mock_handlers: Dict[Type[BaseModel], Any] = {}

        self._genai_client = None

        if self.mock_mode:
            logger.info("GeminiClient initialized in EXPLICIT MOCK MODE for model '%s'", self.model)
        else:
            # Live execution requires a valid API key
            if not self._api_key:
                raise GeminiConfigurationError(
                    "GEMINI_API_KEY is not configured. "
                    "Provide a valid API key in .env or initialize GeminiClient with mock_mode=True for offline testing."
                )
            try:
                from google import genai

                client_http_options: Dict[str, Any] = {"api_version": "v1beta"}
                if http_options:
                    client_http_options.update(http_options)

                self._genai_client = genai.Client(
                    api_key=self._api_key,
                    http_options=client_http_options,
                )
                logger.info(
                    "GeminiClient initialized in LIVE MODE for model '%s' (Key: %s, API: v1beta)",
                    self.model,
                    self.masked_api_key(),
                )
            except Exception as exc:
                raise GeminiConfigurationError(f"Failed to initialize Google GenAI SDK: {exc}") from exc

    @property
    def _client(self):
        return self._genai_client

    @_client.setter
    def _client(self, value):
        self._genai_client = value

    def masked_api_key(self) -> str:
        """Return safely masked API key for logging (e.g. 'AIzaSy...4F2d')."""
        if not self._api_key:
            return "[NONE]"
        if len(self._api_key) <= 8:
            return "[PROTECTED]"
        return f"{self._api_key[:6]}...{self._api_key[-4:]}"

    def register_mock_handler(self, schema: Type[T], handler_or_instance: Any) -> None:
        """Register a specific mock handler or default instance for a given schema in mock mode."""
        self._mock_handlers[schema] = handler_or_instance

    def generate_structured(
        self,
        prompt: str,
        response_schema: Type[T],
        system_instruction: Optional[str] = None,
        media_bytes: Optional[bytes] = None,
        media_mime: Optional[str] = None,
    ) -> T:
        """Generate structured output validated against a Pydantic schema.

        Args:
            prompt: Text instruction or content to analyze.
            response_schema: Pydantic model class defining the expected response.
            system_instruction: Optional role instruction.
            media_bytes: Optional raw bytes for multimodal image or PDF verification.
            media_mime: MIME type of media (e.g. 'image/png', 'application/pdf').

        Returns:
            An instance of response_schema.

        Raises:
            GeminiConfigurationError: If misconfigured.
            GeminiTimeoutError: If the call times out.
            GeminiModelNotFoundError: If the model name is unknown.
            GeminiQuotaError: If rate limit exceeded.
            GeminiAPIError: If the service reports an error.
        """
        if self.mock_mode:
            return self._execute_mock(prompt, response_schema)

        return self._execute_live(
            prompt=prompt,
            response_schema=response_schema,
            system_instruction=system_instruction,
            media_bytes=media_bytes,
            media_mime=media_mime,
        )

    # ------------------------------------------------------------------------
    # LIVE EXECUTION
    # ------------------------------------------------------------------------

    def _execute_live(
        self,
        prompt: str,
        response_schema: Type[T],
        system_instruction: Optional[str],
        media_bytes: Optional[bytes],
        media_mime: Optional[str],
    ) -> T:
        if self._client is None and self._genai_client is None:
            raise GeminiConfigurationError("Live GenAI client is not initialized.")

        from google.genai import types
        from google.genai import errors as genai_errors

        # Configure structured JSON output adhering to the Pydantic schema
        config_args: Dict[str, Any] = {
            "response_mime_type": "application/json",
            "response_schema": response_schema,
            "http_options": {"api_version": "v1beta"},
        }
        if system_instruction:
            config_args["system_instruction"] = system_instruction

        config = types.GenerateContentConfig(**config_args)

        # Build contents (text and optional multimodal image/pdf bytes)
        contents = []
        if media_bytes:
            mime = media_mime or "application/octet-stream"
            contents.append(types.Part.from_bytes(data=media_bytes, mime_type=mime))
        contents.append(prompt)

        try:
            max_attempts = 3
            response = None
            for attempt in range(1, max_attempts + 1):
                try:
                    response = self._client.models.generate_content(
                        model=self.model,
                        contents=contents,
                        config=config,
                    )
                    break
                except Exception as exc:
                    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
                    if code is None and hasattr(exc, "response"):
                        code = getattr(exc.response, "status_code", None) or getattr(exc.response, "status", None)
                    try:
                        code_int = int(code) if code is not None else None
                    except (ValueError, TypeError):
                        code_int = None
                    msg = str(exc)
                    is_server_error = (
                        code_int in (500, 502, 503, 504)
                        or bool(re.search(r"\b(500|502|503|504)\b", msg))
                    )
                    if is_server_error and attempt < max_attempts:
                        logger.warning(
                            "Gemini API server error (attempt %d/%d): %s. Retrying in 1s...",
                            attempt,
                            max_attempts,
                            exc,
                        )
                        time.sleep(1)
                        continue
                    raise

            # Response is either parsed directly or available as raw text JSON
            if hasattr(response, "parsed") and response.parsed is not None:
                if isinstance(response.parsed, response_schema):
                    return response.parsed
                if isinstance(response.parsed, dict):
                    return response_schema.model_validate(response.parsed)

            if response.text:
                return response_schema.model_validate_json(response.text)

            raise GeminiAPIError("Gemini returned an empty response with no text or parsed content.")

        except genai_errors.APIError as exc:
            code = getattr(exc, "code", None)
            msg = str(exc)
            if code == 404 or "not found" in msg.lower():
                raise GeminiModelNotFoundError(f"Model '{self.model}' not found or unsupported: {msg}") from exc
            if code == 429 or "quota" in msg.lower() or "resource exhausted" in msg.lower():
                raise GeminiQuotaError(f"Gemini API quota exceeded: {msg}") from exc
            raise GeminiAPIError(f"Gemini API call failed: {msg}", status_code=code) from exc

        except TimeoutError as exc:
            raise GeminiTimeoutError("Gemini API call timed out.") from exc

        except Exception as exc:
            # Handle other client or network errors
            exc_name = type(exc).__name__
            if "timeout" in exc_name.lower():
                raise GeminiTimeoutError(f"Gemini request timed out: {exc}") from exc
            raise GeminiAPIError(f"Unexpected error during Gemini execution ({exc_name}): {exc}") from exc

    # ------------------------------------------------------------------------
    # EXPLICIT MOCK EXECUTION
    # ------------------------------------------------------------------------

    def _execute_mock(self, prompt: str, response_schema: Type[T]) -> T:
        """Deterministic mock generation for unit tests and offline evaluation."""
        logger.debug("Generating explicit mock response for %s", response_schema.__name__)

        # Check for user-registered mock handlers
        if response_schema in self._mock_handlers:
            handler = self._mock_handlers[response_schema]
            if callable(handler):
                return handler(prompt)
            if isinstance(handler, response_schema):
                return handler

        # Build sensible deterministic fallback instances for each schema
        return self._build_default_mock(prompt, response_schema)

    def _build_default_mock(self, prompt: str, schema: Type[T]) -> T:
        from app.ai.schemas import (
            BrandFinding,
            BrandVerificationOutput,
            ClaimFinding,
            ClaimVerificationOutput,
            ContentUnderstandingOutput,
            CorrectionOutput,
            ExtractedClaim,
            GovernanceInsightsOutput,
            PreservedEntity,
            RecurringViolation,
            VisualAccessibilityOutput,
        )

        sample_passage = prompt[:80].strip() if prompt else "Sample draft submission text"

        if schema == ContentUnderstandingOutput:
            return schema(
                summary="Synthesized analysis of submitted brand material.",
                target_audience="General enterprise stakeholders and prospective customers.",
                purpose="Product launch communications and positioning.",
                tone="Professional and confident with promotional highlights.",
                intended_message="Deliver verifiable value through reliable performance.",
                claims=[
                    ExtractedClaim(
                        claim_id="claim-1",
                        text="Our platform accelerates workflow compliance by 40%.",
                        claim_type="fact",
                        passage="accelerates workflow compliance by 40%",
                        location="paragraph 1",
                    ),
                    ExtractedClaim(
                        claim_id="claim-2",
                        text="We offer the best collaboration tools available.",
                        claim_type="opinion",
                        passage="the best collaboration tools available",
                        location="paragraph 1",
                    ),
                ],
                preserved_entities=[
                    PreservedEntity(
                        entity_type="metric",
                        text="40%",
                        context="accelerates workflow compliance by 40%",
                    ),
                    PreservedEntity(
                        entity_type="date",
                        text="2026",
                        context="Launched in Q4 2026",
                    ),
                ],
            )

        if schema == BrandVerificationOutput:
            return schema(
                overall_alignment="potential_issue",
                voice_and_tone_assessment="Tone is generally professional, but includes exaggerated buzzwords.",
                terminology_assessment="Phrasing 'disruptive synergy' conflicts with plain-English communication.",
                visual_brand_assessment="Typography matches primary sans-serif guidelines.",
                findings=[
                    BrandFinding(
                        state="potential_issue",
                        passage="disruptive synergy",
                        location="paragraph 1",
                        violation_category="buzzword",
                        explanation="Corporate buzzword conflicts with our plain-language communication standard.",
                        why_it_matters="Clear terminology builds credibility across enterprise decision makers.",
                        guideline_document="Brand Identity Playbook v2.1",
                        guideline_section="Section 1.3",
                        guideline_excerpt="Use clear, plain English and avoid buzzwords that obscure capabilities.",
                        suggested_fix="effective collaboration",
                        uncertainty_note=None,
                    )
                ],
            )

        if schema == ClaimVerificationOutput:
            return schema(
                findings=[
                    ClaimFinding(
                        claim_text="Delivers 99.99% uptime with zero maintenance windows.",
                        passage="99.99% uptime with zero maintenance windows",
                        location="paragraph 2",
                        state="insufficient_evidence",
                        explanation="No SLA report or audited infrastructure status was retrieved to substantiate zero maintenance windows.",
                        why_it_matters="Unsubstantiated uptime promises introduce commercial warranty liabilities.",
                        evidence_source_url="https://status.example.com",
                        evidence_excerpt="Scheduled maintenance windows occur monthly.",
                        evidence_quality="conflicting",
                        uncertainty_note="Evidence reports maintenance exclusions exist.",
                        suggested_fix="targeted high availability with transparent maintenance schedules",
                    )
                ]
            )

        if schema == CorrectionOutput:
            return schema(
                flag_id="mock-flag-1",
                original_passage="disruptive synergy",
                suggested_replacement="effective collaboration",
                change_rationale="Replaces corporate buzzword with plain-English equivalent while preserving intent.",
                entities_preserved=[],
                recheck_passed=True,
                recheck_notes="Simulated verification confirms clean voice alignment.",
            )

        if schema == VisualAccessibilityOutput:
            return schema(
                has_visual_content=True,
                detected_logos=["Inkloom AI mark"],
                color_palette=["#1E293B", "#3B82F6", "#FFFFFF"],
                visual_consistency_score="high",
                visual_brand_alignment="aligned",
                visual_brand_notes="Balanced layout adhering to core color hierarchy.",
                accessibility_issues=[],
            )

        if schema == GovernanceInsightsOutput:
            return schema(
                total_reviews_analyzed=12,
                top_recurring_violations=[
                    RecurringViolation(
                        rule_or_topic="Unsubstantiated performance superlatives",
                        frequency=5,
                        severity="high",
                        guideline_reference="Commercial Compliance Standard Section 2.1",
                        recommendation="Require authors to link verified benchmark reports before claiming top market rankings.",
                    )
                ],
                ambiguous_guidelines=[],
                summary_narrative="Overall brand compliance has improved; performance superlatives remain the most common violation.",
            )

        # Fallback empty construction
        return schema()

