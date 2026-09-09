"""Records passed between Agent 3's blocks.

Stdlib dataclasses are used so this runs with no third-party dependency. The
project standard is Pydantic v2; swapping is mechanical and confined to this
file (replace @dataclass with BaseModel, keep the field names). Field names are
the contract, not the base class.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from typing import Any


# --------------------------------------------------------------------------
# Enumerations, kept as string constants so artifacts stay JSON-plain
# --------------------------------------------------------------------------

DIMENSIONS = {
    "D1": "Visibility",
    "D2": "Terminal outcome",
    "D3": "Validation (explicit)",
    "D4": "Validation (mandatory)",
    "D5": "Option-source dependency",
    "D6": "Text-pipe dependency",
    "D7": "Randomization configuration",
    "D8": "Quota cell state",
    "D9": "Interaction",
}

# Enumeration status for a whole dimension
EXHAUSTIVE = "EXHAUSTIVE"
BOUNDED = "BOUNDED"
PARTIAL = "PARTIAL"
UNKNOWN = "UNKNOWN"

# Per-target uncovered reasons. Each means exactly one thing and they are never
# used interchangeably (architecture doc, section 9).
INFEASIBLE = "INFEASIBLE"
BOUND_REACHED = "BOUND_REACHED"
UNRESOLVED_DECISION = "UNRESOLVED_DECISION"
UNSUPPORTED = "UNSUPPORTED"
NOT_IN_IMPLEMENTATION = "NOT_IN_IMPLEMENTATION"
UNVERIFIABLE = "UNVERIFIABLE"
QUOTA_SIZE_UNDEFINED = "QUOTA_SIZE_UNDEFINED"
RANDOMIZATION_ANCHOR_UNDEFINED = "RANDOMIZATION_ANCHOR_UNDEFINED"

COVERED = "COVERED"
UNCOVERED = "UNCOVERED"


def stable_id(prefix: str, payload: Any) -> str:
    """Content-derived id: unchanged content keeps its id across runs."""
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return f"{prefix}-{hashlib.sha256(blob.encode()).hexdigest()[:10]}"


# --------------------------------------------------------------------------
# B1 output
# --------------------------------------------------------------------------

@dataclass
class CoverageTarget:
    """One behaviour that can be proven true or false.

    A target is a claim about the survey, not a test. The test that
    demonstrates it is produced later, and one target yields at most one
    verified scenario.
    """

    target_id: str
    dimension: str                 # D1..D9
    subject: str                   # the question / disposition / quota cell it concerns
    polarity: str                  # e.g. "shown" / "hidden", "satisfied" / "violated"
    claim: str                     # plain-English statement of what must be shown
    traces_to: list[str] = field(default_factory=list)   # rule ids / spec paths
    predetermined_reason: str | None = None  # set when B1 already knows it cannot be attempted
    notes: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------
# B2 output
# --------------------------------------------------------------------------

@dataclass
class Witness:
    """A minimal respondent answer-set that should reach a target.

    `answers` maps question id to the answer as the respondent would give it:
    a single option id, a list of option ids, a number, or a string.
    """

    target_id: str
    feasible: bool
    answers: dict[str, Any] = field(default_factory=dict)
    method: str = "unattempted"    # how feasibility was decided
    evidence: str = ""
    reason: str | None = None      # populated when feasible is False
    # Some behaviours cannot be reached by one respondent. Filling a quota cell
    # needs a run-up of earlier respondents, so the witness carries the recipe
    # for that run-up rather than pretending one journey is enough.
    preconditions: dict = field(default_factory=dict)
    campaign: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------
# B3 output
# --------------------------------------------------------------------------

@dataclass
class ExpectedState:
    """What the survey should do, computed independently of how B2 found the witness.

    B3 never receives the target. It receives only an answer-set and the spec.
    """

    witness_target_id: str
    shown: list[str] = field(default_factory=list)
    hidden: list[str] = field(default_factory=list)
    validation_triggered: list[dict] = field(default_factory=list)
    ending: str | None = None
    path: list[str] = field(default_factory=list)
    piped_text: dict[str, str] = field(default_factory=dict)
    piped_options: dict[str, list[str]] = field(default_factory=dict)
    unresolved: list[str] = field(default_factory=list)
    fired_rules: list[str] = field(default_factory=list)
    blocked_at: str | None = None
    quota_stopped: str | None = None
    semantics_used: list[str] = field(default_factory=list)
    observable: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------
# B4 output
# --------------------------------------------------------------------------

@dataclass
class VerifiedScenario:
    """B4's ruling: does this witness plus this predicted state prove the target?"""

    scenario_id: str
    target_id: str
    dimension: str
    status: str                    # COVERED / UNCOVERED
    reason: str | None = None      # controlled reason when UNCOVERED
    answers: dict[str, Any] = field(default_factory=dict)
    expected: dict[str, Any] = field(default_factory=dict)
    proof: str = ""                # what specifically demonstrates the target
    provisional_semantics: list[str] = field(default_factory=list)
    preconditions: dict = field(default_factory=dict)
    campaign: dict = field(default_factory=dict)
    # Set when another test already proves this behaviour, so no separate run
    # is needed. Recorded explicitly rather than folded silently into COVERED.
    covered_by: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------
# Logical test case (pre-Block C: no physical identifiers)
# --------------------------------------------------------------------------

@dataclass
class LogicalTestCase:
    """A test expressed entirely in canonical identifiers.

    This is deliberately NOT executable. Turning Q5 into a LimeSurvey SGQA
    field address is Block C's job and needs Agent 2's build manifest, which
    does not exist yet. Emitting these now means the logical design is complete
    and reviewable before the physical layer arrives.
    """

    test_id: str
    target_id: str
    dimension: str
    title: str
    steps: list[dict] = field(default_factory=list)
    assertions: list[dict] = field(default_factory=list)
    traces_to: list[str] = field(default_factory=list)
    executable: bool = False
    non_executable_reason: str = "NO_BUILD_MANIFEST"
    provisional_semantics: list[str] = field(default_factory=list)
    campaign: dict = field(default_factory=dict)

    # Set by the compiler: the answers needed only to reach the question under
    # test, versus the action the test is actually about.
    setup: list[dict] = field(default_factory=list)
    action: list[dict] = field(default_factory=list)
    action_text: str = ""
    focus: str | None = None
    blocks: bool = False

    def to_dict(self) -> dict:
        return asdict(self)
