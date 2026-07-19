"""Distinct normalization rules for claim hashes and evidence matching."""

import hashlib
import re
import unicodedata
from difflib import SequenceMatcher


_WHITESPACE = re.compile(r"\s+")
_PUNCTUATION = re.compile(r"[^\w\s]", re.UNICODE)
_ANCHOR = re.compile(r"\w+", re.UNICODE)


def normalize_for_hash(text: str) -> str:
    """Normalize semantic claim identity: NFC, lowercase, no punctuation."""

    normalized = unicodedata.normalize("NFC", text).lower()
    without_punctuation = _PUNCTUATION.sub("", normalized)
    return _WHITESPACE.sub(" ", without_punctuation).strip()


def normalize_for_match(text: str) -> str:
    """Normalize source comparison while preserving case and punctuation."""

    normalized = unicodedata.normalize("NFC", text)
    return _WHITESPACE.sub(" ", normalized).strip()


def claim_hash(text: str) -> str:
    normalized = normalize_for_hash(text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def excerpt_match_score(excerpt: str, raw: str, threshold: float) -> float:
    """Return the best score from the bounded excerpt matching algorithm."""

    candidate = normalize_for_match(excerpt)
    source = normalize_for_match(raw)
    if not candidate:
        return 0.0
    if candidate in source:
        return 1.0

    anchors = sorted(
        _ANCHOR.finditer(candidate),
        key=lambda match: len(match.group(0)),
        reverse=True,
    )
    if not anchors:
        return 0.0

    tolerance = max(1, round(len(candidate) * (1 - threshold)))
    best_score = 0.0
    for anchor_match in anchors:
        anchor = anchor_match.group(0)
        source_pos = source.find(anchor)
        while source_pos >= 0:
            expected_start = source_pos - anchor_match.start()
            for shift in range(-tolerance, tolerance + 1):
                start = max(0, expected_start + shift)
                segment = source[start : start + len(candidate)]
                score = SequenceMatcher(None, candidate, segment).ratio()
                best_score = max(best_score, score)
            source_pos = source.find(anchor, source_pos + len(anchor))

    return best_score


def excerpt_matches(excerpt: str, raw: str, threshold: float) -> bool:
    """Match exact text first, then inspect only anchor-adjacent fuzzy windows."""

    return excerpt_match_score(excerpt, raw, threshold) >= threshold
