"""provider 참조 봉인 -- 원장이 유출돼도 provider 세션을 조작할 수 없게 한다."""

import base64
import binascii
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


_NONCE_BYTES = 12
_VERSION_BYTES = 2
# AES-128/192/256-GCM 이 허용하는 키 길이. AESGCM(key) 생성자 자체가 이
# 세 길이만 받으므로 여기서 미리 걸러 더 명확한 오류 메시지를 낸다.
_VALID_KEY_BYTE_LENGTHS = frozenset({16, 24, 32})


class AesGcmProviderReferenceCipher:
    """provider 참조를 봉인한다.

    평문 참조는 저장도 로깅도 하지 않는다 -- 원장이 유출돼도 provider 세션을
    직접 조작할 수 없어야 한다. AAD 에 allocation_id:provider:generation 을 묶어
    다른 할당의 봉인을 가져다 쓰는 것을 막는다.
    """

    __slots__ = ("_aesgcm", "_associated_data", "_key_version")

    def __init__(self, *, key: bytes, key_version: int, associated_data: str) -> None:
        if len(key) not in _VALID_KEY_BYTE_LENGTHS:
            raise ValueError("managed_cipher_key_invalid")
        if key_version < 1:
            raise ValueError("managed_cipher_key_version_invalid")
        self._aesgcm = AESGCM(key)
        self._key_version = key_version
        self._associated_data = associated_data.encode("utf-8")

    def encrypt(self, provider_ref: str) -> bytes:
        nonce = os.urandom(_NONCE_BYTES)
        sealed = self._aesgcm.encrypt(
            nonce, provider_ref.encode("utf-8"), self._associated_data
        )
        return self._key_version.to_bytes(_VERSION_BYTES, "big") + nonce + sealed

    def decrypt(self, encrypted_ref: bytes) -> str:
        nonce = encrypted_ref[_VERSION_BYTES : _VERSION_BYTES + _NONCE_BYTES]
        sealed = encrypted_ref[_VERSION_BYTES + _NONCE_BYTES :]
        return self._aesgcm.decrypt(nonce, sealed, self._associated_data).decode(
            "utf-8"
        )

    # __repr__ 을 정의하지 않는다 -- 기본 repr 은 키를 노출하지 않는다.


def decode_provider_reference_key(secret: str) -> bytes:
    """base64 로 인코딩된 시크릿 문자열을 원시 키 바이트로 디코딩한다.

    `.env`/config 에는 임의 바이트를 그대로 넣을 수 없으므로 base64 문자열로
    보관한다 -- 런타임 배선(`neos/coding/runtime.py`)과 설정 검증
    (`neos/config/schema.py`)이 이 함수를 공유하지 않고 각자 최소 형태로
    구현하는 이유는 `neos/config/schema.py`가 `neos.coding.*` 기능 모듈에
    의존하지 않는 계층 경계를 지키기 위해서다 -- 대신 두 곳 모두 같은
    `_VALID_KEY_BYTE_LENGTHS` 값(16/24/32)을 이름 붙인 상수로 검증한다.
    """
    try:
        return base64.b64decode(secret, validate=True)
    except (binascii.Error, ValueError) as error:
        raise ValueError("managed_provider_reference_key_invalid_encoding") from error
