import pytest

from neos.coding.managed.crypto import AesGcmProviderReferenceCipher


KEY = bytes(range(32))


def _cipher(key_version: int = 1) -> AesGcmProviderReferenceCipher:
    return AesGcmProviderReferenceCipher(
        key=KEY,
        key_version=key_version,
        associated_data="msa_1:docker:1",
    )


def test_roundtrip_recovers_the_reference() -> None:
    cipher = _cipher()
    assert cipher.decrypt(cipher.encrypt("ref_secret")) == "ref_secret"


def test_ciphertext_never_contains_the_plaintext() -> None:
    assert b"ref_secret" not in _cipher().encrypt("ref_secret")


def test_nonce_is_random_so_ciphertexts_differ() -> None:
    cipher = _cipher()
    assert cipher.encrypt("ref_secret") != cipher.encrypt("ref_secret")


def test_a_different_allocation_cannot_decrypt() -> None:
    """AAD 가 allocation_id:provider:generation 이므로 교차 복호가 막힌다."""
    sealed = _cipher().encrypt("ref_secret")
    other = AesGcmProviderReferenceCipher(
        key=KEY, key_version=1, associated_data="msa_2:docker:1"
    )
    with pytest.raises(Exception):
        other.decrypt(sealed)


def test_a_wrong_key_cannot_decrypt() -> None:
    sealed = _cipher().encrypt("ref_secret")
    other = AesGcmProviderReferenceCipher(
        key=bytes(32), key_version=1, associated_data="msa_1:docker:1"
    )
    with pytest.raises(Exception):
        other.decrypt(sealed)
