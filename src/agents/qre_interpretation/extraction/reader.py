"""The QRE Reader: NormalizedDocument -> QREExtractionIR.

Walks an ingested document in order and routes every item somewhere. That
"every" is the load-bearing word: each block and table either becomes an IR
object or is retained in ``unparsed_content``. Nothing is allowed to fall
through, because content lost here is invisible downstream - a reviewer cannot
notice the absence of something they were never shown (Sections 16 and 40).

The reader records what the document says. It does not resolve references,
normalize conditions, or decide what any instruction does. "Skip to Q8" is
stored as those four characters plus its location; that it denotes a jump to
question Q8 is Part 2's finding (Section 19).
"""

from __future__ import annotations

from pathlib import Path

from src.agents.qre_interpretation.ingestion import (
    Block,
    BlockKind,
    NormalizedDocument,
    Table,
)
from src.agents.qre_interpretation.ingestion import SourceLocation
from src.common.schemas.qre_extraction import (
    Confidence,
    Evidence,
    ExtractedInstruction,
    ExtractedOption,
    ExtractedQuestion,
    ExtractionRun,
    InstructionKind,
    Origin,
    QREExtractionIR,
    ReviewItem,
    ReviewReason,
    Section,
    SourceDocument,
    SourceRef,
    UnparsedContent,
)

from .extractor import (
    ColumnMapping,
    ExtractionPatterns,
    classify_instruction,
    corroborate_prose_question,
    find_question_id,
    load_patterns,
    looks_significant,
    map_columns,
    split_options,
)

READER = "qre_reader"
READER_VERSION = "0.1.0"


def _ref(location: SourceLocation) -> SourceRef:
    """Map an ingestion location onto the contract's own reference type.

    The duplication is deliberate - see the note in qre_extraction.py. The
    contract must not depend on Agent 1 internals (Section 26).
    """
    return SourceRef(
        document=location.document,
        order_index=location.order_index,
        page=location.page,
        table_index=location.table_index,
        row=location.row,
        column=location.column,
    )


