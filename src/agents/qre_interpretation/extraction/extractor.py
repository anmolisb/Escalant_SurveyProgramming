"""Detection primitives for the QRE Reader.

Each function here answers one narrow, deterministic question about a piece of
text: does this header name a column role, does this line start with a question
identifier, what does this instruction appear to be about. Every one of them can
answer "I don't know", and that answer is a legitimate result rather than a
failure - Section 30 requires that missing information become an explicit state
instead of a guess.

Nothing in this module hard-codes a QRE convention. The vocabularies come from
``config/extraction_patterns.toml`` so that meeting a new document format is a
configuration change, not a code change (Sections 9, 10, 61).
"""

from __future__ import annotations

import hashlib
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from src.common.schemas.qre_extraction import Evidence, InstructionKind

REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_PATTERNS_PATH = REPO_ROOT / "config" / "extraction_patterns.toml"

_PUNCTUATION = re.compile(r"[^a-z0-9]+")
_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class ExtractionPatterns:
    """The configured vocabulary, plus a fingerprint of the file it came from."""

    column_roles: dict[str, list[str]]
    question_id_patterns: list[re.Pattern]
    instruction_cues: dict[str, list[str]]
    min_header_match_ratio: float
    flag_unparsed_with_cues: bool
    flag_unparsed_with_question_id: bool
    fingerprint: str
    _role_lookup: dict[str, str] = field(default_factory=dict)

    def role_for_header(self, header: str) -> str | None:
        return self._role_lookup.get(normalize_header(header))


def normalize_header(text: str) -> str:
    """Reduce a header cell to a comparable form.

    Punctuation is collapsed so that "Options / scale", "Options/Scale" and
    "options - scale" all compare equal. This is normalization for *matching*
    only; the original text is never altered in the output.
    """
    return _PUNCTUATION.sub(" ", (text or "").lower()).strip()


def load_patterns(path: Path | None = None) -> ExtractionPatterns:
    """Load the extraction vocabulary from TOML."""
    path = path or DEFAULT_PATTERNS_PATH
    raw = path.read_bytes()
    data = tomllib.loads(raw.decode("utf-8"))

    column_roles = {
        role: [normalize_header(s) for s in synonyms]
        for role, synonyms in data.get("column_roles", {}).items()
    }

    lookup: dict[str, str] = {}
    for role, synonyms in column_roles.items():
        for synonym in synonyms:
            # First declaration wins, so a synonym listed under two roles is
            # resolved predictably rather than by dict ordering accident.
            lookup.setdefault(synonym, role)

    return ExtractionPatterns(
        column_roles=column_roles,
        question_id_patterns=[
            re.compile(p) for p in data.get("question_id", {}).get("patterns", [])
        ],
        instruction_cues={
            kind: [c.lower() for c in cues]
            for kind, cues in data.get("instruction_cues", {}).items()
        },
        min_header_match_ratio=float(
            data.get("table_detection", {}).get("min_header_match_ratio", 0.6)
        ),
        flag_unparsed_with_cues=bool(
            data.get("review", {}).get("flag_unparsed_containing_cues", True)
        ),
        flag_unparsed_with_question_id=bool(
            data.get("review", {}).get("flag_unparsed_containing_question_id", True)
        ),
        fingerprint=hashlib.sha256(raw).hexdigest()[:16],
        _role_lookup=lookup,
    )


@dataclass(frozen=True)
class ColumnMapping:
    """Which column holds which role, and how sure we are the table is one."""

    roles: dict[str, int]
    match_ratio: float
    unmapped_headers: list[str]

    @property
    def has_identifiable_question(self) -> bool:
        return "id" in self.roles or "wording" in self.roles


def map_columns(header: list[str], patterns: ExtractionPatterns) -> ColumnMapping:
    """Map a table's header row onto column roles.

    Returns a mapping plus the share of headers that were recognised. A low
    ratio is not an error - it means this is probably not a question table, and
    the caller should preserve it rather than interpret it.
    """
    roles: dict[str, int] = {}
    unmapped: list[str] = []
    matched = 0

    for index, cell in enumerate(header):
        if not (cell or "").strip():
            continue
        role = patterns.role_for_header(cell)
        if role is None:
            unmapped.append(cell)
            continue
        matched += 1
        # First column wins a role, so a repeated header does not silently
        # overwrite the earlier and better-placed one.
        roles.setdefault(role, index)

    considered = sum(1 for c in header if (c or "").strip())
    ratio = matched / considered if considered else 0.0
    return ColumnMapping(roles=roles, match_ratio=ratio, unmapped_headers=unmapped)


def find_question_id(text: str, patterns: ExtractionPatterns) -> tuple[str, str] | None:
    """Return (question_id, matching_pattern) if the text starts with one."""
    candidate = (text or "").strip()
    for pattern in patterns.question_id_patterns:
        match = pattern.match(candidate)
        if match:
            return match.group(1), pattern.pattern
    return None


