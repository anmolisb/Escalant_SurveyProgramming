"""instructor-patched Groq client. The only module that touches a provider SDK.

Not a stage — shared infrastructure for the three stages permitted to call an LLM
(Stage 2 shape-matching, Stage 3 prose extraction, Stage 4 field splitting and
condition translation).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import threading
import time
import weakref
from datetime import datetime, timezone
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
#: The provider writes the wait as "1.4775s", "97.499999ms" or "2m41.567999999s".
#: Reading only the seconds form meant a wait stated in minutes fell through to
#: the flat fallback, so a request needing three minutes was retried after five
#: seconds and failed six times in a row.
_RETRY_AFTER = re.compile(
    r"try again in (?:(?P<minutes>[\d.]+)m)?(?P<seconds>[\d.]+)(?P<unit>ms|s)\b"
)


class DailyQuotaExhausted(LLMUnavailable):
    """The day's token budget is gone. Waiting will not help until it resets.

    A kind of LLMUnavailable on purpose. Every stage already degrades gracefully
    when the model cannot be reached — raising something they do not catch would
    turn a known limit into a crash halfway through a corpus run.
    """


def _is_daily_quota(message: str) -> bool:
    """Whether a rate-limit message is the per-day cap rather than per-minute.

    Worth separating. A per-minute limit clears in seconds and retrying is
    exactly right; a per-day limit clears at midnight, so the same retry loop
    burns its attempts on calls that cannot succeed and then reports a generic
    failure that reads like a transient blip.
    """
    lowered = message.lower()
    return "tokens per day" in lowered or "(tpd)" in lowered


def _is_empty_completion(message: str) -> bool:
    """Whether a schema failure is really the model having returned nothing.

    Groq reports a truncated or empty completion as `json_validate_failed`, the
    same code it uses for genuinely malformed JSON, and the two need opposite
    handling: malformed JSON means the prompt or schema is wrong and retrying
    hides that, while an empty completion means the token budget was squeezed
    and retrying is the whole fix. They are told apart by `failed_generation`,
    which holds the offending text in the first case and nothing in the second.
    """
    return "json_validate_failed" in message and (
        "'failed_generation': ''" in message or '"failed_generation": ""' in message
    )


def _rate_limit_delay(error: Exception) -> float | None:
    """Seconds to wait for a rate-limit error, or None if it is not one.

    The provider states the exact wait in its message, so honour that rather
    than guessing — a fixed sleep either wastes time or retries too early.
    """
    message = str(error)
    if "rate_limit" not in message and "429" not in message:
        return None
    match = _RETRY_AFTER.search(message)
    if not match:
        return _FALLBACK_BACKOFF
    seconds = float(match.group("seconds"))
    if match.group("unit") == "ms":
        seconds /= 1000.0
    if match.group("minutes"):
        seconds += float(match.group("minutes")) * 60.0
    return seconds + 0.5


# ---------------------------------------------------------------------------
# The decision record
# ---------------------------------------------------------------------------

#: Where this run records what the model answered, or None to call every time.
_CACHE_PATH: Path | None = None
_CACHE: dict | None = None
#: Stage 4 runs its calls on worker threads, so two of them can finish at once.
#: Without this the dict is written and the file rewritten from two threads at
#: the same time, which loses an entry or truncates the file.
_CACHE_LOCK = threading.Lock()

CACHE_ARTIFACT = "llm_decisions.json"


def use_cache(directory: Path | None) -> Path | None:
    """Record every model answer for one document, and reuse it on a re-run.

    Temperature 0 is not determinism. The same prompt on the same model returned
    a different answer on three consecutive runs of C01: the wording of Q21 was
    read as quoting Q19 twice and not the third time, and the prose condition on
    R8 was declined once and accepted twice. Each of those changes which
    questions a respondent sees, so a specification built from them is not
    stable, and a test built on top of it cannot be told from a test built on
    top of a different reading of the same document.

    So the answers are written down. A question that has been decided once stays
    decided, and the file says what was decided and from what - which makes the
    inferred parts of a specification reviewable in a way a fresh call never is.

    The key covers the model, the prompt and the schema, so changing any of them
    asks again rather than reusing an answer to a different question. Editing
    the QRE changes the prompt and so re-asks by itself.

    Set `QRE_LLM_CACHE=off` to bypass, for deliberately re-asking everything.
    """
    global _CACHE_PATH, _CACHE
    _load_env()
    if directory is None or os.environ.get("QRE_LLM_CACHE", "").lower() == "off":
        _CACHE_PATH, _CACHE = None, None
        return None

    _CACHE_PATH = Path(directory) / CACHE_ARTIFACT
    _CACHE = {"entries": {}}
    if _CACHE_PATH.exists():
        try:
            loaded = json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded.get("entries"), dict):
                _CACHE = loaded
        except (ValueError, OSError) as exc:
            # A damaged record is not a reason to stop. Say so and re-ask.
            logger.warning("Ignoring unreadable decision record: %s", exc)
    return _CACHE_PATH


def _cache_key(system: str, user: str, response_model: type[T], max_tokens) -> str:
    digest = hashlib.sha256()
    for part in (
        get_model(),
        response_model.__name__,
        str(max_tokens or MAX_TOKENS),
        system,
        user,
    ):
        digest.update(part.encode("utf-8"))
        digest.update(b"\x00")
    return digest.hexdigest()


def _cache_read(key: str, response_model: type[T]) -> T | None:
    if _CACHE is None:
        return None
    with _CACHE_LOCK:
        entry = _CACHE["entries"].get(key)
    if not entry:
        return None
    try:
        return response_model.model_validate(entry["response"])
    except Exception as exc:
        # The schema has moved on since this was recorded. Ask again rather than
        # forcing an old shape into a new model.
        logger.info("Recorded answer no longer fits %s: %s", response_model.__name__, exc)
        return None


def _cache_write(key: str, user: str, response_model: type[T], value: T) -> None:
    if _CACHE is None or _CACHE_PATH is None:
        return
    with _CACHE_LOCK:
        _CACHE["entries"][key] = {
            # Enough context to read the file and see what was decided about
            # what, without having to re-run anything to find out.
            "response_model": response_model.__name__,
            "model": get_model(),
            "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "asked": user if len(user) <= 400 else user[:400] + " ...",
            "response": value.model_dump(mode="json"),
        }
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_PATH.write_text(
            json.dumps(_CACHE, indent=2, default=str), encoding="utf-8"
        )


def complete(
    system: str, user: str, response_model: type[T], max_tokens: int | None = None
) -> T:
    """One structured call. Temperature 0, validated into `response_model`.

    Retries on rate limiting only. Any other failure is raised: a malformed
    response means the prompt or schema needs fixing, and retrying hides that.

    `max_tokens` overrides the default for a single call. Almost nothing needs
    it: the default is deliberately tight because Groq counts the requested cap
    against the rate budget, so an oversized cap throttles every other call
    without buying anything. A schema returning a list of objects is the
    exception - it can legitimately need more room than a handful of fields, and
    running out shows up as an empty completion rather than as a clear error.
    """
    key = _cache_key(system, user, response_model, max_tokens)
    recorded = _cache_read(key, response_model)
    if recorded is not None:
        return recorded

    last: Exception | None = None
    for _attempt in range(MAX_RATE_LIMIT_RETRIES + 1):
        try:
            answer = get_client().chat.completions.create(
                model=get_model(),
                response_model=response_model,
                temperature=0,
                max_tokens=max_tokens or MAX_TOKENS,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
            _cache_write(key, user, response_model, answer)
            return answer
        except Exception as exc:
            if _is_daily_quota(str(exc)):
                # Fail now rather than sleeping through five more attempts that
                # cannot succeed, and say plainly why, because "rate limited"
                # alone sends the reader looking for a transient problem.
                raise DailyQuotaExhausted(
                    "The provider's daily token budget is used up. Retrying will "
                    "not help until it resets. Reduce the work, wait for the "
                    f"reset, or raise the quota. Provider said: {exc}"
                ) from exc
            delay = _rate_limit_delay(exc)
            if delay is None and _is_empty_completion(str(exc)):
                # Nothing came back at all. Give the budget a moment to free up
                # rather than reporting this as a schema problem, which is what
                # the provider's error code says and what it is not.
                delay = _FALLBACK_BACKOFF
                logger.info("Empty completion; retrying in %.1fs", delay)
            if delay is None:
                raise
            last = exc
            logger.info("Rate limited; waiting %.1fs", delay)
            time.sleep(delay)
    raise RuntimeError(f"Rate limited after {MAX_RATE_LIMIT_RETRIES} retries: {last}")


#: Keyed by event loop, because an asyncio primitive binds to the loop it is
#: first awaited on. A single module-level semaphore worked only while the
#: process ran one loop: a second `asyncio.run` — a test suite, or two documents
#: in one process — inherited the first loop's semaphore and raised
#: "is bound to a different event loop". Weak keys so a finished loop does not
#: keep its semaphore alive.
_semaphores: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore]" = (
    weakref.WeakKeyDictionary()
)


def _get_semaphore() -> asyncio.Semaphore:
    """One semaphore per event loop, created lazily inside the running loop."""
    loop = asyncio.get_running_loop()
    semaphore = _semaphores.get(loop)
    if semaphore is None:
        semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
        _semaphores[loop] = semaphore
    return semaphore


async def complete_async(
    system: str, user: str, response_model: type[T], max_tokens: int | None = None
) -> T:
    """Async wrapper so Stage 4 can gather calls, bounded by MAX_CONCURRENCY."""
    async with _get_semaphore():
        return await asyncio.to_thread(
            complete, system, user, response_model, max_tokens
        )