class _Reader:
    """Accumulates IR pieces while walking one document."""

    def __init__(self, document: NormalizedDocument, patterns: ExtractionPatterns):
        self.document = document
        self.patterns = patterns
        self.sections: list[Section] = []
        self.questions: list[ExtractedQuestion] = []
        self.instructions: list[ExtractedInstruction] = []
        self.unparsed: list[UnparsedContent] = []
        self.review: list[ReviewItem] = []
        self.current_section: str | None = None

    # --- routing of individual items ------------------------------------

    def handle_block(self, block: Block) -> None:
        ref = _ref(block.location)

        if block.kind is BlockKind.HEADING:
            self.sections.append(
                Section(title=block.text, level=block.heading_level, source=ref)
            )
            self.current_section = block.text
            return

        identified = find_question_id(block.text, self.patterns)
        if identified:
            qid, pattern = identified
            corroborated, corroboration = corroborate_prose_question(block.text, qid)
            if corroborated:
                self.questions.append(
                    ExtractedQuestion(
                        qid=qid,
                        text=block.text,
                        section=self.current_section,
                        origin=Origin.EXTRACTED,
                        confidence=Confidence(
                            # Weaker than a row in a question table: the
                            # identifier matched and the line reads like a
                            # question, but no column structure confirms it.
                            score=0.6,
                            evidence=[
                                Evidence(
                                    signal="question_id_pattern",
                                    value=pattern,
                                    detail=f"matched {qid}",
                                ),
                                Evidence(signal="source", value="prose_block"),
                                *corroboration,
                            ],
                        ),
                        source=ref,
                    )
                )
                return

            # Identifier-shaped but nothing else supports calling it a question.
            # Retaining and flagging is the honest outcome; emitting a question
            # here would fabricate one (Section 30).
            self._retain_unparsed(
                block.text, "question_id_shape_without_corroboration", ref
            )
            return

        classification = classify_instruction(block.text, self.patterns)
        if classification.kind is not InstructionKind.UNCLASSIFIED:
            self._add_instruction(block.text, classification, None, ref)
            return

        self._retain_unparsed(block.text, "block_not_classified", ref)

    def handle_table(self, table: Table) -> None:
        ref = _ref(table.location)
        if not table.rows:
            self._retain_unparsed("", "empty_table", ref)
            return

        header = [cell.text for cell in table.rows[0]]
        mapping = map_columns(header, self.patterns)

        is_question_table = (
            mapping.match_ratio >= self.patterns.min_header_match_ratio
            and mapping.has_identifiable_question
        )

        if not is_question_table:
            self._retain_unrecognized_table(table, mapping, ref)
            return

        if mapping.unmapped_headers:
            self.review.append(
                ReviewItem(
                    reason=ReviewReason.UNMAPPED_COLUMN,
                    message=(
                        "Question table has columns with no known role: "
                        f"{', '.join(mapping.unmapped_headers)}. Their content is "
                        "retained as unparsed rather than assigned to a field."
                    ),
                    source=ref,
                )
            )

        for row in table.rows[1:]:
            self._read_question_row(row, mapping, table)

    # --- question rows ---------------------------------------------------

    def _read_question_row(self, row, mapping: ColumnMapping, table: Table) -> None:
        def cell_at(role: str):
            index = mapping.roles.get(role)
            if index is None or index >= len(row):
                return None
            return row[index]

        id_cell = cell_at("id")
        wording_cell = cell_at("wording")
        type_cell = cell_at("type")
        options_cell = cell_at("options")
        logic_cell = cell_at("logic")

        anchor = id_cell or wording_cell or row[0]
        ref = _ref(anchor.location)

        qid = (id_cell.text.strip() or None) if id_cell else None
        text = (wording_cell.text.strip() or None) if wording_cell else None

        if not qid and not text:
            # A row with neither identifier nor wording carries no question.
            # It is usually a spacer or a continuation; retain it and move on.
            joined = " | ".join(c.text for c in row if c.text).strip()
            if joined:
                self._retain_unparsed(joined, "table_row_without_question", ref)
            return

        options: list[ExtractedOption] = []
        raw_options = None
        if options_cell and options_cell.text.strip():
            raw_options = options_cell.text
            for label, code in split_options(options_cell.text):
                options.append(
                    ExtractedOption(
                        label=label,
                        code=code,
                        # Splitting one cell into several options is derived
                        # from the text, not stated by it (Section 14).
                        origin=Origin.DERIVED,
                        source=_ref(options_cell.location),
                    )
                )

        raw_instructions: list[str] = []
        if logic_cell and logic_cell.text.strip():
            raw_instructions.append(logic_cell.text)
            classification = classify_instruction(logic_cell.text, self.patterns)
            self._add_instruction(
                logic_cell.text, classification, qid, _ref(logic_cell.location)
            )

        evidence = [
            Evidence(
                signal="header_match_ratio",
                value=f"{mapping.match_ratio:.2f}",
                detail=f"roles: {', '.join(sorted(mapping.roles))}",
            ),
            Evidence(signal="source", value="question_table"),
        ]
        score = 0.9 if qid and text else 0.7
        if not qid:
            score = min(score, 0.6)
            self.review.append(
                ReviewItem(
                    reason=ReviewReason.MISSING_QUESTION_ID,
                    message=(
                        "A question table row has wording but no identifier. "
                        "No identifier was invented for it."
                    ),
                    source=ref,
                )
            )
            evidence.append(Evidence(signal="missing_qid", value="true"))

        self.questions.append(
            ExtractedQuestion(
                qid=qid,
                text=text,
                raw_type=(type_cell.text.strip() or None) if type_cell else None,
                options=options,
                raw_options_text=raw_options,
                raw_instructions=raw_instructions,
                section=self.current_section,
                origin=Origin.EXTRACTED,
                confidence=Confidence(score=score, evidence=evidence),
                source=ref,
            )
        )

    # --- helpers ----------------------------------------------------------

    def _add_instruction(
        self, raw_text: str, classification, qid: str | None, ref: SourceRef
    ) -> None:
        self.instructions.append(
            ExtractedInstruction(
                # Verbatim. Not stripped, not normalized - the evidence has to
                # survive intact for review and for Part 2 (Section 19).
                raw_text=raw_text,
                kind=classification.kind,
                qid=qid,
                origin=(
                    Origin.AMBIGUOUS if classification.ambiguous else Origin.EXTRACTED
                ),
                confidence=Confidence(
                    score=classification.score, evidence=classification.evidence
                ),
                source=ref,
            )
        )
        if classification.ambiguous:
            self.review.append(
                ReviewItem(
                    reason=ReviewReason.AMBIGUOUS_INSTRUCTION_KIND,
                    message=(
                        f"Instruction reads as {classification.kind.value} but also "
                        f"as {', '.join(classification.runners_up)}. Recorded as "
                        "ambiguous rather than resolved."
                    ),
                    source=ref,
                    related_qid=qid,
                )
            )

    def _retain_unrecognized_table(
        self, table: Table, mapping: ColumnMapping, ref: SourceRef
    ) -> None:
        """Keep a table we could not read as a question table, whole."""
        for row in table.rows:
            joined = " | ".join(cell.text for cell in row if cell.text).strip()
            if joined:
                self._retain_unparsed(
                    joined, "table_not_recognized_as_questions", _ref(row[0].location)
                )

        self.review.append(
            ReviewItem(
                reason=ReviewReason.UNRECOGNIZED_TABLE,
                message=(
                    f"Table {table.location.table_index} was not recognised as a "
                    f"question table (header match {mapping.match_ratio:.2f}, "
                    f"threshold {self.patterns.min_header_match_ratio:.2f}). Its "
                    "rows are retained as unparsed content. If it does hold "
                    "questions, add its column headers to "
                    "config/extraction_patterns.toml rather than changing code."
                ),
                source=ref,
            )
        )

    def _retain_unparsed(self, text: str, reason: str, ref: SourceRef) -> None:
        significance = looks_significant(text, self.patterns)
        self.unparsed.append(
            UnparsedContent(
                text=text,
                reason=reason,
                source=ref,
                requires_review=significance is not None,
            )
        )
        if significance:
            self.review.append(
                ReviewItem(
                    reason=ReviewReason.UNPARSED_SIGNIFICANT_CONTENT,
                    message=f"Unclassified content {significance}.",
                    source=ref,
                )
            )