def corroborate_prose_question(
    text: str, qid: str
) -> tuple[bool, list[Evidence]]:
    """Decide whether an ID-looking line is really a question.

    An identifier alone is weak evidence. Document titles, section labels and
    reference codes all start with something shaped like "S01", and treating
    every one of them as a question would invent questions the QRE never asked -
    the hallucination Section 30 forbids and failure mode 24 in Section 39.

    Corroboration is deliberately generic: either the line asks something, or it
    carries enough words after the identifier to be a question rather than a
    label. Anything weaker is retained as unparsed and flagged, so the decision
    surfaces instead of silently going either way.
    """
    remainder = (text or "")[len(qid) :].strip(" .:)-–—•\t")
    word_count = len(remainder.split())
    asks = "?" in (text or "")

    evidence = [
        Evidence(signal="remainder_word_count", value=str(word_count)),
        Evidence(signal="contains_question_mark", value=str(asks).lower()),
    ]
    return (asks or word_count >= 4), evidence


@dataclass(frozen=True)
class InstructionClassification:
    """A shallow guess at what an instruction is about, with its evidence."""

    kind: InstructionKind
    score: float
    evidence: list[Evidence]
    ambiguous: bool
    runners_up: list[str]


def classify_instruction(
    text: str, patterns: ExtractionPatterns
) -> InstructionClassification:
    """Classify an instruction by cue words alone.

    This is deliberately shallow. It records that an instruction *mentions*
    skipping, not that it skips to Q8 under some condition - that reading is
    Part 2's (Section 19).

    When two kinds score equally the result is marked ambiguous rather than
    resolved. Cues genuinely overlap: "terminate" is both routing and
    disposition, and forcing a choice here would discard the fact that the
    document was unclear (Section 31).
    """
    haystack = (text or "").lower()
    scores: dict[str, list[str]] = {}

    for kind, cues in patterns.instruction_cues.items():
        hits = [cue for cue in cues if cue in haystack]
        if hits:
            scores[kind] = hits

    if not scores:
        return InstructionClassification(
            kind=InstructionKind.UNCLASSIFIED,
            score=0.0,
            evidence=[Evidence(signal="cue_matches", value="0")],
            ambiguous=False,
            runners_up=[],
        )

    ranked = sorted(scores.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    best_kind, best_hits = ranked[0]
    tied = [k for k, hits in ranked[1:] if len(hits) == len(best_hits)]

    evidence = [
        Evidence(
            signal="cue_matches",
            value=str(len(best_hits)),
            detail=f"{best_kind}: {', '.join(sorted(best_hits))}",
        )
    ]
    if tied:
        evidence.append(
            Evidence(
                signal="tied_kinds",
                value=str(len(tied)),
                detail=", ".join(sorted(tied)),
            )
        )

    # More distinct cues means firmer ground, but never certainty: a cue is a
    # word, not a meaning. Capped below 1.0 so that no deterministic string
    # match ever presents itself as beyond doubt.
    score = min(0.5 + 0.15 * len(best_hits), 0.9)
    if tied:
        score = min(score, 0.5)

    return InstructionClassification(
        kind=InstructionKind(best_kind),
        score=score,
        evidence=evidence,
        ambiguous=bool(tied),
        runners_up=sorted(tied),
    )


_CODE_PREFIX = re.compile(r"^\s*([A-Za-z0-9]{1,4})\s*[=:.\)]\s*(.+)$")
_OPTION_SPLIT = re.compile(r"[;\n|]+")


def split_options(text: str) -> list[tuple[str, str | None]]:
    """Split an options cell into (label, code) pairs.

    Splitting is DERIVED, not extracted - it is deterministic from the source
    text but the source did not present a list. The caller records that origin,
    and keeps the raw cell alongside.

    A code is returned only where the text supplies one. Section 13: labels
    without codes yield ``None``, never an invented number, because a
    fabricated code is indistinguishable from a real one downstream.
    """
    raw = (text or "").strip()
    if not raw:
        return []

    options: list[tuple[str, str | None]] = []
    for part in _OPTION_SPLIT.split(raw):
        label = part.strip()
        if not label:
            continue
        match = _CODE_PREFIX.match(label)
        if match:
            options.append((match.group(2).strip(), match.group(1).strip()))
        else:
            options.append((label, None))
    return options


def looks_significant(text: str, patterns: ExtractionPatterns) -> str | None:
    """Whether unclassifiable content still deserves a reviewer's attention.

    Everything unclassified is retained regardless (Section 16). This decides
    only what gets *surfaced*, because a review queue containing every leftover
    line is a review queue nobody reads (Section 22).
    """
    candidate = (text or "").strip()
    if not candidate:
        return None

    if patterns.flag_unparsed_with_question_id and find_question_id(
        candidate, patterns
    ):
        return "contains something shaped like a question identifier"

    if patterns.flag_unparsed_with_cues:
        haystack = candidate.lower()
        for cues in patterns.instruction_cues.values():
            if any(cue in haystack for cue in cues):
                return "contains an instruction cue but could not be classified"
    return None
