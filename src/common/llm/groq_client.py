"""Shared Groq client — the single place agent prompts reach an LLM.

Every prompt module under `src/common/prompts/` must call this client rather than
instantiating the provider SDK itself, so the runtime can be audited,
rate-limited and swapped from one place (CLAUDE.md §52).

Deviation on record. CLAUDE.md §52 names Azure OpenAI as the sponsor-approved
runtime. Groq is wired here at the explicit direction of the project team, per
the Step 2 / 5 / 7 tech stack in the agent specification. The §52 *principle* —
one shared, auditable, swappable client — is preserved, so replacing this module
with `azure_client.py` later requires no change to any calling step. See
docs/decisions/ for the logged decision.

Confidentiality note. Only the minimum text a step needs classified is sent —
Step 2 sends heading text and a label vocabulary, never document bodies or
respondent data. Callers are responsible for keeping payloads minimal; this
client does not inspect or redact what it is given.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ..config import GroqSettings, get_settings

logger = logging.getLogger(__name__)


class LLMUnavailableError(RuntimeError):
    """Raised when the client cannot be constructed — missing SDK or key.

    Distinct from a call failure: this means the runtime was never usable, so
    the caller should fall back to deterministic behaviour rather than retry.
    """


class LLMCallError(RuntimeError):
    """Raised when a request was attempted but did not return usable output."""


class GroqClient:
    """Thin wrapper over the Groq chat-completions API.

    Kept deliberately small: one JSON-returning classification method is all the
    current steps need. Resist growing this into a general-purpose LLM facade —
    add a method when a step actually requires it.
    """

    def __init__(self, settings: GroqSettings | None = None) -> None:
        self._settings = settings or get_settings().groq

        if not self._settings.is_configured:
            raise LLMUnavailableError(
                "GROQ_API_KEY is not set. Copy .env.example to .env and add your "
                "key, or set LLM_PROVIDER=none to run deterministically."
            )

        try:
            from groq import Groq
        except ImportError as exc:  # pragma: no cover - depends on install state
            raise LLMUnavailableError(
                "The 'groq' package is not installed. Run: pip3 install -r requirements.txt"
            ) from exc

        self._client = Groq(
            api_key=self._settings.api_key,
            timeout=float(self._settings.timeout_seconds),
            max_retries=self._settings.max_retries,
        )

    @property
    def model(self) -> str:
        return self._settings.model

    def complete_json(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float = 0.0,
    ) -> dict[str, Any]:
        """Send one chat request and parse the reply as a JSON object.

        Uses Groq's JSON response mode and temperature 0, so the same input
        yields the same label — a reproducibility requirement, not a preference
        (CLAUDE.md §50).

        Args:
            system_prompt: role/instruction text.
            user_prompt:   the specific item to act on.
            temperature:   sampling temperature; leave at 0 for classification.

        Returns:
            The parsed JSON object.

        Raises:
            LLMCallError: the request failed, returned nothing, or returned
                content that was not a JSON object.
        """
        try:
            response = self._client.chat.completions.create(
                model=self._settings.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=temperature,
                response_format={"type": "json_object"},
            )
        except Exception as exc:
            # Message only — never include the payload, which may hold client
            # material, or the key (CLAUDE.md §55).
            raise LLMCallError(f"Groq request failed: {type(exc).__name__}: {exc}") from exc

        if not response.choices:
            raise LLMCallError("Groq returned no choices.")

        content = response.choices[0].message.content
        if not content:
            raise LLMCallError("Groq returned empty content.")

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise LLMCallError(f"Groq returned non-JSON content: {exc}") from exc

        if not isinstance(parsed, dict):
            raise LLMCallError(f"Expected a JSON object, got {type(parsed).__name__}.")

        return parsed


def build_client(settings: GroqSettings | None = None) -> GroqClient | None:
    """Construct a GroqClient, or return None when the LLM is unavailable.

    Convenience for callers that must degrade to deterministic behaviour rather
    than fail. Logs the reason at INFO so a run's log explains why no model was
    used (CLAUDE.md §55).
    """
    try:
        return GroqClient(settings)
    except LLMUnavailableError as exc:
        logger.info("LLM disabled: %s", exc)
        return None
