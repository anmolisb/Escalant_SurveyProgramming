"""Test-session configuration.

The pipeline steps now default to using the project's configured LLM, so calling
`detect_sections(doc)` with a key in `.env` would make a real API call. That is
correct for the application and wrong for the tests: a suite that reaches the
network is slow, costs money, fails offline, and stops being deterministic.

Forcing `LLM_PROVIDER=none` for the whole session keeps every test on the
deterministic path by default. Tests that need to exercise the model path inject
their own stub explicitly, which is both faster and more precise than calling a
real one.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# Set before any test imports the settings loader, and override rather than
# setdefault: a developer with LLM_PROVIDER exported in their shell must still
# get a hermetic test run.
os.environ["LLM_PROVIDER"] = "none"
os.environ["GROQ_API_KEY"] = ""

from common.config import get_settings  # noqa: E402

# The loader caches, so clear anything a previous import may have cached under
# the developer's real settings.
get_settings.cache_clear()

assert not get_settings().llm_enabled, (
    "tests must run with the LLM disabled; check tests/conftest.py"
)
