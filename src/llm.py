"""instructor-patched Groq client. The only module that touches a provider SDK.

Not a stage — shared infrastructure for the three stages permitted to call an LLM
(Stage 2 shape-matching, Stage 3 prose extraction, Stage 4 field splitting and
condition translation).
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from functools import lru_cache
from pathlib import Path
from typing import TypeVar

import instructor
from groq import Groq
from pydantic import BaseModel

REPO_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = REPO_ROOT / ".env"

DEFAULT_MODEL = "openai/gpt-oss-120b"

#: Structured replies here are small — a handful of fields. Kept tight because
#: Groq counts the *requested* max_tokens against the tokens-per-minute budget,
#: so an oversized cap throttles the run without buying anything.
MAX_TOKENS = 800

#: Concurrent in-flight calls. Stage 4 gathers one call per question, which on a
#: 30-question QRE saturates the rate limit instantly; this bounds it.
MAX_CONCURRENCY = 2

#: How many times to wait out a rate limit before giving up.
MAX_RATE_LIMIT_RETRIES = 6

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class LLMUnavailable(RuntimeError):
    """No usable API key. Raised rather than silently degrading."""


def _load_env() -> None:
    """Read .env into the environment without overriding real variables."""
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip("\"'")
        if value and not os.environ.get(key):
            os.environ[key] = value


@lru_cache(maxsize=1)
def get_client() -> instructor.Instructor:
    _load_env()
    api_key = os.environ.get("GROQ_API_KEY", "")
    if not api_key:
        raise LLMUnavailable(
            "GROQ_API_KEY is not set. Copy .env.example to .env and add your key."
        )
    return instructor.from_groq(Groq(api_key=api_key), mode=instructor.Mode.JSON)


def get_model() -> str:
    _load_env()
    return os.environ.get("GROQ_MODEL") or DEFAULT_MODEL


#: Seconds to wait when the provider reports a rate limit but names no delay.
_FALLBACK_BACKOFF = 5.0
_RETRY_AFTER = re.compile(r"try again in ([\d.]+)s")


def _rate_limit_delay(error: Exception) -> float | None:
    """Seconds to wait for a rate-limit error, or None if it is not one.

    The provider states the exact wait in its message, so honour that rather
    than guessing — a fixed sleep either wastes time or retries too early.
    """
    message = str(error)
    if "rate_limit" not in message and "429" not in message:
        return None
    match = _RETRY_AFTER.search(message)
    return float(match.group(1)) + 0.5 if match else _FALLBACK_BACKOFF


def complete(system: str, user: str, response_model: type[T]) -> T:
    """One structured call. Temperature 0, validated into `response_model`.

    Retries on rate limiting only. Any other failure is raised: a malformed
    response means the prompt or schema needs fixing, and retrying hides that.
    """
    last: Exception | None = None
    for _attempt in range(MAX_RATE_LIMIT_RETRIES + 1):
        try:
            return get_client().chat.completions.create(
                model=get_model(),
                response_model=response_model,
                temperature=0,
                max_tokens=MAX_TOKENS,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
        except Exception as exc:
            delay = _rate_limit_delay(exc)
            if delay is None:
                raise
            last = exc
            logger.info("Rate limited; waiting %.1fs", delay)
            time.sleep(delay)
    raise RuntimeError(f"Rate limited after {MAX_RATE_LIMIT_RETRIES} retries: {last}")


_semaphore: "asyncio.Semaphore | None" = None


def _get_semaphore() -> asyncio.Semaphore:
    """One semaphore per event loop, created lazily inside the running loop."""
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
    return _semaphore


async def complete_async(system: str, user: str, response_model: type[T]) -> T:
    """Async wrapper so Stage 4 can gather calls, bounded by MAX_CONCURRENCY."""
    async with _get_semaphore():
        return await asyncio.to_thread(complete, system, user, response_model)
