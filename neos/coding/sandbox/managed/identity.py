"""Deterministic identifiers and the keyed physical ownership digest.

관리형 코딩 샌드박스는 **할당 평면이 만든 allocation 에 붙는다**
(`neos.coding.managed`, 045). 그래서 식별자는 두 층이다.

* **할당 층 (기존, 그대로 둔다).** `allocation_id`, admission 의 idempotency key,
  `sha256:` 레거시 ownership digest (`neos.coding.managed.allocation`). vendor
  metadata 의 `neos_allocation_id` / `neos_idempotency_key` /
  `neos_ownership_digest` 가 이 층이다. 정리 서비스가 이 digest 로 destroy 를
  허가하므로 바꾸지 않는다.
* **물리 층 (이 모듈).** 논리 샌드박스 id 는 allocation 에서 결정적으로 나오고,
  vendor object 하나하나는 `incarnation` 으로 구별한다 (Modal cold resume 이
  object 를 교체한다). 물리 digest 는 **별도의 32바이트 host 키**로 만든 HMAC 이다
  -- `secrets.managed_coding_ownership_key`. 참조 봉인 키
  (`managed_provider_reference_key`)와 섞지 않는다.

모든 새 vendor object 는 두 digest 를 **모두** 싣고, 붙기 전에 둘 다 검증한다.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime

OWNERSHIP_KEY_BYTES = 32
DIGEST_PREFIX = "hmac-sha256:"
REPLACEMENT_IDEMPOTENCY_PREFIX = "neos-coding-sbx:v1:"
_ID_HEX = 32

# 할당 층 metadata. `neos/coding/managed/adapters/e2b.py` 의 키와 **같은 문자열**이다
# -- 할당 평면의 재발견·정리가 이 키를 읽는다.
METADATA_ALLOCATION_ID = "neos_allocation_id"
METADATA_IDEMPOTENCY_KEY = "neos_idempotency_key"
METADATA_OWNERSHIP_DIGEST = "neos_ownership_digest"
# 물리 층 metadata. 재발견 인덱스일 뿐 ACL 이 아니다 -- 검증은 host 가 HMAC 으로 한다.
METADATA_SANDBOX_ID = "neos_sandbox_id"
METADATA_INCARNATION = "neos_incarnation"
METADATA_CODING_OWNERSHIP = "neos_coding_ownership"


def decode_ownership_key(secret: str) -> bytes:
    """`secrets.managed_coding_ownership_key` (base64, 정확히 32바이트)."""
    try:
        key = base64.b64decode(secret, validate=True)
    except (binascii.Error, ValueError) as error:
        raise ValueError("managed_coding_ownership_key_invalid_encoding") from error
    if len(key) != OWNERSHIP_KEY_BYTES:
        raise ValueError("managed_coding_ownership_key_must_be_32_bytes")
    return key


@dataclass(frozen=True, slots=True)
class PhysicalIdentity:
    """물리 digest 가 묶는 사실 전부. 하나라도 바뀌면 digest 가 달라진다."""

    tenant_id: str
    task_id: str
    allocation_id: str
    allocation_generation: int
    sandbox_id: str
    incarnation: int
    profile: str
    image_digest: str
    region: str
    expires_at: datetime

    def __post_init__(self) -> None:
        if self.allocation_generation < 1 or self.incarnation < 1:
            raise ValueError("allocation generation and incarnation must be positive")
        if self.expires_at.tzinfo is None or self.expires_at.utcoffset() is None:
            raise ValueError("expires_at must be timezone-aware")

    def canonical(self) -> bytes:
        return json.dumps(
            {
                "allocation_generation": self.allocation_generation,
                "allocation_id": self.allocation_id,
                "expires_at": self.expires_at.astimezone(UTC).isoformat(),
                "image_digest": self.image_digest,
                "incarnation": self.incarnation,
                "profile": self.profile,
                "region": self.region,
                "sandbox_id": self.sandbox_id,
                "task_id": self.task_id,
                "tenant_id": self.tenant_id,
                "v": 1,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")


def _encode(parts: tuple[str, ...]) -> bytes:
    # 길이 접두 인코딩: ("a:b", "c") 와 ("a", "b:c") 가 같은 MAC 이 되면 안 된다.
    return b"".join(
        f"{len(encoded)}:".encode("ascii") + encoded
        for encoded in (part.encode("utf-8") for part in parts)
    )


class ManagedCodingIdentity:
    __slots__ = ("_key",)

    def __init__(self, key: bytes) -> None:
        if len(key) != OWNERSHIP_KEY_BYTES:
            raise ValueError("managed_coding_ownership_key_must_be_32_bytes")
        self._key = key

    def _mac(self, *parts: str) -> str:
        return hmac.new(self._key, _encode(parts), hashlib.sha256).hexdigest()

    def sandbox_id(self, *, allocation_id: str) -> str:
        """논리 샌드박스 id. allocation 하나에 정확히 하나다."""
        return "sbx_" + self._mac("sandbox", allocation_id)[:_ID_HEX]

    @staticmethod
    def replacement_idempotency_key(*, sandbox_id: str, incarnation: int) -> str:
        """incarnation >= 2 (교체 object) 의 재발견 키.

        incarnation 1 은 할당 평면의 admission idempotency key 를 쓴다.
        """
        if incarnation < 2:
            raise ValueError("replacement incarnations start at 2")
        return f"{REPLACEMENT_IDEMPOTENCY_PREFIX}{sandbox_id}:{incarnation}"

    @staticmethod
    def provider_name(*, sandbox_id: str, incarnation: int) -> str:
        """Deterministic vendor name/tag. Used as an idempotency aid only."""
        return f"neos-{sandbox_id.replace('_', '-')}-i{incarnation}"

    def physical_digest(self, identity: PhysicalIdentity) -> str:
        return DIGEST_PREFIX + hmac.new(
            self._key, identity.canonical(), hashlib.sha256
        ).hexdigest()

    def verify_physical(self, digest: str | None, identity: PhysicalIdentity) -> bool:
        if not digest:
            return False
        return hmac.compare_digest(digest, self.physical_digest(identity))

    def ref_index(self, *, provider: str, provider_ref: str) -> str:
        """provider ref 의 키 있는 색인. 원장이 평문 ref 없이 ref 로 행을 찾는다."""
        return "ref_" + self._mac("ref", provider, provider_ref)[:40]

    def snapshot_id(
        self, *, sandbox_id: str, incarnation: int, provider_snapshot_ref: str
    ) -> str:
        return "snp_" + self._mac(
            "snapshot", sandbox_id, str(incarnation), provider_snapshot_ref
        )[:_ID_HEX]

    def metadata(
        self,
        identity: PhysicalIdentity,
        *,
        idempotency_key: str,
        legacy_ownership_digest: str,
    ) -> dict[str, str]:
        return {
            METADATA_ALLOCATION_ID: identity.allocation_id,
            METADATA_IDEMPOTENCY_KEY: idempotency_key,
            METADATA_OWNERSHIP_DIGEST: legacy_ownership_digest,
            METADATA_SANDBOX_ID: identity.sandbox_id,
            METADATA_INCARNATION: str(identity.incarnation),
            METADATA_CODING_OWNERSHIP: self.physical_digest(identity),
        }

    def __repr__(self) -> str:  # 키를 repr 에 노출하지 않는다.
        return "ManagedCodingIdentity(<key>)"
