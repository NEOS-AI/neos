"""provider 참조 봉인 -- 원장이 유출돼도 provider 세션을 조작할 수 없게 한다."""

import base64
import binascii
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


_NONCE_BYTES = 12
_VERSION_BYTES = 2
# 봉인 값이 최소 이 길이는 돼야 버전·nonce 를 슬라이싱할 수 있다(암호문·태그는
# 없어도 된다 -- 그 경우는 AEAD 인증 실패로 자연스럽게 갈라진다). 이보다
# 짧으면 슬라이싱이 조용히 짧은 nonce 를 만들어 AESGCM 이 다른(untyped) 예외를
# 내게 된다 -- 그래서 슬라이싱 전에 길이부터 검사한다.
_MIN_SEALED_BYTES = _VERSION_BYTES + _NONCE_BYTES
# AES-128/192/256-GCM 이 허용하는 키 길이. AESGCM(key) 생성자 자체가 이
# 세 길이만 받으므로 여기서 미리 걸러 더 명확한 오류 메시지를 낸다.
_VALID_KEY_BYTE_LENGTHS = frozenset({16, 24, 32})


class ProviderReferenceCipherError(RuntimeError):
    """provider 참조 봉인/복호화 실패의 공통 기반.

    `ManagedAdapterError`(`neos.coding.managed.adapters.base`)와 같은 모양의
    taxonomy다 -- 공통 기반 하나 + 원인별 구체 타입. `cryptography` 라이브러리의
    예외가 이 모듈 밖 도메인 코드로 새 나가지 않게 여기서 잡아 옮긴다.
    """


class ProviderReferenceAuthenticationError(ProviderReferenceCipherError):
    """AEAD 인증 실패 -- 변조되었거나, AAD·키가 다른 봉인을 복호화하려 한 경우.

    나중에 이 cipher가 실제로 배선되면 호출자는 이 타입을
    `ProviderErrorCode.PROVIDER_AUTH_ERROR` / `MANUAL_RECOVERY_REQUIRED`로
    옮겨야 한다 -- `ManagedAdapterOwnershipError` -> `PROVIDER_AUTH_ERROR`
    매핑과 같은 자리다 (`neos.coding.managed.allocation._error_code` 참고).
    """


class ProviderReferenceKeyVersionMismatch(ProviderReferenceCipherError):
    """봉인에 박힌 key_version 이 이 cipher 가 쥔 key_version 과 다르다.

    키 로테이션이 있는 한 반드시 검사해야 한다 -- 검사하지 않으면 이미 퇴역한
    키로 봉인된 값을 새 키를 쥔 cipher 가 조용히(그리고 틀리게) 복호화해
    받아들이는 사고가 난다.
    """


class ProviderReferenceMalformedError(ProviderReferenceCipherError):
    """봉인 값이 버전·nonce 조차 담을 수 없을 만큼 짧다.

    `BYTEA` 컬럼은 어떤 길이든 담을 수 있어 손상되거나 잘린 행에서도 나올 수
    있다 -- 공격이 아니어도 발생한다. 길이 부족을 버전 불일치나 인증 실패로
    잘못 진단하지 않도록 슬라이싱보다 먼저 걸러낸다.
    """


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
        if len(encrypted_ref) < _MIN_SEALED_BYTES:
            raise ProviderReferenceMalformedError(
                f"sealed reference is {len(encrypted_ref)} bytes, "
                f"expected at least {_MIN_SEALED_BYTES} (version + nonce)"
            )
        embedded_version = int.from_bytes(encrypted_ref[:_VERSION_BYTES], "big")
        if embedded_version != self._key_version:
            # 이 cipher 가 쥔 키가 이 봉인을 만든 키와 실제로 같은 것인지는
            # AEAD 인증(아래)이 결국 증명해주지만, 그건 이미 잘못된 평문 후보를
            # 만들어 낸 *뒤에* 확인하는 것이다. 버전이 안 맞으면 그 시도 자체를
            # 하지 않는다 -- 키 로테이션 중 퇴역한 키로 봉인된 값을 새 키를 쥔
            # cipher 가 (우연히) 인증까지 통과시켜 받아들이는 경우를 막는다.
            raise ProviderReferenceKeyVersionMismatch(
                f"sealed under key_version={embedded_version}, "
                f"this cipher serves key_version={self._key_version}"
            )
        nonce = encrypted_ref[_VERSION_BYTES : _VERSION_BYTES + _NONCE_BYTES]
        sealed = encrypted_ref[_VERSION_BYTES + _NONCE_BYTES :]
        try:
            plaintext = self._aesgcm.decrypt(nonce, sealed, self._associated_data)
        except InvalidTag as error:
            raise ProviderReferenceAuthenticationError(
                "provider reference authentication failed"
            ) from error
        return plaintext.decode("utf-8")

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
