"""An independent reading of the raw QRE, used as ground truth.

This is the other half of a comparison, so it deliberately shares no code with
the pipeline it checks. It reads the document through Stage 1 only - a
mechanical walk of the body XML with no interpretation in it - and works
everything else out for itself. Importing `part2_canonical` or
`part2_conditions` here would make the test agree with the thing under test by
construction, which is the one result that would mean nothing.

Two jobs:

    read()      the document's own statements, in its own words
    reference   a parser and evaluator for the formal conditions a QRE writes
                itself, so a routing rule can be checked by running it rather
                than by comparing strings

The reference parser handles only what a QRE states formally - `S1 == 'No'`,
`Q12 in ['Fully','Partly']`, `sum(Q18) != 100`. Anything else returns None and
the test that needed it is reported UNVERIFIED rather than guessed at. A prose
condition has no independent expected answer: that is exactly the case where
only a person can say whether the pipeline read it correctly.

Nothing here is specific to any document. Sections are found by what their
headings say, columns by what their headers say, and every id, label and code
comes out of the file.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import stage1_ingestion
from .models import BlockKind

# ---------------------------------------------------------------------------
# Finding the parts of the document
# ---------------------------------------------------------------------------

#: What a heading has to say for a section to be that section. Ordered, because
#: the first match wins and some headings answer to more than one cue.
_SECTION_CUES: list[tuple[str, tuple[str, ...]]] = [
    ("quotas", ("quota",)),
    ("scenarios", ("scenario", "acceptance", "test case")),
    ("messages", ("completion message", "disposition", "message")),
    ("routing", ("routing", "termination", "skip logic")),
    ("programming", ("programming", "qa requirement", "qa ")),
    ("study", ("study", "specification", "background", "objective")),
    ("questionnaire", ("questionnaire", "question")),
]

#: What a column header has to say for a column to be that column.
_QUESTION_COLUMNS = {
    "id": ("id", "ref", "number"),
    "wording": ("wording", "instruction", "text", "question"),
    "type": ("type", "format"),
    "options": ("option", "scale", "answer", "response"),
    "display": ("display", "validation", "logic", "condition", "base"),
}
_ROUTING_COLUMNS = {
    "rule": ("rule", "id"),
    "condition": ("condition", "if", "criteria"),
    "action": ("action", "behaviour", "behavior"),
    "destination": ("destination", "target", "goto", "then"),
}
_SCENARIO_COLUMNS = {
    "id": ("id", "ref"),
    "purpose": ("purpose", "description", "name"),
    "inputs": ("input", "given", "answers"),
    "expected": ("expected", "outcome", "result"),
}

#: A question id as documents write them: S1, Q12, D4, A_2.
QID = re.compile(r"\b([A-Za-z]{1,4}_?\d+)\b")

#: "1 - Very poor" is a code and a label. "Primary-care physician" and "21-29"
#: are not, which is why the hyphen must have space on both sides.
_CODED_OPTION = re.compile(r"^\s*(\S+)\s+-\s+(.+?)\s*$")

#: "Label: value" at the start of a prose line.
_LABELLED = re.compile(r"^\s*([A-Za-z][A-Za-z0-9_ /&-]{2,40}?)\s*:\s*(.+)$", re.S)

#: An instruction that narrows one question's options to another's answers.
_PIPE_CUE = re.compile(r"\bshow only\b|\bpiped?\b|\bcarry forward\b", re.I)


def _section_of(heading: str) -> str | None:
    lowered = heading.lower()
    for name, cues in _SECTION_CUES:
        if any(cue in lowered for cue in cues):
            return name
    return None


def _column_map(header: list[str], wanted: dict) -> dict[str, int]:
    """Which column holds which field, decided from the header row alone."""
    found: dict[str, int] = {}
    for index, cell in enumerate(header):
        lowered = (cell or "").strip().lower()
        if not lowered:
            continue
        for field_name, cues in wanted.items():
            if field_name in found:
                continue
            if any(cue in lowered for cue in cues):
                found[field_name] = index
                break
    return found


def _split_segments(text: str) -> list[str]:
    """Split a cell on its separators, but not inside a brace or a bracket.

    A validation instruction is JSON, and JSON contains commas and can contain
    slashes; splitting blindly would cut one instruction in half.
    """
    parts, depth, current = [], 0, []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch in "{[":
            depth += 1
        elif ch in "}]":
            depth = max(0, depth - 1)
        if depth == 0:
            if ch == "\n":
                parts.append("".join(current))
                current = []
                i += 1
                continue
            if ch == "/" and (i == 0 or text[i - 1] == " ") and text[i + 1 : i + 2] == " ":
                parts.append("".join(current))
                current = []
                i += 1
                continue
        current.append(ch)
        i += 1
    parts.append("".join(current))
    return [p.strip() for p in parts if p.strip()]


# ---------------------------------------------------------------------------
# What the document says
# ---------------------------------------------------------------------------


@dataclass
class OracleOption:
    label: str
    code: str | None = None
    position: int = 0


@dataclass
class OracleQuestion:
    question_id: str
    seq: int
    wording: str = ""
    type: str = ""
    options: list[OracleOption] = field(default_factory=list)
    matrix_rows: list[OracleOption] = field(default_factory=list)
    #: The text after "Show if:", exactly as written. None where the cell says
    #: the question is always shown, or says nothing about display at all.
    display_condition: str | None = None
    #: True where the cell explicitly says the question is always shown.
    always_shown: bool = False
    #: Parsed `Validate: {...}` payloads, merged.
    validate: dict = field(default_factory=dict)
    randomize: bool = False
    optional: bool = False
    #: A sentence narrowing this question's options to an earlier answer.
    option_source_text: str | None = None
    #: Every other instruction in the cell, kept whole.
    other_instructions: list[str] = field(default_factory=list)
    block_order: int = 0
    row_index: int = 0


@dataclass
class OracleRule:
    rule_id: str
    condition: str
    action: str
    destination: str
    position: int
    block_order: int = 0
    row_index: int = 0


@dataclass
class OracleScenario:
    scenario_id: str
    purpose: str
    inputs_raw: dict
    expected_raw: dict
    inputs_text: str
    expected_text: str
    row_index: int = 0


@dataclass
class OracleStatement:
    text: str
    label: str | None = None
    code: str | None = None
    block_order: int = 0


@dataclass
class OracleDocument:
    source: str
    questions: list[OracleQuestion] = field(default_factory=list)
    rules: list[OracleRule] = field(default_factory=list)
    scenarios: list[OracleScenario] = field(default_factory=list)
    messages: list[OracleStatement] = field(default_factory=list)
    quotas: list[OracleStatement] = field(default_factory=list)
    study: list[OracleStatement] = field(default_factory=list)
    programming: list[OracleStatement] = field(default_factory=list)
    #: Headings seen, so a section the reader could not place is visible rather
    #: than quietly absent.
    headings: list[str] = field(default_factory=list)
    unplaced_headings: list[str] = field(default_factory=list)

    def question(self, question_id: str) -> OracleQuestion | None:
        return next((q for q in self.questions if q.question_id == question_id), None)


def _parse_options(cell: str) -> tuple[list[OracleOption], list[OracleOption]]:
    """Answer options, and matrix rows where the cell names them separately."""
    rows_text, scale_text = None, None
    for segment in _split_segments(cell):
        lowered = segment.lower()
        if lowered.startswith("rows:"):
            rows_text = segment.split(":", 1)[1]
        elif lowered.startswith("scale:"):
            scale_text = segment.split(":", 1)[1]

    def build(text: str) -> list[OracleOption]:
        out: list[OracleOption] = []
        for position, piece in enumerate(text.split(";"), start=1):
            label = piece.strip()
            if not label or label in {"—", "-", "–"}:
                continue
            match = _CODED_OPTION.match(label)
            if match:
                out.append(
                    OracleOption(label=match.group(2), code=match.group(1), position=position)
                )
            else:
                out.append(OracleOption(label=label, position=position))
        return out

    if rows_text is not None or scale_text is not None:
        return build(scale_text or ""), build(rows_text or "")
    return build(cell), []


def _read_display_cell(cell: str, question: OracleQuestion) -> None:
    for segment in _split_segments(cell):
        lowered = segment.lower()
        if lowered.startswith("show if"):
            question.display_condition = segment.split(":", 1)[1].strip() if ":" in segment else ""
        elif lowered.startswith("always"):
            question.always_shown = True
        elif lowered.startswith("validate"):
            payload = segment.split(":", 1)[1].strip() if ":" in segment else ""
            try:
                parsed = json.loads(payload)
                if isinstance(parsed, dict):
                    question.validate.update(parsed)
                else:
                    question.other_instructions.append(segment)
            except ValueError:
                question.other_instructions.append(segment)
        elif lowered.startswith("randomi"):
            question.randomize = True
        elif lowered.startswith("optional"):
            question.optional = True
        elif _PIPE_CUE.search(segment):
            question.option_source_text = segment
            if "randomi" in lowered:
                question.randomize = True
        else:
            question.other_instructions.append(segment)
            if "randomi" in lowered:
                question.randomize = True


def read(docx_path: str | Path) -> OracleDocument:
    """Read the document's own statements, without interpreting any of them."""
    document = stage1_ingestion.run(docx_path)
    oracle = OracleDocument(source=Path(docx_path).name)

    section = None
    seq = 0
    for block in document.blocks:
        if block.kind is BlockKind.PARAGRAPH:
            if block.heading_level is not None and block.text.strip():
                oracle.headings.append(block.text.strip())
                section = _section_of(block.text)
                if section is None:
                    oracle.unplaced_headings.append(block.text.strip())
                continue
            text = block.text.strip()
            if not text or section is None:
                continue
            if section in ("messages", "quotas", "study", "programming"):
                label = code = None
                match = _LABELLED.match(text)
                body = text
                if match:
                    head, body = match.group(1).strip(), match.group(2).strip()
                    # A heading-shaped prefix is a code when it looks like an
                    # identifier, and a label when it reads like words.
                    if head.isupper() and " " not in head:
                        code = head
                    else:
                        label = head
                getattr(oracle, section).append(
                    OracleStatement(text=body, label=label, code=code, block_order=block.order)
                )
            continue

        # A table.
        if section is None or not block.rows:
            continue
        header = block.rows[0]
        if section == "questionnaire":
            columns = _column_map(header, _QUESTION_COLUMNS)
            if "id" not in columns:
                continue
            for row_index, row in enumerate(block.rows[1:]):
                get = lambda key: (row[columns[key]] if key in columns and columns[key] < len(row) else "")
                question_id = get("id").strip()
                if not question_id:
                    continue
                seq += 1
                question = OracleQuestion(
                    question_id=question_id,
                    seq=seq,
                    wording=get("wording").strip(),
                    type=get("type").strip(),
                    block_order=block.order,
                    row_index=row_index,
                )
                question.options, question.matrix_rows = _parse_options(get("options"))
                _read_display_cell(get("display"), question)
                oracle.questions.append(question)
        elif section == "routing":
            columns = _column_map(header, _ROUTING_COLUMNS)
            if "condition" not in columns or "action" not in columns:
                continue
            for row_index, row in enumerate(block.rows[1:]):
                get = lambda key: (row[columns[key]] if key in columns and columns[key] < len(row) else "")
                rule_id = get("rule").strip()
                if not rule_id:
                    continue
                oracle.rules.append(
                    OracleRule(
                        rule_id=rule_id,
                        condition=get("condition").strip(),
                        action=get("action").strip(),
                        destination=get("destination").strip(),
                        position=len(oracle.rules) + 1,
                        block_order=block.order,
                        row_index=row_index,
                    )
                )
        elif section == "scenarios":
            columns = _column_map(header, _SCENARIO_COLUMNS)
            if "id" not in columns:
                continue
            for row_index, row in enumerate(block.rows[1:]):
                get = lambda key: (row[columns[key]] if key in columns and columns[key] < len(row) else "")
                scenario_id = get("id").strip()
                if not scenario_id:
                    continue

                def as_dict(text: str) -> dict:
                    try:
                        value = json.loads(text)
                        return value if isinstance(value, dict) else {}
                    except ValueError:
                        return {}

                oracle.scenarios.append(
                    OracleScenario(
                        scenario_id=scenario_id,
                        purpose=get("purpose").strip(),
                        inputs_raw=as_dict(get("inputs").strip()),
                        expected_raw=as_dict(get("expected").strip()),
                        inputs_text=get("inputs").strip(),
                        expected_text=get("expected").strip(),
                        row_index=row_index,
                    )
                )
    return oracle


