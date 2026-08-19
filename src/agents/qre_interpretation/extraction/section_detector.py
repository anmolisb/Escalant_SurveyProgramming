"""Agent 1 · Part 1 · Step 2 — Dynamic section detection.

    In:  NormalizedDocument (from Step 1)
    Out: SectionedDocument — sections in document order, plus a review queue.
         `.by_label()` gives the step table's {section_label: content_block} dict.

Mechanism, in the order the step table describes it:

  1. Detect heading-like elements **structurally** — by Word style, not by
     matching heading titles against a list of expected names. A QRE using
     different section names still slices correctly (CLAUDE.md §9, §10).
  2. Classify each heading against known section types. Deterministic alias
     matching handles the recognized vocabulary; an optional injected
     classifier handles the rest.
  3. Slice the document into named blocks at heading boundaries.
  4. **Flag** unlabeled or missing sections rather than guessing them.

On the LLM call. Classification is layered, per CLAUDE.md §29 — deterministic
code first, model only where semantics are genuinely required:

  - A heading that matches the known vocabulary resolves deterministically. No
    model is called, and the label is marked `extracted`.
  - A heading that does not match is passed to the injected `classifier`. The
    Groq-backed implementation lives in
    `src/common/prompts/qre_interpretation.py`; its label is marked `inferred`
    and re-checked against the vocabulary here before it is accepted (§17).
  - With no classifier supplied, or when the call fails, the heading is flagged
    for review rather than guessed.

This module stays provider-agnostic: it depends on the `SectionClassifier`
signature, not on Groq. Swapping in the Azure client named by CLAUDE.md §52
requires no change here.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

from ..ingestion.normalized_document import (
    DocumentBlock,
    NormalizedDocument,
    NormalizedParagraph,
    SourceReference,
)
from .label_matching import build_alias_index, normalize_label
from .sectioned_document import (
    LABEL_DERIVED,
    LABEL_EXTRACTED,
    LABEL_INFERRED,
    LABEL_UNKNOWN,
    PREAMBLE_LABEL,
    ReviewItem,
    Section,
    SectionedDocument,
)

# ---------------------------------------------------------------------------
# Known section-type vocabulary
# ---------------------------------------------------------------------------
# Category-3 material under CLAUDE.md §61 — patterns observed in the sample
# corpus, not confirmed Escalent rules. It must therefore stay configurable:
# callers override it via `detect_sections(..., section_types=...)` rather than
# editing this dict, and an unrecognized heading is flagged, never forced into
# the nearest entry. Aliases are matched on normalized text (see label_matching).
DEFAULT_SECTION_TYPES: Mapping[str, tuple[str, ...]] = {
    "study_specification": (
        "study specification",
        "study specifications",
        "study overview",
        "background",
        "objectives",
        "study details",
    ),
    "questionnaire": (
        "questionnaire",
        "main questionnaire",
        "question list",
        "questions",
        "survey questions",
    ),
    "routing_and_termination": (
        "routing and termination",
        "routing",
        "routing and logic",
        "skip logic",
        "logic and routing",
        "termination",
        "terminations",
    ),
    "quota_controls": (
        "quota controls",
        "quotas",
        "quota",
        "sample plan",
        "sampling and quotas",
    ),
    "programming_and_qa_requirements": (
        "programming and qa requirements",
        "programming notes",
        "programming requirements",
        "qa requirements",
        "programming and qa",
    ),
    "acceptance_test_scenarios": (
        "acceptance test scenarios",
        "acceptance tests",
        "test scenarios",
        "test cases",
    ),
    "completion_messages": (
        "completion messages",
        "completion message",
        "dispositions",
        "disposition messages",
        "end messages",
        "closing messages",
    ),
}

#: Signature of an optional semantic classifier for unrecognized headings.
#: Receives the raw heading text and the allowed labels; returns a label from
#: that list, or None to leave the heading unclassified. Implementations must
#: route through the approved LLM client (CLAUDE.md §52).
SectionClassifier = Callable[[str, Sequence[str]], str | None]

#: Default for the `classifier` argument, meaning "use whatever the project is
#: configured to use". Distinct from None, which explicitly disables the model.
USE_CONFIGURED_LLM = "__use_configured_llm__"


def _configured_classifier() -> SectionClassifier | None:
    """The project's configured heading classifier, or None if unavailable.

    Imported lazily and only when the LLM is actually enabled, so this module
    keeps no import-time dependency on any provider. Swapping the runtime means
    changing the prompt layer, not this file (CLAUDE.md §52).
    """
    from common.config import get_settings

    if not get_settings().llm_enabled:
        return None
    from common.prompts.qre_interpretation import classify_section_heading

    return classify_section_heading


def _is_heading(block: DocumentBlock) -> bool:
    """True if a block is a heading, judged structurally.

    Uses the Word style name: any paragraph styled "Heading 1", "Heading 2", …
    counts. Two rules this deliberately does NOT use:

      - Heading *titles*. Matching against expected names would make the slicer
        fail on any QRE that names its sections differently (CLAUDE.md §9).
      - Bold text. In the sample QRE the study-specification lines
        ("Business objective: …", "Mode: …") are bold body paragraphs; treating
        bold as a heading signal would shatter that section into six false
        sections. Bold stays what Step 1 recorded it as — a formatting fact for
        Step 3's label detection, not a structural one.
    """
    if not isinstance(block, NormalizedParagraph):
        return False
    return block.style_name.strip().lower().startswith("heading") and bool(
        block.text.strip()
    )


def _classify(
    heading_text: str,
    alias_index: Mapping[str, str],
    known_labels: Sequence[str],
    classifier: SectionClassifier | None,
) -> tuple[str | None, str]:
    """Resolve heading text to a canonical label.

    Returns:
        (label, label_provenance). `label` is None when neither the alias index
        nor the classifier could resolve it — the flagged, non-guessed case.
    """
    direct = alias_index.get(normalize_label(heading_text))
    if direct is not None:
        return direct, LABEL_EXTRACTED

    if classifier is not None:
        proposed = classifier(heading_text, known_labels)
        # Guard the boundary: a classifier that invents a label outside the
        # agreed vocabulary must not silently widen the contract (CLAUDE.md §17).
        if proposed in known_labels:
            return proposed, LABEL_INFERRED

    return None, LABEL_UNKNOWN


def detect_sections(
    document: NormalizedDocument,
    section_types: Mapping[str, Sequence[str]] | None = None,
    classifier: SectionClassifier | None | str = USE_CONFIGURED_LLM,
) -> SectionedDocument:
    """Slice a NormalizedDocument into labelled sections.

    Args:
        document:      Step 1 output.
        section_types: optional override of the known-section vocabulary,
                       shaped {canonical_label: (alias, ...)}. Defaults to
                       DEFAULT_SECTION_TYPES.
        classifier:    semantic classifier for headings the vocabulary does not
                       cover. Defaults to the project's configured LLM, so a
                       caller gets it without wiring anything. Pass None to force
                       deterministic-only behaviour, or a callable to inject your
                       own.

    Returns:
        SectionedDocument. Every block of the input appears in exactly one
        section, so nothing is lost regardless of classification outcome
        (CLAUDE.md §16).
    """
    if classifier is USE_CONFIGURED_LLM:
        classifier = _configured_classifier()

    types = DEFAULT_SECTION_TYPES if section_types is None else section_types
    alias_index = build_alias_index(types)
    known_labels = list(types.keys())

    sections: list[Section] = []
    review_queue: list[ReviewItem] = []

    # Split the block sequence at heading boundaries. Content before the first
    # heading becomes the preamble; without it, title-page blocks would vanish.
    preamble_blocks: list[DocumentBlock] = []
    heading_positions = [i for i, b in enumerate(document.blocks) if _is_heading(b)]

    if heading_positions:
        preamble_blocks = document.blocks[: heading_positions[0]]
    else:
        preamble_blocks = list(document.blocks)

    if any(b.text.strip() if b.kind == "paragraph" else b.rows for b in preamble_blocks):
        first = preamble_blocks[0]
        sections.append(
            Section(
                label=PREAMBLE_LABEL,
                heading_text="",
                heading_style="",
                # Derived, not extracted: no heading in the document says
                # "preamble" — Step 2 named this slice by position.
                label_provenance=LABEL_DERIVED,
                blocks=preamble_blocks,
                requires_review=False,
                source_reference=SourceReference(
                    document=document.document_name, order_index=first.order_index
                ),
            )
        )

    # A document with no heading styles cannot be sliced structurally. Report
    # that plainly instead of inventing boundaries from formatting guesses.
    if not heading_positions:
        review_queue.append(
            ReviewItem(
                element=document.document_name,
                reason="no_headings_detected",
                detail=(
                    "No paragraphs use a Word 'Heading' style, so the document "
                    "could not be sliced into sections. All content is held in "
                    f"the '{PREAMBLE_LABEL}' section pending review."
                ),
            )
        )
        return SectionedDocument(
            document_name=document.document_name,
            source_format=document.source_format,
            sections=sections,
            review_queue=review_queue,
            known_labels=known_labels,
        )

    # Each heading owns the blocks between it and the next heading.
    for position, start in enumerate(heading_positions):
        heading = document.blocks[start]
        end = (
            heading_positions[position + 1]
            if position + 1 < len(heading_positions)
            else len(document.blocks)
        )
        body = document.blocks[start + 1 : end]

        label, provenance = _classify(
            heading.text, alias_index, known_labels, classifier
        )
        # The heading text differs from the section object holding the
        # reference, so provenance carries it (see SourceReference.text).
        reference = SourceReference(
            document=document.document_name,
            order_index=heading.order_index,
            text=heading.text,
        )

        if label is None:
            review_queue.append(
                ReviewItem(
                    element=heading.text,
                    reason="heading_not_classified",
                    detail=(
                        f"Heading '{heading.text}' did not match any known "
                        "section type. Its content is preserved unclassified; "
                        "add an alias or extend the vocabulary if this section "
                        "type is real."
                    ),
                    source_reference=reference,
                )
            )

        sections.append(
            Section(
                label=label,
                heading_text=heading.text,
                heading_style=heading.style_name,
                label_provenance=provenance,
                blocks=body,
                requires_review=label is None,
                source_reference=reference,
            )
        )

    # Report known section types absent from this document. Informational, not
    # an error: CLAUDE.md §9 forbids requiring any section to exist in every QRE.
    found = {s.label for s in sections if s.label is not None}
    for label in known_labels:
        if label not in found:
            review_queue.append(
                ReviewItem(
                    element=label,
                    reason="known_section_not_found",
                    detail=(
                        f"No section matched the known type '{label}'. This is "
                        "informational — not every QRE contains every section."
                    ),
                )
            )

    return SectionedDocument(
        document_name=document.document_name,
        source_format=document.source_format,
        sections=sections,
        review_queue=review_queue,
        known_labels=known_labels,
    )
