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


def excerpt_matches(excerpt: str, raw: str, threshold: float) -> bool:
    """Match exact text first, then inspect only anchor-adjacent fuzzy windows."""

    candidate = normalize_for_match(excerpt)
    source = normalize_for_match(raw)
    if not candidate:
        return False
    if candidate in source:
        return True

    anchors = sorted(
        _ANCHOR.finditer(candidate),
        key=lambda match: len(match.group(0)),
        reverse=True,
    )
    if not anchors:
        return False

    tolerance = max(1, round(len(candidate) * (1 - threshold)))
    for anchor_match in anchors:
        anchor = anchor_match.group(0)
        source_pos = source.find(anchor)
        while source_pos >= 0:
            expected_start = source_pos - anchor_match.start()
            for shift in range(-tolerance, tolerance + 1):
                start = max(0, expected_start + shift)
                segment = source[start : start + len(candidate)]
                if (
                    SequenceMatcher(None, candidate, segment).ratio()
                    >= threshold
                ):
                    return True
            source_pos = source.find(anchor, source_pos + len(anchor))

    return False
