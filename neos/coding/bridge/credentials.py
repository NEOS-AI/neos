"""브리지 페어링 자격증명 -- 트랙 Q16a (B1) · Q16b (BW2: `allow_writes`, 083).

토큰은 만들 때 **한 번만** 보이고, DB 에는 SHA-256 해시만 남는다. 256비트 난수라
솔트·느린 해시가 필요 없다 -- 코딩 소켓 티켓(`RedisCodingTicketStore`)이 키를 잡는
방법과 같다(새 암호를 만들지 않는다). 폐기는 행 삭제다. 키는 **사용자**다(B1, Q6 S4 와 같은 이유).
"""

from __future__ import annotations

import hashlib
import re
import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy import text

TOKEN_PREFIX = "ndb_"
_TOKEN_RE = re.compile(r"^ndb_[A-Za-z0-9_-]{43}$")
BRIDGE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]{0,63}$")


class BridgeLimit(Exception):
    """사용자당 브리지 상한(`device_bridge.max_bridges_per_user`)에 닿았다."""


class BridgeNameTaken(Exception):
    pass


@dataclass(frozen=True, slots=True)
class BridgeCredentialInfo:
    """목록의 한 줄. 토큰도 해시도 없다 -- API 와 로그가 쥐어도 된다."""

    bridge_id: str
    user_id: str
    name: str
    allow_unattended: bool
    created_at: datetime
    last_connected_at: datetime | None = None
    #: 쓰기 도구를 선언해도 되는가(Q16b, BW2). 기본 False -- 클라이언트의 `--allow-writes` 와 둘 다 있어야 한다.
    allow_writes: bool = False


def new_token() -> str:
    return TOKEN_PREFIX + secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def well_formed_token(token: object) -> bool:
    return isinstance(token, str) and bool(_TOKEN_RE.fullmatch(token))


def parse_bridge_name(name: object) -> str:
    value = name.strip() if isinstance(name, str) else ""
    if not BRIDGE_NAME_RE.fullmatch(value):
        raise ValueError("name is 1-64 letters, digits, space, '_', '.' or '-'")
    return value


class BridgeCredentialStore(Protocol):
    async def create(
        self, user_id: str, name: str, *, allow_unattended: bool = False, allow_writes: bool = False
    ) -> tuple[BridgeCredentialInfo, str]: ...

    async def list_for_user(self, user_id: str) -> list[BridgeCredentialInfo]: ...

    async def get(self, user_id: str, bridge_id: str) -> BridgeCredentialInfo | None: ...

    async def set_unattended(
        self, user_id: str, bridge_id: str, allow_unattended: bool
    ) -> BridgeCredentialInfo | None: ...

    async def set_writes(
        self, user_id: str, bridge_id: str, allow_writes: bool
    ) -> BridgeCredentialInfo | None: ...

    async def delete(self, user_id: str, bridge_id: str) -> bool: ...

    async def authenticate(self, token: str) -> BridgeCredentialInfo | None: ...


class InMemoryBridgeCredentialStore:
    """테스트용. Postgres 와 **같은 계약**만 지킨다."""

    def __init__(self, *, max_bridges: int = 5) -> None:
        self._rows: dict[str, tuple[BridgeCredentialInfo, str]] = {}
        self._max = max_bridges

    async def create(self, user_id, name, *, allow_unattended=False, allow_writes=False):
        name = parse_bridge_name(name)
        mine = await self.list_for_user(user_id)
        if any(info.name == name for info in mine):
            raise BridgeNameTaken()
        if len(mine) >= self._max:
            raise BridgeLimit()
        token = new_token()
        info = BridgeCredentialInfo(
            bridge_id="dbr_" + secrets.token_hex(12),
            user_id=user_id,
            name=name,
            allow_unattended=bool(allow_unattended),
            created_at=datetime.now(UTC),
            allow_writes=bool(allow_writes),
        )
        self._rows[info.bridge_id] = (info, token_hash(token))
        return info, token

    async def list_for_user(self, user_id):
        mine = [info for info, _hash in self._rows.values() if info.user_id == user_id]
        return sorted(mine, key=lambda info: (info.created_at, info.bridge_id))

    async def get(self, user_id, bridge_id):
        row = self._rows.get(bridge_id)
        return row[0] if row is not None and row[0].user_id == user_id else None

    async def set_unattended(self, user_id, bridge_id, allow_unattended):
        info = await self.get(user_id, bridge_id)
        if info is None:
            return None
        updated = replace(info, allow_unattended=bool(allow_unattended))
        self._rows[bridge_id] = (updated, self._rows[bridge_id][1])
        return updated

    async def set_writes(self, user_id, bridge_id, allow_writes):
        info = await self.get(user_id, bridge_id)
        if info is None:
            return None
        updated = replace(info, allow_writes=bool(allow_writes))
        self._rows[bridge_id] = (updated, self._rows[bridge_id][1])
        return updated

    async def delete(self, user_id, bridge_id):
        if await self.get(user_id, bridge_id) is None:
            return False
        del self._rows[bridge_id]
        return True

    async def authenticate(self, token):
        if not well_formed_token(token):
            return None
        wanted = token_hash(token)
        for bridge_id, (info, digest) in self._rows.items():
            if secrets.compare_digest(digest, wanted):
                touched = replace(info, last_connected_at=datetime.now(UTC))
                self._rows[bridge_id] = (touched, digest)
                return touched
        return None


