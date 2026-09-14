"""Deterministic identifiers and the HMAC ownership digest.

모든 식별자는 같은 입력에서 항상 같은 값이 나온다 -- 프로세스가 재시작해도
원장 행의 (owner, task, ordinal, generation)만으로 allocation id, idempotency
key, provider name/tag를 다시 계산해 재발견할 수 있어야 한다.

ownership digest는 **키가 있는** HMAC이다. 키 없는 sha256은 원장이나 provider
metadata를 쓸 수 있는 누구나 다시 계산할 수 있어 소유권의 증거가 되지 못한다.
키는 `secrets.managed_provider_reference_key`에서 도메인 분리 라벨로 **파생**한다
-- 같은 바이트를 AES-GCM 봉인 키와 HMAC 키로 동시에 쓰지 않는다.
"""

from __future__ import annotations

import hashlib
import hmac

from neos.coding.managed.crypto import decode_provider_reference_key

_OWNERSHIP_KEY_LABEL = b"neos/coding-sandbox/ownership-hmac/v1"
_MIN_KEY_BYTES = 16
_ID_HEX = 32
IDEMPOTENCY_PREFIX = "neos-coding-sbx:v1:"
DIGEST_PREFIX = "hmac-sha256:"

# provider metadata/tag keys. 할당 어댑터(`managed/adapters/e2b.py`)의 상수를
# 가져다 쓰지 않는다 -- 코딩 provider의 recovery index는 별도 계약이다.
METADATA_SANDBOX_ID = "neos_sandbox_id"
METADATA_ALLOCATION_ID = "neos_allocation_id"
METADATA_IDEMPOTENCY_KEY = "neos_idempotency_key"
METADATA_OWNERSHIP_DIGEST = "neos_ownership_digest"
METADATA_GENERATION = "neos_generation"


def derive_ownership_key(reference_key: bytes) -> bytes:
    if len(reference_key) < _MIN_KEY_BYTES:
        raise ValueError("managed_ownership_key_too_short")
    return hmac.new(reference_key, _OWNERSHIP_KEY_LABEL, hashlib.sha256).digest()


def ownership_key_from_secret(secret: str) -> bytes:
    """`secrets.managed_provider_reference_key` (base64) -> HMAC key."""
    return derive_ownership_key(decode_provider_reference_key(secret))


def _encode(parts: tuple[str, ...]) -> bytes:
    # 길이 접두 인코딩: 어떤 구분자를 고르든 owner id 안에 그 문자가 들어올 수
    # 있다. ("a:b", "c") 와 ("a", "b:c") 가 같은 MAC 이 되면 안 된다.
    return b"".join(
        f"{len(encoded)}:".encode("ascii") + encoded
        for encoded in (part.encode("utf-8") for part in parts)
    )


class SandboxIdentity:
    __slots__ = ("_key",)

    def __init__(self, key: bytes) -> None:
        if len(key) < _MIN_KEY_BYTES:
            raise ValueError("managed_ownership_key_too_short")
        self._key = key

    def _mac(self, *parts: str) -> str:
        return hmac.new(self._key, _encode(parts), hashlib.sha256).hexdigest()

    def sandbox_id(self, *, owner_id: str, task_id: str, ordinal: int) -> str:
        return "sbx_" + self._mac("sandbox", owner_id, task_id, str(ordinal))[:_ID_HEX]

    def allocation_id(self, *, sandbox_id: str, generation: int) -> str:
        return "alc_" + self._mac("allocation", sandbox_id, str(generation))[:_ID_HEX]

    @staticmethod
    def idempotency_key(allocation_id: str) -> str:
        return IDEMPOTENCY_PREFIX + allocation_id

    @staticmethod
    def provider_name(allocation_id: str) -> str:
        """Deterministic vendor name/tag. Used as an idempotency aid only."""
        return "neos-" + allocation_id.replace("_", "-")

    def ownership_digest(
        self, *, allocation_id: str, owner_id: str, generation: int
    ) -> str:
        return DIGEST_PREFIX + self._mac("owner", allocation_id, owner_id, str(generation))

    def verify_ownership(
        self,
        digest: str | None,
        *,
        allocation_id: str,
        owner_id: str,
        generation: int,
    ) -> bool:
        if not digest:
            return False
        expected = self.ownership_digest(
            allocation_id=allocation_id, owner_id=owner_id, generation=generation
        )
        return hmac.compare_digest(digest, expected)

    def snapshot_id(
        self, *, sandbox_id: str, generation: int, provider_snapshot_ref: str
    ) -> str:
        return "snp_" + self._mac(
            "snapshot", sandbox_id, str(generation), provider_snapshot_ref
        )[:_ID_HEX]

    def __repr__(self) -> str:  # 키를 repr 에 노출하지 않는다.
        return "SandboxIdentity(<key>)"
