import pytest

from neos.coding.managed.crypto import (
    AesGcmProviderReferenceCipher,
    ProviderReferenceAuthenticationError,
    ProviderReferenceKeyVersionMismatch,
)


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
    with pytest.raises(ProviderReferenceAuthenticationError):
        other.decrypt(sealed)


def test_a_wrong_key_cannot_decrypt() -> None:
    sealed = _cipher().encrypt("ref_secret")
    other = AesGcmProviderReferenceCipher(
        key=bytes(32), key_version=1, associated_data="msa_1:docker:1"
    )
    with pytest.raises(ProviderReferenceAuthenticationError):
        other.decrypt(sealed)


def test_a_different_key_version_is_rejected_before_authentication() -> None:
    """키 로테이션 중 퇴역한 키로 봉인된 값을 새 버전의 cipher가 받아들이면 안 된다.

    같은 원시 키를 쓰더라도(로테이션은 보통 키 자체도 바뀌지만, 버전 검사가
    키 일치 여부와 무관하게 독립적으로 동작해야 함을 보이기 위해 여기서는
    키를 고정한다) 봉인에 박힌 key_version 이 cipher 가 쥔 key_version 과
    다르면 AEAD 인증을 시도하기도 전에 거부해야 한다.
    """
    sealed = _cipher(key_version=1).encrypt("ref_secret")
    other = AesGcmProviderReferenceCipher(
        key=KEY, key_version=2, associated_data="msa_1:docker:1"
    )
    with pytest.raises(ProviderReferenceKeyVersionMismatch):
        other.decrypt(sealed)