# ---------------------------------------------------------------------------
# The reference condition: parse, then run
# ---------------------------------------------------------------------------

_REF_OPS = [
    ("!=", "ne"), ("==", "eq"), ("<=", "le"), (">=", "ge"),
    (" not in ", "not_in"), (" in ", "in"), ("<", "lt"), (">", "gt"),
]
_REF_AGG = re.compile(r"^\s*(sum|count)\s*\(\s*([A-Za-z]{1,4}_?\d+)\s*\)\s*$", re.I)


@dataclass
class RefCondition:
    op: str
    question_id: str
    aggregate: str | None
    literal: object


def _mask_literals(text: str) -> str:
    """The text with quoted content blanked out, for searching structure only.

    Without this, an answer label decides whether the condition parses:
    `Q3 != 'None/currently not using'` was read as a boolean expression because
    its literal contains the word "not", and a perfectly formal condition was
    reported as prose.
    """
    out, quote = [], None
    for ch in text:
        if quote:
            out.append("x")
            if ch == quote:
                quote = None
                out[-1] = ch
        elif ch in "'\"":
            quote = ch
            out.append(ch)
        else:
            out.append(ch)
    return "".join(out)


def parse_reference(text: str) -> RefCondition | None:
    """Read a condition the QRE states formally. None for anything else.

    Deliberately small. It exists to give an independent expected answer for
    conditions the document already wrote in a machine-readable form, and to
    admit defeat on the rest rather than to compete with the real parser.
    """
    text = (text or "").strip()
    if not text:
        return None
    mask = _mask_literals(text)
    if any(joiner in mask.lower() for joiner in (" and ", " or ", " not ")):
        return None
    for token, op in _REF_OPS:
        index = mask.find(token)
        if index < 0:
            continue
        left, right = text[:index].strip(), text[index + len(token) :].strip()
        aggregate = None
        match = _REF_AGG.match(left)
        if match:
            aggregate, question_id = match.group(1).lower(), match.group(2)
        else:
            bare = QID.fullmatch(left.strip())
            if not bare:
                return None
            question_id = bare.group(1)
        try:
            literal = json.loads(right.replace("'", '"'))
        except ValueError:
            return None
        return RefCondition(op=op, question_id=question_id, aggregate=aggregate, literal=literal)
    return None