def _info(row: Any) -> BridgeCredentialInfo:
    return BridgeCredentialInfo(
        bridge_id=row.bridge_id,
        user_id=row.user_id,
        name=row.name,
        allow_unattended=bool(row.allow_unattended),
        created_at=row.created_at,
        last_connected_at=row.last_connected_at,
        allow_writes=bool(row.allow_writes),
    )


_COLUMNS = (
    "bridge_id, user_id, name, allow_unattended, created_at, last_connected_at, allow_writes"
)


class PostgresBridgeCredentialStore:
    def __init__(
        self, session_factory: Callable[[], Awaitable[Any]], *, max_bridges: int = 5
    ) -> None:
        self._session_factory = session_factory
        self._max = max_bridges

    async def create(self, user_id, name, *, allow_unattended=False, allow_writes=False):
        name = parse_bridge_name(name)
        token = new_token()
        bridge_id = "dbr_" + secrets.token_hex(12)
        async with await self._session_factory() as session:
            async with session.begin():
                # 상한 검사와 쓰기가 한 트랜잭션이다 -- 사용자 행을 잠근다(Q6 금고와 같다).
                await session.execute(
                    text("SELECT 1 FROM users WHERE user_id = :user_id FOR UPDATE"),
                    {"user_id": user_id},
                )
                taken = await session.execute(
                    text(
                        "SELECT count(*) AS n, count(*) FILTER (WHERE name = :name) AS same "
                        "FROM device_bridges WHERE user_id = :user_id"
                    ),
                    {"user_id": user_id, "name": name},
                )
                counts = taken.one()
                if counts.same:
                    raise BridgeNameTaken()
                if counts.n >= self._max:
                    raise BridgeLimit()
                result = await session.execute(
                    text(
                        "INSERT INTO device_bridges "
                        "(bridge_id, user_id, name, token_hash, allow_unattended, allow_writes) "
                        "VALUES (:bridge_id, :user_id, :name, :token_hash, :allow_unattended, "
                        ":allow_writes) "
                        f"RETURNING {_COLUMNS}"
                    ),
                    {
                        "bridge_id": bridge_id,
                        "user_id": user_id,
                        "name": name,
                        "token_hash": token_hash(token),
                        "allow_unattended": bool(allow_unattended),
                        "allow_writes": bool(allow_writes),
                    },
                )
                info = _info(result.one())
        return info, token

    async def list_for_user(self, user_id):
        async with await self._session_factory() as session:
            result = await session.execute(
                text(
                    f"SELECT {_COLUMNS} FROM device_bridges WHERE user_id = :user_id "
                    "ORDER BY created_at, bridge_id"
                ),
                {"user_id": user_id},
            )
            return [_info(row) for row in result]

    async def get(self, user_id, bridge_id):
        async with await self._session_factory() as session:
            result = await session.execute(
                text(
                    f"SELECT {_COLUMNS} FROM device_bridges "
                    "WHERE user_id = :user_id AND bridge_id = :bridge_id"
                ),
                {"user_id": user_id, "bridge_id": bridge_id},
            )
            row = result.first()
        return _info(row) if row is not None else None

    async def set_unattended(self, user_id, bridge_id, allow_unattended):
        async with await self._session_factory() as session:
            async with session.begin():
                result = await session.execute(
                    text(
                        "UPDATE device_bridges SET allow_unattended = :value "
                        "WHERE user_id = :user_id AND bridge_id = :bridge_id "
                        f"RETURNING {_COLUMNS}"
                    ),
                    {"user_id": user_id, "bridge_id": bridge_id, "value": bool(allow_unattended)},
                )
                row = result.first()
        return _info(row) if row is not None else None

    async def set_writes(self, user_id, bridge_id, allow_writes):
        async with await self._session_factory() as session:
            async with session.begin():
                result = await session.execute(
                    text(
                        "UPDATE device_bridges SET allow_writes = :value "
                        "WHERE user_id = :user_id AND bridge_id = :bridge_id "
                        f"RETURNING {_COLUMNS}"
                    ),
                    {"user_id": user_id, "bridge_id": bridge_id, "value": bool(allow_writes)},
                )
                row = result.first()
        return _info(row) if row is not None else None

    async def delete(self, user_id, bridge_id):
        async with await self._session_factory() as session:
            async with session.begin():
                result = await session.execute(
                    text(
                        "DELETE FROM device_bridges "
                        "WHERE user_id = :user_id AND bridge_id = :bridge_id"
                    ),
                    {"user_id": user_id, "bridge_id": bridge_id},
                )
        return bool(result.rowcount)

    async def authenticate(self, token):
        if not well_formed_token(token):
            return None
        async with await self._session_factory() as session:
            async with session.begin():
                result = await session.execute(
                    text(
                        "UPDATE device_bridges SET last_connected_at = :now "
                        f"WHERE token_hash = :token_hash RETURNING {_COLUMNS}"
                    ),
                    {"token_hash": token_hash(token), "now": datetime.now(UTC)},
                )
                row = result.first()
        return _info(row) if row is not None else None


__all__ = [
    "BRIDGE_NAME_RE",
    "BridgeCredentialInfo",
    "BridgeCredentialStore",
    "BridgeLimit",
    "BridgeNameTaken",
    "InMemoryBridgeCredentialStore",
    "PostgresBridgeCredentialStore",
    "TOKEN_PREFIX",
    "new_token",
    "parse_bridge_name",
    "token_hash",
    "well_formed_token",
]
