"""Deterministic extraction: NormalizedDocument -> QREExtractionIR.

Part 1's second half. Ingestion found the text; this finds the survey facts
stated in it - questions, options, instructions, sections - without deciding
what any of them mean (CLAUDE.md Sections 7.1 and 19).

No LLM is used here. Section 29 reserves the model for genuine semantic
reasoning, and recognising that a table holds questions is pattern matching, not
interpretation. Keeping this stage deterministic also makes it reproducible by
construction and testable without mocking anything.
"""

from __future__ import annotations

from .extractor import (
    ExtractionPatterns,
    classify_instruction,
    find_question_id,
    load_patterns,
    map_columns,
    normalize_header,
    split_options,
)
from .reader import READER, READER_VERSION, read, read_file

__all__ = [
    "READER",
    "READER_VERSION",
    "ExtractionPatterns",
    "classify_instruction",
    "find_question_id",
    "load_patterns",
    "map_columns",
    "normalize_header",
    "read",
    "read_file",
    "split_options",
]
