"""자격증명 브로커 -- 트랙 Q6 (docs/Q6_CREDENTIAL_BROKER_DESIGN_261001.md).

도구 인자에는 `secret://<name>` 참조만 싣고, **실행기**가 실행 직전에 풀어 쓴다.
풀린 값은 실행기의 지역 변수로만 산다 -- 전사·원장·이벤트·체크포인트에 들어가지
않는다. 결과는 돌려주기 전에 `ResolvedSecrets.scrub_*` 로 가린다.

뒤의 소비자(Q11 MCP · Q14 브라우저 · Q16 브리지)는 같은 세 걸음을 쓴다:
`secret_ref_name` 으로 찾고 → 금고에서 `resolve` → 결과를 `scrub`.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy import text

from neos.coding.redact import _redact_secret_values

_REF_PREFIX = "secret://"
#: 비밀 이름. 소문자로 시작 -- 참조가 URL 처럼 읽혀도 대소문자가 갈리지 않게.
SECRET_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
#: 묶을 환경변수 이름. `LD_*`·`DYLD_*` 는 로더가 해석하므로 막는다.
ENV_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_INTERPRETED_ENV_PREFIXES = ("LD_", "DYLD_")
#: 실행 환경이 정하는 이름 -- 비밀로 덮으면 명령이 엉뚱하게 돈다.
_RESERVED_ENV_NAMES = frozenset({"PATH", "HOME", "TMPDIR", "LANG", "LC_ALL", "TERM", "PWD", "SHELL"})
#: 이보다 짧은 값은 결과 가리기가 무해한 출력까지 지운다(S6).
MIN_SECRET_CHARS = 8
MAX_SECRET_CHARS = 8192
#: 잘린 출력의 끝에 걸친 접두는 이 길이부터 가린다(S6).
_TAIL_PREFIX_MIN = 4


class SecretNotFound(LookupError):
    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.name = name


class SecretLimit(Exception):
    """사용자당 비밀 수 상한(`coding_model.secret_broker_max`)에 닿았다."""


def secret_ref_name(value: object) -> str | None:
    """`secret://github` -> `github`. 값 전체가 참조일 때만 (S1)."""
    if not isinstance(value, str) or not value.startswith(_REF_PREFIX):
        return None
    name = value[len(_REF_PREFIX) :]
    return name if SECRET_NAME_RE.fullmatch(name) else None


def secret_env_refs(env: object) -> dict[str, str]:
    """`execute.v1` 의 `env` 에서 {변수 이름: 비밀 이름} (S2 -- 첫 소비자)."""
    if not isinstance(env, Mapping):
        return {}
    refs: dict[str, str] = {}
    for key, value in env.items():
        name = secret_ref_name(value)
        if name is not None:
            refs[str(key)] = name
    return refs


def carries_secret_refs(call: Any) -> bool:
    """이 호출이 금고의 비밀을 푸는가. 부모 게이트(S7)와 자식 거절(S8)이 **이 판정 하나**를 쓴다.

    커넥터(트랙 Q11a)는 참조가 입력이 아니라 서버 설정에 있다 -- 검증기가
    `ValidatedToolCall.secret_refs` 에 실어 온다.
    """
    if getattr(call, "secret_refs", ()):
        return True
    name = getattr(call, "name", None)
    data = getattr(call, "input", {})
    if name == "browser_fill_secret.v1":  # 트랙 Q14a
        return secret_ref_name(data.get("secret")) is not None
    if name != "execute.v1":
        return False
    return bool(secret_env_refs(data.get("env")))


def secret_env_name_allowed(name: str) -> bool:
    """비밀을 실을 수 있는 환경변수 이름인가 -- 검증기와 금고가 같이 쓴다."""
    return (
        bool(ENV_NAME_RE.fullmatch(name))
        and name not in _RESERVED_ENV_NAMES
        and not name.startswith(_INTERPRETED_ENV_PREFIXES)
    )


def parse_secret_fields(name: str, env_name: str, value: str) -> tuple[str, str, str]:
    if not SECRET_NAME_RE.fullmatch(name or ""):
        raise ValueError("name is lowercase letters, digits, '_' or '-' (1-64)")
    if not secret_env_name_allowed(env_name or ""):
        raise ValueError("env_name is an UPPER_CASE variable that is not reserved")
    if not isinstance(value, str) or not MIN_SECRET_CHARS <= len(value) <= MAX_SECRET_CHARS:
        raise ValueError(f"value is {MIN_SECRET_CHARS}-{MAX_SECRET_CHARS} characters")
    if "\0" in value:
        raise ValueError("value must not contain NUL")
    return name, env_name, value


@dataclass(frozen=True, slots=True)
class SecretInfo:
    """금고 목록의 한 줄. 값은 **없다** -- API 와 로그가 쥐어도 된다."""

    name: str
    env_name: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ResolvedSecret:
    env_name: str
    value: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class ResolvedSecrets:
    """한 호출 동안만 사는 풀린 값. `repr` 은 이름만 보인다."""

    values: Mapping[str, ResolvedSecret] = field(default_factory=dict, repr=False)

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self.values))

    def scrub_bytes(self, data: bytes, *, truncated: bool = False) -> bytes:
        """값 자체를 가린다(S6). 잘렸으면 끝에 걸친 접두도 가린다."""
        for name, secret in sorted(
            self.values.items(), key=lambda pair: -len(pair[1].value)
        ):
            raw = secret.value.encode("utf-8")
            marker = f"<redacted:secret://{name}>".encode()
            data = data.replace(raw, marker)
            if truncated:
                for size in range(min(len(raw) - 1, len(data)), _TAIL_PREFIX_MIN - 1, -1):
                    if data.endswith(raw[:size]):
                        data = data[:-size] + marker
                        break
        return data

    def scrub_text(self, text_value: str) -> str:
        scrubbed = self.scrub_bytes(text_value.encode("utf-8")).decode("utf-8", "replace")
        return _redact_secret_values(scrubbed)


SecretLookup = Callable[[Sequence[str]], Awaitable[ResolvedSecrets]]


class SecretStore(Protocol):
    async def list_for_user(self, user_id: str) -> list[SecretInfo]: ...

    async def put(self, user_id: str, name: str, *, env_name: str, value: str) -> SecretInfo: ...

    async def delete(self, user_id: str, name: str) -> bool: ...

    async def resolve(self, user_id: str, names: Iterable[str]) -> ResolvedSecrets: ...


class InMemorySecretStore:
    """테스트·개발용. 값은 평문으로 들고 있다 -- Postgres 와 **같은 계약**만 지킨다."""

    def __init__(self, *, max_secrets: int = 50) -> None:
        self._rows: dict[tuple[str, str], tuple[str, str, datetime, datetime]] = {}
        self._max = max_secrets

    async def list_for_user(self, user_id):
        mine = [
            SecretInfo(name, env_name, created, updated)
            for (owner, name), (env_name, _value, created, updated) in self._rows.items()
            if owner == user_id
        ]
        return sorted(mine, key=lambda info: info.name)

    async def put(self, user_id, name, *, env_name, value):
        name, env_name, value = parse_secret_fields(name, env_name, value)
        now = datetime.now(UTC)
        existing = self._rows.get((user_id, name))
        if existing is None and len(await self.list_for_user(user_id)) >= self._max:
            raise SecretLimit()
        created = existing[2] if existing else now
        self._rows[(user_id, name)] = (env_name, value, created, now)
        return SecretInfo(name, env_name, created, now)

    async def delete(self, user_id, name):
        return self._rows.pop((user_id, name), None) is not None

    async def resolve(self, user_id, names):
        values: dict[str, ResolvedSecret] = {}
        for name in names:
            row = self._rows.get((user_id, name))
            if row is None:
                raise SecretNotFound(name)
            values[name] = ResolvedSecret(row[0], row[1])
        return ResolvedSecrets(values)


_KEY_INFO = b"neos-secret-broker:v1"
_KEY_VERSION = 1
SECRET_BROKER_KEY_MIN_CHARS = 32


def derive_secret_key(master: str) -> bytes:
    """`NEOS_SECRET_BROKER_KEY` -> AES-256 키 (S5). Q4a 의 서명 비밀과 같은 파생 모양."""
    if len(master or "") < SECRET_BROKER_KEY_MIN_CHARS:
        raise ValueError("secret_broker_key_too_short")
    return hmac.new(master.encode("utf-8"), _KEY_INFO, hashlib.sha256).digest()


def _cipher(key: bytes, user_id: str, name: str):
    # 사본을 만들지 않는다 -- managed 의 봉인과 같은 형식(버전 · nonce · AEAD).
    from neos.coding.managed.crypto import AesGcmProviderReferenceCipher

    return AesGcmProviderReferenceCipher(
        key=key, key_version=_KEY_VERSION, associated_data=f"neos-secret:{user_id}:{name}"
    )


class PostgresSecretStore:
    def __init__(
        self,
        session_factory: Callable[[], Awaitable[Any]],
        *,
        key: bytes,
        max_secrets: int = 50,
    ) -> None:
        self._session_factory = session_factory
        self._key = key
        self._max = max_secrets

    def __repr__(self) -> str:  # 키를 보이지 않는다
        return "PostgresSecretStore()"

    async def list_for_user(self, user_id):
        async with await self._session_factory() as session:
            result = await session.execute(
                text(
                    "SELECT name, env_name, created_at, updated_at FROM user_secrets "
                    "WHERE user_id = :user_id ORDER BY name"
                ),
                {"user_id": user_id},
            )
            return [
                SecretInfo(row.name, row.env_name, row.created_at, row.updated_at)
                for row in result
            ]

    async def put(self, user_id, name, *, env_name, value):
        name, env_name, value = parse_secret_fields(name, env_name, value)
        sealed = _cipher(self._key, user_id, name).encrypt(value)
        now = datetime.now(UTC)
        async with await self._session_factory() as session:
            async with session.begin():
                # 상한 검사와 쓰기가 한 트랜잭션이다 -- 사용자 행을 잠근다(Q2 규칙 저장소와 같다).
                await session.execute(
                    text("SELECT 1 FROM users WHERE user_id = :user_id FOR UPDATE"),
                    {"user_id": user_id},
                )
                result = await session.execute(
                    text(
                        """
                        INSERT INTO user_secrets
                            (user_id, name, env_name, ciphertext, created_at, updated_at)
                        SELECT CAST(:user_id AS VARCHAR), CAST(:name AS VARCHAR),
                               CAST(:env_name AS VARCHAR), :ciphertext, :now, :now
                        WHERE EXISTS (SELECT 1 FROM user_secrets
                                      WHERE user_id = CAST(:user_id AS VARCHAR)
                                        AND name = CAST(:name AS VARCHAR))
                           OR (SELECT count(*) FROM user_secrets
                               WHERE user_id = CAST(:user_id AS VARCHAR)) < CAST(:max AS INTEGER)
                        ON CONFLICT (user_id, name) DO UPDATE
                            SET env_name = EXCLUDED.env_name,
                                ciphertext = EXCLUDED.ciphertext,
                                updated_at = EXCLUDED.updated_at
                        RETURNING created_at, updated_at
                        """
                    ),
                    {
                        "user_id": user_id,
                        "name": name,
                        "env_name": env_name,
                        "ciphertext": sealed,
                        "now": now,
                        "max": self._max,
                    },
                )
                row = result.first()
                if row is None:
                    raise SecretLimit()
        return SecretInfo(name, env_name, row.created_at, row.updated_at)

    async def delete(self, user_id, name):
        async with await self._session_factory() as session:
            async with session.begin():
                result = await session.execute(
                    text("DELETE FROM user_secrets WHERE user_id = :user_id AND name = :name"),
                    {"user_id": user_id, "name": name},
                )
        return bool(result.rowcount)

    async def resolve(self, user_id, names):
        wanted = sorted(set(names))
        if not wanted:
            return ResolvedSecrets({})
        async with await self._session_factory() as session:
            result = await session.execute(
                text(
                    "SELECT name, env_name, ciphertext FROM user_secrets "
                    "WHERE user_id = :user_id AND name = ANY(:names)"
                ),
                {"user_id": user_id, "names": wanted},
            )
            rows = {row.name: row for row in result}
        values: dict[str, ResolvedSecret] = {}
        for name in wanted:
            row = rows.get(name)
            if row is None:
                raise SecretNotFound(name)
            plain = _cipher(self._key, user_id, name).decrypt(bytes(row.ciphertext))
            values[name] = ResolvedSecret(row.env_name, plain)
        return ResolvedSecrets(values)


def build_secret_source(
    coding: Any, secrets: Any, session_factory: Callable[[], Awaitable[Any]]
) -> PostgresSecretStore | None:
    """`None` 이 off 다. 켜졌는지 판단하는 자리는 이 팩토리 하나다."""
    if not getattr(coding, "secret_broker", False):
        return None
    return PostgresSecretStore(
        session_factory,
        key=derive_secret_key(getattr(secrets, "secret_broker_key", None) or ""),
        max_secrets=coding.secret_broker_max,
    )


__all__ = [
    "InMemorySecretStore",
    "PostgresSecretStore",
    "ResolvedSecret",
    "ResolvedSecrets",
    "SecretInfo",
    "SecretLimit",
    "SecretLookup",
    "SecretNotFound",
    "SecretStore",
    "build_secret_source",
    "carries_secret_refs",
    "derive_secret_key",
    "parse_secret_fields",
    "secret_env_name_allowed",
    "secret_env_refs",
    "secret_ref_name",
]
