import unicodedata

import pytest

from neos.workflow.deep_analysis.text_norm import (
    claim_hash,
    excerpt_matches,
    normalize_for_hash,
    normalize_for_match,
)


pytestmark = pytest.mark.no_db


def test_hash_normalization_strips_punctuation_and_case():
    assert normalize_for_hash("The MoE, routing!") == normalize_for_hash(
        "the moe routing"
    )


def test_match_normalization_preserves_case_and_collapses_whitespace():
    assert normalize_for_match("Hello   World") == "Hello World"
    assert normalize_for_match("Hello") != normalize_for_match("hello")


def test_both_normalizers_apply_unicode_nfc():
    decomposed = unicodedata.normalize("NFD", "한글 café")

    assert normalize_for_hash(decomposed) == normalize_for_hash("한글 café")
    assert normalize_for_match(decomposed) == normalize_for_match("한글 café")


def test_claim_hash_is_sixteen_lowercase_hex_characters():
    value = claim_hash("some claim")

    assert len(value) == 16
    assert all(char in "0123456789abcdef" for char in value)


def test_exact_and_fuzzy_excerpt_matching():
    assert excerpt_matches(
        "quick brown fox",
        "the quick brown fox jumps over the lazy dog",
        0.92,
    )
    assert excerpt_matches(
        "mixture of experts routing scheme",
        "GLM uses a mixture-of-experts routing scheme for efficiency",
        0.92,
    )


def test_empty_or_unrelated_excerpt_does_not_match():
    assert not excerpt_matches("", "source", 0.92)
    assert not excerpt_matches(
        "quantum entanglement theory",
        "completely unrelated content here",
        0.92,
    )