def evaluate_reference(condition: RefCondition, state: dict) -> bool | None:
    """Run a reference condition against an answer state. None if unanswerable.

    `==` against a list compares the whole answer set, which is what a QRE
    means by `Q1 == ['None of these']` - chosen, and chosen alone. That reading
    is the document's own, not the pipeline's: the pipeline records it as an
    assumption, and this is the independent statement of the same thing.
    """
    if condition.question_id not in state:
        return None
    answer = state[condition.question_id]
    if condition.aggregate:
        values = answer.values() if isinstance(answer, dict) else (answer if isinstance(answer, (list, tuple)) else [answer])
        numbers = [v for v in values if isinstance(v, (int, float))]
        actual = sum(numbers) if condition.aggregate == "sum" else len(list(values))
        literal = condition.literal
        if not isinstance(literal, (int, float)):
            return None
        return _compare(condition.op, actual, literal)
    return _compare(condition.op, answer, condition.literal)


def _compare(op: str, answer, literal) -> bool | None:
    if op in ("eq", "ne"):
        if isinstance(literal, list) or isinstance(answer, list):
            same = set(answer if isinstance(answer, list) else [answer]) == set(
                literal if isinstance(literal, list) else [literal]
            )
        else:
            same = answer == literal
        return same if op == "eq" else not same
    if op in ("in", "not_in"):
        if not isinstance(literal, list):
            return None
        if isinstance(answer, list):
            inside = any(a in literal for a in answer)
        else:
            inside = answer in literal
        return inside if op == "in" else not inside
    if isinstance(answer, (int, float)) and isinstance(literal, (int, float)):
        return {"lt": answer < literal, "le": answer <= literal,
                "gt": answer > literal, "ge": answer >= literal}[op]
    return None
