"""Agent 1 · Part 1 · Step 4 — Understand the questions.

    In:  questionnaire block from Step 2
    Out: list of RawQuestion objects
         {id, wording, type, options_raw, display_validation_raw}

Per the step table: "Parses the question table (or equivalent structural format)
row by row, pulling ID, wording, type, and raw options/validation content as-is —
no interpretation yet."

Mechanism: `python-docx` table cells, already extracted into row/column grids by
Step 1, so this step reads `NormalizedTable.rows` rather than reopening the
document. Fully deterministic — no LLM call, matching the step table's tech stack
(python-docx / pdfplumber only) and CLAUDE.md §29's assignment of table
extraction to code.

The "as-is" boundary is strict. This step does NOT:
  - split "Yes; No" into options — Step 5 splits multi-part cells;
  - parse `Validate: {"min_length": 10}` — Step 5 reads validation JSON;
  - interpret "Show if: Q5 == 'Yes'" — Step 5 converts conditions, Part 2
    normalizes their semantics (CLAUDE.md §19);
  - decide that "—" means "no options";
  - map "single"/"multi" onto any platform's type system.
Every cell is carried through verbatim, newlines included.

Column roles are matched dynamically. "Or equivalent structural format" and
CLAUDE.md §9 both forbid depending on the sample's column names, so headers are
matched against a configurable alias vocabulary. A header that matches nothing is
preserved in `extra_columns` (keyed by column index) and reported, never dropped (§16).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

from ..ingestion.normalized_document import DocumentBlock, NormalizedTable, SourceReference
from .label_matching import score_label
from .raw_question import ExtraColumn, QuestionExtraction, RawQuestion
from .sectioned_document import ReviewItem, SectionedDocument

# ---------------------------------------------------------------------------
# Column-role vocabulary
# ---------------------------------------------------------------------------
# The five roles are fixed by the step table's output contract. The aliases are
# category-3 material under CLAUDE.md §61 — observed sample patterns, not
# confirmed Escalent conventions — so callers override them via
# `parse_questions(..., column_aliases=...)` rather than editing this dict.
ROLE_ID = "id"
ROLE_WORDING = "wording"
ROLE_TYPE = "type"
ROLE_OPTIONS = "options_raw"
ROLE_DISPLAY_VALIDATION = "display_validation_raw"

#: Roles without which a row cannot be a question. A table lacking either is
#: reported rather than parsed into content-free objects.
REQUIRED_ROLES = (ROLE_ID, ROLE_WORDING)

DEFAULT_COLUMN_ALIASES: Mapping[str, tuple[str, ...]] = {
    ROLE_ID: (
        "id",
        "qid",
        "q id",
        "question id",
        "question no",
        "question number",
        "number",
        "no",
        "ref",
        "reference",
        "code",
    ),
    ROLE_WORDING: (
        "wording",
        "wording instruction",
        "wording / instruction",
        "question",
        "question wording",
        "question text",
        "text",
        "label",
        "instruction",
        "script",
    ),
    ROLE_TYPE: (
        "type",
        "question type",
        "qtype",
        "q type",
        "format",
        "answer type",
        "response type",
    ),
    ROLE_OPTIONS: (
        "options",
        "options scale",
        "options / scale",
        "option list",
        "scale",
        "answers",
        "answer list",
        "answer options",
        "response options",
        "responses",
        "codes",
        "codeframe",
        "code frame",
    ),
    ROLE_DISPLAY_VALIDATION: (
        "display validation",
        "display / validation",
        "display",
        "validation",
        "display logic",
        "logic",
        "conditions",
        "condition",
        "base",
        "base and validation",
    ),
}

#: Signature of an optional semantic classifier for unrecognized column headers.
#: Receives the header text and the roles still unfilled; returns one of those
#: roles, or None to leave the column unmapped. Implementations must route
#: through the approved LLM client (CLAUDE.md §52).
ColumnClassifier = Callable[[str, Sequence[str]], str | None]

#: How many leading rows to consider as the header row. A table may open with a
#: title or spanning-caption row before its real header.
HEADER_SEARCH_DEPTH = 3


def _map_columns(
    header: Sequence[str], vocabulary: Mapping[str, Sequence[str]]
) -> tuple[dict[str, int], list[str]]:
    """Map header cells to column roles by best match, not document order.

    Every (column, role) pair is scored, then roles are assigned in descending
    score order. Assigning left to right instead would let an early weak match
    claim a role that a later column fits better: in a table headed
    "Scripter notes | … | Base / Validation", "Scripter notes" appears first but
    "Base / Validation" is the real validation column.

    Returns:
        (role -> column index, unmapped header texts). A column that wins no role
        is reported, and its content is still preserved per question in
        `extra_columns`. Blank headers are omitted from the report — they are not
        column names — but their content is preserved just the same.
    """
    # (score, column index, role) for every candidate pairing.
    candidates: list[tuple[float, int, str]] = []
    for index, cell in enumerate(header):
        for role, score in score_label(cell, vocabulary).items():
            candidates.append((score, index, role))

    # Highest score first; ties resolve to the earlier column for stability.
    candidates.sort(key=lambda c: (-c[0], c[1]))

    roles: dict[str, int] = {}
    claimed: set[int] = set()
    for _score, index, role in candidates:
        if role not in roles and index not in claimed:
            roles[role] = index
            claimed.add(index)

    unmapped = [
        cell
        for index, cell in enumerate(header)
        if index not in claimed and cell.strip()
    ]
    return roles, unmapped


def _find_header_row(
    rows: Sequence[Sequence[str]], vocabulary: Mapping[str, Sequence[str]]
) -> tuple[int, dict[str, int], list[str]]:
    """Pick the row that best works as a header.

    Scans the first HEADER_SEARCH_DEPTH rows and takes whichever maps the most
    roles, so a leading title row does not defeat detection. Ties go to the
    earlier row.

    Returns:
        (header row index, role -> column index, unmapped header texts). When no
        row maps any role, falls back to row 0 with *all* its cells reported as
        unmapped — never a hardcoded empty list. An earlier version seeded `best`
        with an empty unmapped list and only replaced it when a row mapped at
        least one role, so a table whose column names were wholly unfamiliar
        reported nothing to classify and the LLM fallback could never engage.
    """
    if not rows:
        return 0, {}, []

    best: tuple[int, dict[str, int], list[str]] | None = None
    for index in range(min(HEADER_SEARCH_DEPTH, len(rows))):
        roles, unmapped = _map_columns(rows[index], vocabulary)
        if best is None or len(roles) > len(best[1]):
            best = (index, roles, unmapped)
    return best if best is not None else (0, {}, [])


def _cell(row: Sequence[str], roles: Mapping[str, int], role: str) -> str:
    """Read one role's cell from a row, or "" when absent.

    A short row — fewer cells than the header — yields "" for the missing roles
    rather than raising, and `RawQuestion.empty_fields` then reports the gap.
    """
    index = roles.get(role)
    if index is None or index >= len(row):
        return ""
    return row[index]


def _is_blank_row(row: Sequence[str]) -> bool:
    return not any(cell.strip() for cell in row)


def _fill_roles_with_classifier(
    header: Sequence[str],
    roles: dict[str, int],
    unmapped: list[str],
    vocabulary: Mapping[str, Sequence[str]],
    classifier: ColumnClassifier,
) -> tuple[dict[str, int], list[str]]:
    """Ask the classifier about columns the alias vocabulary could not place.

    Called once, on the header row already chosen deterministically — not during
    the header search, which would multiply model calls by HEADER_SEARCH_DEPTH for
    no gain.

    Only unmapped columns are offered, and only unfilled roles are on the table,
    so a header the vocabulary already understood never reaches the model. A
    returned role is accepted only if it is in the vocabulary and still unclaimed,
    so the classifier cannot widen the contract or steal a deterministic match
    (CLAUDE.md §17).

    Returns:
        (updated role -> column index, remaining unmapped header texts).
    """
    remaining = [role for role in vocabulary if role not in roles]
    if not remaining:
        return roles, unmapped

    claimed_indexes = set(roles.values())
    still_unmapped: list[str] = []

    for index, cell in enumerate(header):
        if index in claimed_indexes or not cell.strip():
            continue
        open_roles = [role for role in vocabulary if role not in roles]
        if not open_roles:
            still_unmapped.append(cell)
            continue

        proposed = classifier(cell, open_roles)
        if proposed in open_roles:
            roles[proposed] = index
            claimed_indexes.add(index)
        else:
            still_unmapped.append(cell)

    return roles, still_unmapped


#: Column-shape thresholds for value-based role inference. Deliberately loose —
#: this is a last resort before giving up, not a precise classifier.
_ID_MAX_MEAN_LENGTH = 14
_WORDING_MIN_MEAN_LENGTH = 18


def _column_values(
    rows: Sequence[Sequence[str]], header_index: int, column: int
) -> list[str]:
    """Non-empty data-row values for one column."""
    values = []
    for row in rows[header_index + 1 :]:
        if column < len(row) and row[column].strip():
            values.append(row[column].strip())
    return values


def _infer_required_roles_from_values(
    rows: Sequence[Sequence[str]],
    header_index: int,
    roles: dict[str, int],
    vocabulary: Mapping[str, Sequence[str]],
) -> tuple[dict[str, int], list[str]]:
    """Infer a missing id or wording column from the shape of its values.

    Header text alone is not always enough. A column headed "Marker" holding
    A_01, A_02, A_03 is obviously an id column, but nothing in the word "Marker"
    says so — and a model asked to judge the header in isolation correctly
    declines. The values settle it.

    Deterministic on purpose (CLAUDE.md §29): more reliable here than a model,
    and it sends nothing anywhere, so it works on confidential QREs where
    transmitting cell content would not be acceptable.

    Only the two required roles are inferred, and only when still unfilled — this
    is what decides whether a table can be read at all. Optional roles left
    unmatched merely leave a field empty, which needs no guessing.

    Signals used:
      - id:      short values, all distinct, no internal whitespace (a code, not
                 a sentence).
      - wording: longest mean length among remaining columns, containing spaces.

    Returns:
        (updated roles, list of role names that were inferred this way).
    """
    inferred: list[str] = []
    if not rows or header_index + 1 >= len(rows):
        return roles, inferred

    width = max(len(row) for row in rows)
    available = [c for c in range(width) if c not in set(roles.values())]

    def stats(column: int) -> tuple[int, float, bool, int]:
        values = _column_values(rows, header_index, column)
        if not values:
            return 0, 0.0, False, 0
        mean_length = sum(len(v) for v in values) // len(values)
        uniqueness = len(set(values)) / len(values)
        spaceless = all(" " not in v for v in values)
        return mean_length, uniqueness, spaceless, len(values)

    if ROLE_ID not in roles:
        candidates = [
            (c, *stats(c))
            for c in available
            if stats(c)[3] > 0
        ]
        # A code column: short, every value distinct, no spaces inside a value.
        id_candidates = [
            (mean_length, c)
            for c, mean_length, uniqueness, spaceless, _count in candidates
            if mean_length <= _ID_MAX_MEAN_LENGTH and uniqueness == 1.0 and spaceless
        ]
        if id_candidates:
            # Shortest mean length is the most id-like.
            roles[ROLE_ID] = min(id_candidates)[1]
            inferred.append(ROLE_ID)
            available.remove(roles[ROLE_ID])

    if ROLE_WORDING not in roles:
        wording_candidates = []
        for column in available:
            mean_length, _uniqueness, spaceless, count = stats(column)
            if count and mean_length >= _WORDING_MIN_MEAN_LENGTH and not spaceless:
                wording_candidates.append((mean_length, column))
        if wording_candidates:
            # Longest mean length is the most sentence-like.
            roles[ROLE_WORDING] = max(wording_candidates)[1]
            inferred.append(ROLE_WORDING)

    return roles, inferred


def _resolve_header(
    rows: Sequence[Sequence[str]],
    vocabulary: Mapping[str, Sequence[str]],
    classifier: ColumnClassifier | None = None,
) -> tuple[int, dict[str, int], list[str]]:
    """Pick the header row and map its columns to roles.

    The single place header resolution happens, so candidate detection and
    parsing can never disagree about what a table's columns mean. Keeping these
    separate was a bug: detection ran deterministically while parsing had the
    classifier, so a table whose column names the vocabulary did not know was
    rejected before the classifier ever saw it.

    Resolution is layered, cheapest and most trustworthy first:
      1. deterministic alias matching on the header text;
      2. an optional model call on headers that did not match;
      3. deterministic inference from cell values, for a required role still
         missing after both.

    Returns:
        (header row index, role -> column index, unmapped header texts, roles
        inferred from values). The last element lets callers report which roles
        rest on inference rather than on what the document actually said (§14).
    """
    header_index, roles, unmapped = _find_header_row(rows, vocabulary)

    # 2nd: a model on the headers the vocabulary could not place.
    if classifier is not None and unmapped:
        roles, unmapped = _fill_roles_with_classifier(
            rows[header_index], roles, unmapped, vocabulary, classifier
        )

    # 3rd: value shape, for a required role still missing. Last resort, and the
    # only stage that looks at cell content rather than headers.
    inferred: list[str] = []
    if any(role not in roles for role in REQUIRED_ROLES):
        roles, inferred = _infer_required_roles_from_values(
            rows, header_index, roles, vocabulary
        )
        if inferred:
            claimed = set(roles.values())
            header = rows[header_index]
            unmapped = [
                cell
                for index, cell in enumerate(header)
                if index not in claimed and cell.strip()
            ]

    return header_index, roles, unmapped, inferred


def _is_question_shaped(
    table: NormalizedTable,
    vocabulary: Mapping[str, Sequence[str]],
    classifier: ColumnClassifier | None = None,
) -> bool:
    """True if a table's header identifies both required roles.

    Recognizes a question table by its shape rather than by which section it sits
    in. Requiring *both* id and wording keeps other QRE tables out: a routing
    table headed "Rule | Condition | Action | Destination" maps neither, and an
    acceptance-test table headed "ID | Purpose | Key inputs | Expected outcome"
    maps id but not wording.
    """
    if len(table.rows) < 2:
        return False
    _index, roles, _unmapped, _inferred = _resolve_header(
        table.rows, vocabulary, classifier
    )
    return all(role in roles for role in REQUIRED_ROLES)


def _find_question_tables(
    sectioned: SectionedDocument,
    vocabulary: Mapping[str, Sequence[str]],
    classifier: ColumnClassifier | None = None,
) -> tuple[list[NormalizedTable], str]:
    """Search every section for question-shaped tables.

    Tried deterministically first. Only if that finds nothing is the classifier
    brought in, so the common case costs no model calls.

    Cost note: a table accepted during the classifier pass has its header
    resolved again in `_parse_table`, so its unmapped headers are classified
    twice. Bounded and cheap — it happens only on this fallback path, only for
    tables the vocabulary could not read, and the payload is a few header
    strings. Threading the resolved roles through would remove the second pass at
    the cost of widening three signatures; not worth it until it shows up as a
    real cost.

    Returns:
        (tables in document order, human-readable description of where they were
        found). Empty list and "" when nothing qualifies.
    """

    def scan(active: ColumnClassifier | None) -> tuple[list[NormalizedTable], list[str]]:
        found: list[NormalizedTable] = []
        origins: list[str] = []
        for section in sectioned.sections:
            for block in section.blocks:
                if isinstance(block, NormalizedTable) and _is_question_shaped(
                    block, vocabulary, active
                ):
                    found.append(block)
                    name = section.label or (
                        f"unclassified section '{section.heading_text}'"
                        if section.heading_text
                        else "unheaded content"
                    )
                    if name not in origins:
                        origins.append(name)
        return found, origins

    found, origins = scan(None)
    if not found and classifier is not None:
        found, origins = scan(classifier)

    return found, ", ".join(origins)


def _parse_table(
    table: NormalizedTable,
    document_name: str,
    vocabulary: Mapping[str, Sequence[str]],
    classifier: ColumnClassifier | None = None,
) -> tuple[list[RawQuestion], list[ReviewItem], dict[str, str], list[str]]:
    """Extract questions from one table.

    Returns:
        (questions, review items, role -> header text, unmapped header texts).
    """
    review: list[ReviewItem] = []

    if len(table.rows) < 2:
        review.append(
            ReviewItem(
                element=f"table@{table.order_index}",
                reason="table_has_no_data_rows",
                detail=(
                    f"The questionnaire table at block {table.order_index} has "
                    f"{len(table.rows)} row(s), so it holds a header at most and "
                    "no questions could be extracted."
                ),
                source_reference=SourceReference(
                    document=document_name, order_index=table.order_index
                ),
            )
        )
        return [], review, {}, []

    header_index, roles, unmapped, inferred_roles = _resolve_header(
        table.rows, vocabulary, classifier
    )
    header = table.rows[header_index]
    mapping = {role: header[index] for role, index in roles.items()}

    # An inferred role rests on value shape, not on anything the document said.
    # Say so, so a reviewer can check it (CLAUDE.md §14, §31).
    if inferred_roles:
        review.append(
            ReviewItem(
                element=f"table@{table.order_index}",
                reason="column_role_inferred_from_values",
                detail=(
                    f"Role(s) {inferred_roles} were not identifiable from the "
                    f"header {list(header)}; they were inferred from the shape of "
                    "the column values (short unique codes for id, longest "
                    "sentence-like column for wording). Verify before relying on "
                    "the output."
                ),
                source_reference=SourceReference(
                    document=document_name,
                    order_index=table.order_index,
                    text=" | ".join(header),
                ),
            )
        )

    missing_required = [role for role in REQUIRED_ROLES if role not in roles]
    if missing_required:
        review.append(
            ReviewItem(
                element=f"table@{table.order_index}",
                reason="required_columns_not_identified",
                detail=(
                    f"Could not identify column(s) {missing_required} in header "
                    f"{list(header)}. No questions were extracted from this table. "
                    "Add an alias for the column, or supply column_aliases."
                ),
                source_reference=SourceReference(
                    document=document_name,
                    order_index=table.order_index,
                    text=" | ".join(header),
                ),
            )
        )
        return [], review, mapping, unmapped

    for role in (ROLE_TYPE, ROLE_OPTIONS, ROLE_DISPLAY_VALIDATION):
        if role not in roles:
            review.append(
                ReviewItem(
                    element=f"table@{table.order_index}",
                    reason="optional_column_not_identified",
                    detail=(
                        f"No column mapped to '{role}' in header {list(header)}. "
                        "Affected fields will be empty."
                    ),
                    source_reference=SourceReference(
                        document=document_name, order_index=table.order_index
                    ),
                )
            )

    if unmapped:
        review.append(
            ReviewItem(
                element=f"table@{table.order_index}",
                reason="unmapped_columns_preserved",
                detail=(
                    f"Column(s) {unmapped} matched no known role. Their cell "
                    "content is preserved per question in `extra_columns` and "
                    "nothing was discarded."
                ),
                source_reference=SourceReference(
                    document=document_name, order_index=table.order_index
                ),
            )
        )

    unmapped_indexes = [
        index for index, cell in enumerate(header) if index not in roles.values()
    ]

    questions: list[RawQuestion] = []
    for offset, row in enumerate(table.rows[header_index + 1 :], start=1):
        if _is_blank_row(row):
            continue  # a spacer row carries no content, so nothing is lost

        # Keyed by column index, not header text: two unmapped columns sharing a
        # header name (or both blank) must not collapse onto one another (§16).
        extra = tuple(
            ExtraColumn(
                column_index=index,
                header=header[index] if index < len(header) else "",
                value=row[index],
            )
            for index in unmapped_indexes
            if index < len(row) and row[index].strip()
        )

        question = RawQuestion(
            id=_cell(row, roles, ROLE_ID),
            wording=_cell(row, roles, ROLE_WORDING),
            type=_cell(row, roles, ROLE_TYPE),
            options_raw=_cell(row, roles, ROLE_OPTIONS),
            display_validation_raw=_cell(row, roles, ROLE_DISPLAY_VALIDATION),
            row_index=offset,
            source_reference=SourceReference(
                document=document_name,
                order_index=table.order_index,
                text=" | ".join(row),
            ),
            extra_columns=extra,
        )
        questions.append(question)

        # Malformed-object detection is part of Part 1's definition of done (§45),
        # but only the two required roles are genuinely defects when empty. An
        # empty options cell on a free-text question is correct, not malformed —
        # flagging it would bury real findings in false positives, and §18
        # requires applicability and requirement to stay distinct.
        empty_required = [f for f in question.empty_fields if f in REQUIRED_ROLES]
        if empty_required:
            review.append(
                ReviewItem(
                    element=question.id or f"row {offset}",
                    reason="required_question_fields_empty",
                    detail=(
                        f"Row {offset} of table {table.order_index} left "
                        f"{empty_required} empty in the source. Rows without an "
                        "id cannot be referenced by routing or validation rules."
                    ),
                    source_reference=question.source_reference,
                )
            )

    return questions, review, mapping, unmapped


def parse_questions(
    sectioned: SectionedDocument,
    section_label: str = "questionnaire",
    column_aliases: Mapping[str, Sequence[str]] | None = None,
    classifier: ColumnClassifier | None = None,
) -> QuestionExtraction:
    """Extract RawQuestion objects from a sectioned document's questionnaire.

    Args:
        sectioned:      Step 2 output.
        section_label:  which section holds the questions. Defaults to
                        "questionnaire".
        column_aliases: optional override of the column-role vocabulary, shaped
                        {role: (alias, ...)}. Defaults to DEFAULT_COLUMN_ALIASES.
        classifier:     optional semantic classifier for column headers the
                        vocabulary does not cover. Omit it and such columns are
                        left unmapped and reported.

    Returns:
        QuestionExtraction. `.questions` is the list the step table specifies;
        `.review_queue` carries anything a human should check.
    """
    aliases = DEFAULT_COLUMN_ALIASES if column_aliases is None else column_aliases
    document_name = sectioned.document_name

    review_queue: list[ReviewItem] = []

    blocks: list[DocumentBlock] = sectioned.by_label().get(section_label, [])
    tables = [b for b in blocks if isinstance(b, NormalizedTable)]

    # Fall back to searching the whole document when the named section did not
    # yield a table. Without this, Step 2 failing to classify one heading takes
    # Step 4 down with it: the question table can be sitting in an unclassified
    # section with perfectly recognizable columns and still be missed. A table
    # that maps both required roles is question-shaped whatever section it is in.
    if not tables:
        reason = (
            "questionnaire_section_not_found"
            if not blocks
            else "no_table_in_questionnaire_section"
        )
        tables, origin = _find_question_tables(sectioned, aliases, classifier)
        if tables:
            review_queue.append(
                ReviewItem(
                    element=origin,
                    reason="question_table_found_outside_named_section",
                    detail=(
                        f"No table in a '{section_label}' section, so the document "
                        f"was searched for question-shaped tables. Found {len(tables)} "
                        f"in: {origin}. Confirm this is the questionnaire before "
                        "relying on the output."
                    ),
                )
            )
        else:
            review_queue.append(
                ReviewItem(
                    element=section_label,
                    reason=reason,
                    detail=(
                        f"No '{section_label}' section with a table, and no other "
                        "table in the document has both an identifiable id and "
                        "wording column. If this QRE lists questions as prose "
                        "rather than a table, it needs a different extractor."
                    ),
                )
            )
            return QuestionExtraction(questions=[], review_queue=review_queue)

    questions: list[RawQuestion] = []
    column_mapping: dict[str, str] = {}
    unmapped_headers: list[str] = []

    # A questionnaire may be split across several tables; parse each and
    # concatenate, so no table is ignored.
    for table in tables:
        found, review, mapping, unmapped = _parse_table(table, document_name, aliases, classifier)
        questions.extend(found)
        review_queue.extend(review)
        for role, header_text in mapping.items():
            column_mapping.setdefault(role, header_text)
        unmapped_headers.extend(h for h in unmapped if h not in unmapped_headers)

    # Duplicate ids break every downstream cross-reference, so report them (§45).
    seen: dict[str, int] = {}
    for question in questions:
        if not question.id:
            continue
        if question.id in seen:
            review_queue.append(
                ReviewItem(
                    element=question.id,
                    reason="duplicate_question_id",
                    detail=(
                        f"Question id '{question.id}' appears more than once "
                        f"(rows {seen[question.id]} and {question.row_index}). "
                        "Downstream references to it are ambiguous."
                    ),
                    source_reference=question.source_reference,
                )
            )
        else:
            seen[question.id] = question.row_index

    return QuestionExtraction(
        questions=questions,
        review_queue=review_queue,
        column_mapping=column_mapping,
        unmapped_headers=unmapped_headers,
        source_tables=[t.order_index for t in tables],
    )