def read(
    document: NormalizedDocument, patterns: ExtractionPatterns | None = None
) -> QREExtractionIR:
    """Extract a QREExtractionIR from an ingested document."""
    patterns = patterns or load_patterns()
    reader = _Reader(document, patterns)

    for item in document.ordered_items():
        if isinstance(item, Table):
            reader.handle_table(item)
        else:
            reader.handle_block(item)

    if not reader.questions:
        reader.review.append(
            ReviewItem(
                reason=ReviewReason.NO_QUESTIONS_FOUND,
                message=(
                    "No questions were extracted from this document. Either the "
                    "document does not contain a recognisable question structure, "
                    "or its conventions are not yet in the extraction vocabulary."
                ),
            )
        )

    return QREExtractionIR(
        document=SourceDocument(
            filename=document.metadata.filename,
            sha256=document.metadata.sha256,
            format=document.metadata.format.value,
            page_count=document.metadata.page_count,
            ingestion_adapter=document.metadata.adapter,
            ingestion_adapter_version=document.metadata.adapter_version,
        ),
        extraction=ExtractionRun(
            reader=READER,
            reader_version=READER_VERSION,
            patterns_fingerprint=patterns.fingerprint,
        ),
        sections=reader.sections,
        questions=reader.questions,
        instructions=reader.instructions,
        unparsed_content=reader.unparsed,
        review_queue=reader.review,
    )


def read_file(
    path: str | Path, patterns: ExtractionPatterns | None = None
) -> QREExtractionIR:
    """Ingest and extract in one step."""
    from src.agents.qre_interpretation.ingestion import load_document

    return read(load_document(path), patterns)
