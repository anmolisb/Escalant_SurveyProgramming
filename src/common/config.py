"""Configuration loading — reads `.env`, exposes typed settings.

Secrets come from the environment or a local, gitignored `.env` file. Nothing in
this module ever logs or prints a key value (CLAUDE.md §51, §55).

Precedence: a real environment variable always wins over a `.env` entry, so CI
and shell exports override the local file without editing it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = REPO_ROOT / ".env"

PROVIDER_GROQ = "groq"
PROVIDER_NONE = "none"


def _parse_env_file(path: Path) -> dict[str, str]:
    """Parse a KEY=value file. Supports comments, blank lines, quoted values.

    Deliberately hand-rolled rather than pulling in python-dotenv: the format we
    use is a dozen lines of parsing, and one less dependency handling secrets is
    one less thing to audit.
    """
    values: dict[str, str] = {}
    if not path.exists():
        return values

    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        # Strip matching surrounding quotes, if present.
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def _get(key: str, default: str = "") -> str:
    """Read a setting: real environment first, then `.env`, then default."""
    from_env = os.environ.get(key)
    if from_env is not None and from_env != "":
        return from_env
    return _parse_env_file(ENV_FILE).get(key, default) or default


def _get_int(key: str, default: int) -> int:
    try:
        return int(_get(key, str(default)))
    except ValueError:
        return default


@dataclass(frozen=True)
class GroqSettings:
    """Groq connection settings.

    `api_key` is held in memory only. `__repr__` is overridden so the key cannot
    leak into a log line, traceback or debugger dump.
    """

    api_key: str
    model: str
    timeout_seconds: int
    max_retries: int

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    def __repr__(self) -> str:  # pragma: no cover - trivial
        state = "set" if self.api_key else "missing"
        return (
            f"GroqSettings(api_key=<{state}>, model={self.model!r}, "
            f"timeout_seconds={self.timeout_seconds}, max_retries={self.max_retries})"
        )


@dataclass(frozen=True)
class Settings:
    """Top-level application settings."""

    llm_provider: str
    groq: GroqSettings

    @property
    def llm_enabled(self) -> bool:
        """True only when a provider is selected AND its credentials exist.

        Callers use this to decide whether to pass a classifier into a step. A
        provider selected without a key is treated as disabled rather than
        raising, so the deterministic pipeline still runs end to end.
        """
        if self.llm_provider == PROVIDER_GROQ:
            return self.groq.is_configured
        return False


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load settings once per process.

    Cached so repeated calls do not re-read `.env`. Tests that need to change
    the environment mid-run should call `get_settings.cache_clear()`.
    """
    return Settings(
        llm_provider=_get("LLM_PROVIDER", PROVIDER_NONE).strip().lower(),
        groq=GroqSettings(
            api_key=_get("GROQ_API_KEY"),
            # Default chosen by benchmarking every model available on the
            # project's Groq account against the Step 2 classification task —
            # see docs/decisions/0001-groq-as-interim-llm-runtime.md.
            model=_get("GROQ_MODEL", "qwen/qwen3.6-27b"),
            timeout_seconds=_get_int("GROQ_TIMEOUT_SECONDS", 30),
            max_retries=_get_int("GROQ_MAX_RETRIES", 2),
        ),
    )
