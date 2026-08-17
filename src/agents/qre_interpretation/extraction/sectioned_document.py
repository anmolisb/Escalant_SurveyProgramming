"""Sectioned Document Representation — the Step 2 output contract.

Step 2 slices the ordered blocks from Step 1 into named sections. Per the step
table, the output is a "dict of {section_label: content_block}" — supplied here
by `SectionedDocument.by_label()`. The richer `sections` list is the primary
form, because a flat dict cannot express three things this pipeline needs:

  1. sections whose heading could not be classified (label is None);
  2. the same section type appearing more than once;
  3. content appearing before the first heading, which must not be dropped.

Design rules this module obeys (CLAUDE.md):
  §14  every section records how its label was arrived at — `extracted`,
       `derived`, `inferred` or `unknown`
  §15  every section keeps a source reference back to its heading position
  §16  content that cannot be confidently classified is preserved and flagged,
       never discarded
  §31  uncertainty produces a review item rather than a silent guess

This is an internal Part 1 intermediate, not a cross-agent contract, so it lives
inside the agent rather than in src/common/schemas/ (CLAUDE.md §41).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..ingestion.normalized_document import DocumentBlock, SourceReference

# ---------------------------------------------------------------------------
# Label provenance (CLAUDE.md §14)
# ---------------------------------------------------------------------------

#: Heading text matched a known section type exactly, after normalization.
LABEL_EXTRACTED = "extracted"
#: Label was produced deterministically without a direct heading match — e.g.
#: the synthetic preamble section covering content above the first heading.
LABEL_DERIVED = "derived"
#: Label came from semantic reasoning (an LLM classifier).
LABEL_INFERRED = "inferred"
#: A heading was found but no label could be established. Never a guess.
LABEL_UNKNOWN = "unknown"

#: Label given to content appearing before the first heading in the document.
PREAMBLE_LABEL = "document_preamble"


@dataclass(frozen=True)
class ReviewItem:
    """One flagged item for human review (CLAUDE.md §16, §31).

    Attributes:
        element:  short identifier of what is being flagged, e.g. the heading
                  text or a known label that was expected but not found.
        reason:   machine-readable reason code, e.g. "heading_not_classified".
        detail:   human-readable explanation for a reviewer.
        source_reference: where in the document this was raised, when it maps to
                  a position. None for document-level observations such as a
                  known section type being absent.
    """

    element: str
    reason: str
    detail: str
    source_reference: SourceReference | None = None


@dataclass(frozen=True)
class Section:
    """One slice of the document, from a heading up to the next heading.

    Attributes:
        label:            canonical section label, e.g. "questionnaire". None
                          when the heading could not be classified — Step 2
                          flags rather than guesses.
        heading_text:     heading text exactly as it appeared. Empty string for
                          the preamble section, which has no heading.
        heading_style:    Word style of the heading paragraph, e.g. "Heading 1".
                          Empty for the preamble.
        label_provenance: one of LABEL_EXTRACTED / LABEL_DERIVED /
                          LABEL_INFERRED / LABEL_UNKNOWN (CLAUDE.md §14).
        blocks:           the section's content blocks, in document order,
                          excluding the heading paragraph itself.
        requires_review:  True when a reviewer needs to look at this section.
        source_reference: position of the heading (or of the first content block
                          for the preamble).
    """

    label: str | None
    heading_text: str
    heading_style: str
    label_provenance: str
    blocks: list[DocumentBlock]
    requires_review: bool
    source_reference: SourceReference

    @property
    def paragraph_count(self) -> int:
        return sum(1 for b in self.blocks if b.kind == "paragraph")

    @property
    def table_count(self) -> int:
        return sum(1 for b in self.blocks if b.kind == "table")


@dataclass(frozen=True)
class SectionedDocument:
    """Step 2's output: the document sliced into labelled sections.

    Attributes:
        document_name:  source file name, carried through from Step 1.
        source_format:  carried through from Step 1.
        sections:       every section in document order, including unclassified
                        ones and the preamble. Primary output.
        review_queue:   flagged items — unclassified headings, known section
                        types not found, documents with no detectable structure.
        known_labels:   the section-type vocabulary this run was classified
                        against, recorded so a later run's output can be
                        compared against the same vocabulary.
    """

    document_name: str
    source_format: str
    sections: list[Section]
    review_queue: list[ReviewItem]
    known_labels: list[str] = field(default_factory=list)

    def by_label(self) -> dict[str, list[DocumentBlock]]:
        """The step table's `{section_label: content_block}` view.

        Unclassified sections are omitted — they have no label to key on and are
        reachable via `sections` and `review_queue`. Where a label legitimately
        repeats, the blocks are concatenated in document order, so no content is
        lost through the flattening.
        """
        merged: dict[str, list[DocumentBlock]] = {}
        for section in self.sections:
            if section.label is None:
                continue
            merged.setdefault(section.label, []).extend(section.blocks)
        return merged

    @property
    def unclassified_sections(self) -> list[Section]:
        """Sections whose heading could not be matched to a known type."""
        return [s for s in self.sections if s.label is None]
