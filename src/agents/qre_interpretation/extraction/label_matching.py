"""Shared label matching for the extraction steps.

Step 2 matches section headings against a known section vocabulary; Step 4
matches table column headers against a known column-role vocabulary. Both are the
same operation — normalize a human-written label, then look it up in an alias
registry — so the logic lives here once rather than in each step.

Normalization is deliberately conservative: it removes formatting noise only
(case, punctuation, whitespace, ampersands) and never rewrites or stems words. It
therefore cannot silently reinterpret a label's meaning, which matters because a
mis-matched label routes content to the wrong place (CLAUDE.md §40).
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence


def normalize_label(text: str) -> str:
    """Reduce a human-written label to a comparable key.

    Lowercases, expands "&" to "and", drops punctuation, collapses whitespace.
    "Routing & Termination:", "routing and termination" and "ROUTING/TERMINATION"
    all converge on "routing and termination".
    """
    text = text.lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


#: Minimum share of a header's tokens an alias must cover to count as a match.
#: 0.5 keeps "Base / Validation" -> validation (1 of 2 tokens) while rejecting
#: "No. of visits" -> id (1 of 3 tokens), where "no" is incidental wording rather
#: than the column's subject.
MIN_MATCH_SCORE = 0.5


def _is_token_subsequence(needle: Sequence[str], haystack: Sequence[str]) -> bool:
    """True if `needle` appears as a contiguous run of tokens inside `haystack`.

    Token-level, never substring: "id" must not match inside "Validation", and
    "no" must not match inside "Notes".
    """
    if not needle or len(needle) > len(haystack):
        return False
    for start in range(len(haystack) - len(needle) + 1):
        if list(haystack[start : start + len(needle)]) == list(needle):
            return True
    return False


def score_label(
    label: str, vocabulary: Mapping[str, Sequence[str]]
) -> dict[str, float]:
    """Score a label against every canonical name in a vocabulary.

    Whole-string alias matching is too brittle for arbitrary documents: a header
    reading "Base / Validation" fails an exact lookup even though "validation" is
    a known alias, so a QRE phrasing a column slightly differently than the alias
    list gets no match at all. That made matching depend on the sample corpus's
    exact wording, which CLAUDE.md §10 forbids.

    So an alias matches when its tokens appear as a contiguous run inside the
    label's tokens, and the score is the share of the label those tokens cover.
    Scoring by coverage means the most specific match wins: for "Base /
    Validation", "validation" (1 of 2 tokens) beats a weaker partial hit
    elsewhere, and a header that merely mentions a keyword in passing scores too
    low to qualify.

    Args:
        label:      the human-written label, e.g. a table column header.
        vocabulary: {canonical_name: (alias, ...)}.

    Returns:
        {canonical_name: best score} for every name scoring at or above
        MIN_MATCH_SCORE. Empty when nothing matched. The caller decides how to
        resolve competing names — see `question_parser._map_columns`, which
        assigns globally by best score rather than left to right.
    """
    tokens = normalize_label(label).split()
    if not tokens:
        return {}

    scores: dict[str, float] = {}
    for canonical, aliases in vocabulary.items():
        # The canonical name counts as an alias of itself.
        candidates = [canonical.replace("_", " "), *aliases]
        best = 0.0
        for alias in candidates:
            alias_tokens = normalize_label(alias).split()
            if _is_token_subsequence(alias_tokens, tokens):
                best = max(best, len(alias_tokens) / len(tokens))
        if best >= MIN_MATCH_SCORE:
            scores[canonical] = best
    return scores


def build_alias_index(vocabulary: Mapping[str, Sequence[str]]) -> dict[str, str]:
    """Invert {canonical_name: aliases} into {normalized_alias: canonical_name}.

    Each canonical name is registered as an alias of itself, with underscores
    treated as spaces, so "quota_controls" matches a heading reading "Quota
    controls" even when that exact wording is absent from its alias tuple.
    """
    index: dict[str, str] = {}
    for canonical, aliases in vocabulary.items():
        index[normalize_label(canonical.replace("_", " "))] = canonical
        for alias in aliases:
            index[normalize_label(alias)] = canonical
    return index
