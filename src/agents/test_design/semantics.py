"""Survey-wide reading rules, treated as configuration rather than code.

Agent 1's canonical spec carries a `semantics` block with the survey-wide
reading rules it had to settle, and `agent1_decisions.json` carries the
register saying which of those a human still has to confirm. On C01 three are
BLOCKING and PENDING_CONFIRMATION:

  unasked_question_semantics   condition naming an unasked question
  rule_precedence              which rule wins when two match
  multi_select_equality        what == means on a multi-select

These are not run-time blockers only. B3's interpreter cannot be written
without them: every one is an input to its core loop. So they are read from
Agent 1's own artifacts, never hardcoded, and every scenario that leaned on a
still-provisional reading is tagged. When the owner rules differently, Agent 3
regenerates instead of being rewritten.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


# Agent 1's key names, and the readings Agent 3 understands.
UNASKED = "unasked_reference"
PRECEDENCE = "rule_precedence"
MULTI_EQ = "multi_equality"

# Does an answer of spaces alone satisfy a compulsory question? No
# questionnaire we have seen says. The reading matters: if spaces count as an
# answer, a respondent who taps the space bar produces a response with nothing
# in it and the data is quietly lost. LimeSurvey does not trim, so on a real
# build spaces DO count, which means a test asserting otherwise is a test the
# build is expected to fail. That is worth knowing rather than assuming either
# way, so it is recorded here with the other unconfirmed readings.
WHITESPACE = "whitespace_is_an_answer"
MANDATORY = "default_mandatory"

KEYS = (UNASKED, PRECEDENCE, MULTI_EQ, MANDATORY, WHITESPACE)

# Which decision-register `issue` string corresponds to which semantics key.
ISSUE_TO_KEY = {
    "unasked_question_semantics": UNASKED,
    "rule_precedence": PRECEDENCE,
    "multi_select_equality": MULTI_EQ,
    "multi_equality": MULTI_EQ,
    "whitespace_is_an_answer": WHITESPACE,
}

FALLBACK = {
    UNASKED: "condition_false",
    PRECEDENCE: "document_order_first_match",
    MULTI_EQ: "set_equality",
    WHITESPACE: "not_an_answer",
    MANDATORY: True,
}


@dataclass
class Semantics:
    values: dict = field(default_factory=lambda: dict(FALLBACK))
    origins: dict = field(default_factory=dict)
    provisional: set = field(default_factory=set)
    blocking: set = field(default_factory=set)
    register_entries: dict = field(default_factory=dict)

    # ----- construction ---------------------------------------------------

    @classmethod
    def load(cls, canonical_raw: dict, decisions_path: str | Path | None = None
             ) -> "Semantics":
        block = (canonical_raw.get("content") or {}).get("semantics") or {}

        values, origins, provisional = {}, {}, set()
        for key in KEYS:
            if key in block and block[key] is not None:
                values[key] = block[key]
                origins[key] = str(block.get(f"{key}_origin") or "unknown")
            else:
                values[key] = FALLBACK[key]
                origins[key] = "agent3_fallback"
                provisional.add(key)

            # An inferred or ambiguous origin is not a confirmed reading.
            if origins[key] in ("inferred", "ambiguous", "unknown", "agent3_fallback"):
                provisional.add(key)

        blocking: set = set()
        entries: dict = {}
        if decisions_path:
            p = Path(decisions_path)
            if p.exists():
                reg = json.loads(p.read_text(encoding="utf-8"))
                for entry in (reg.get("entries") or {}).values():
                    key = ISSUE_TO_KEY.get(str(entry.get("issue")))
                    if key is None:
                        continue
                    entries[key] = entry
                    status = str(entry.get("status") or "").upper()
                    severity = str(entry.get("severity") or "").upper()
                    if status == "RESOLVED":
                        provisional.discard(key)
                        if entry.get("decision"):
                            values[key] = entry["decision"]
                            origins[key] = "human_confirmed"
                    elif status != "NOT_REQUIRED":
                        provisional.add(key)
                        if severity == "BLOCKING":
                            blocking.add(key)

        return cls(values=values, origins=origins, provisional=provisional,
                   blocking=blocking, register_entries=entries)

    # ----- accessors used by B3 ------------------------------------------

    @property
    def unasked_is(self) -> str:
        """`condition_false`, `condition_true`, or anything else -> unresolved."""
        return str(self.values.get(UNASKED))

    @property
    def precedence(self) -> str:
        return str(self.values.get(PRECEDENCE))

    @property
    def multi_eq_is_exact_set(self) -> bool:
        return str(self.values.get(MULTI_EQ)) in ("set_equality", "exact_set")

    @property
    def default_mandatory(self) -> bool:
        return bool(self.values.get(MANDATORY, True))

    def tags(self, used: set) -> list[str]:
        """Which still-provisional readings a scenario actually leaned on."""
        return sorted(k for k in used if k in self.provisional)

    @property
    def all_resolved(self) -> bool:
        return not self.provisional

    def summary(self) -> dict:
        return {
            key: {
                "value": self.values.get(key),
                "origin": self.origins.get(key, "unknown"),
                "status": "PROVISIONAL" if key in self.provisional else "CONFIRMED",
                "blocking": key in self.blocking,
                "decision_id": (self.register_entries.get(key) or {}).get("decision_id"),
            }
            for key in KEYS
        }
