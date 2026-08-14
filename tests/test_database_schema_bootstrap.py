"""테스트 DB 부트스트랩이 **테스트가 실제로 쓰는 스키마**를 만드는지 검사한다.

`db_manager.initialize()` 는 `Base.metadata.create_all` 로 ORM 모델만 만든다.
채팅 스키마(`conversations`·`messages`·`create_conversation` …)는 ORM 이 아니라
`db/chat_system.sql` 에 있고, 오랫동안 아무도 그것을 적용하지 않았다. 그래도
초록이 나왔던 이유는 두 가지다:

* conftest 의 정리 픽스처가 `except Exception: print(...)` 로 삼켰다 --
  `relation "conversations" does not exist` 가 매 테스트마다 조용히 지나갔다
* 개발 기계에는 누군가 손으로 적용해 둔 스키마가 있었다

즉 이 격차는 **CI 범위를 넓히기 전까지 관측될 수 없었다**(D64). 아래 검사들은
그 조건을 되돌린다 -- 부트스트랩이 다시 반쪽이 되면 삼켜지지 않고 여기서 터진다.
"""

import pathlib
import re

import pytest
from sqlalchemy import text

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
_CONFTEST = _REPO_ROOT / "tests" / "conftest.py"

# SQL 은 대문자 `FROM`, 파이썬 임포트는 소문자 `from` 이라 대소문자를 구분하면
# 정리 픽스처가 손대는 테이블만 걸린다(서브쿼리의 테이블까지 포함).
_SQL_TABLE = re.compile(r"\bFROM\s+([a-z_][a-z0-9_]*)")


def _tables_the_cleanup_fixture_touches() -> set[str]:
    return set(_SQL_TABLE.findall(_CONFTEST.read_text(encoding="utf-8")))


async def _missing_tables(session, names) -> list[str]:
    missing = []
    for name in sorted(names):
        found = await session.execute(
            text("SELECT to_regclass(:name)"), {"name": name}
        )
        if found.scalar() is None:
            missing.append(name)
    return missing


@pytest.mark.asyncio
async def test_every_table_the_cleanup_fixture_deletes_from_exists():
    """정리 픽스처의 예외 삼킴이 스키마 격차를 가리지 못하게 한다.

    이 목록은 손으로 유지하지 않고 conftest 소스에서 읽는다 -- 새 DELETE 를
    더하면서 그 테이블을 만들지 않으면 여기서 걸린다.
    """
    from neos.database.connection import get_session_ctx

    tables = _tables_the_cleanup_fixture_touches()
    assert "conversations" in tables, (
        "정리 픽스처의 SQL 을 못 읽었다 -- 정규식이 낡았을 수 있다"
    )

    async with get_session_ctx() as session:
        missing = await _missing_tables(session, tables)

    assert missing == [], (
        f"부트스트랩이 만들지 않은 테이블: {missing}. "
        "ORM 모델이 아니라면 db/*.sql 이 원본이고, 그것을 적용하는 것은 "
        "tests/conftest.py 의 `_apply_chat_system_schema` 다."
    )


@pytest.mark.asyncio
async def test_the_stored_function_the_chat_service_calls_exists():
    """`ChatService.create_conversation` 은 저장 함수를 호출한다.

    2026-08-13 CI 는 정확히 이것으로 죽었다:
    `function create_conversation(...) does not exist`.
    """
    from neos.database.connection import get_session_ctx

    async with get_session_ctx() as session:
        found = await session.execute(
            text("SELECT 1 FROM pg_proc WHERE proname = 'create_conversation'")
        )
        assert found.scalar() == 1, (
            "create_conversation 저장 함수가 없다 -- db/chat_system.sql 이 "
            "적용되지 않았다"
        )


@pytest.mark.asyncio
async def test_required_extensions_are_installed():
    """`db/init.sql` 이 요구하는 확장이 전부 있어야 한다.

    CI 는 한때 `vector` 하나만 켰다. `pg_trgm` 이 없으면 채팅 스키마의
    gin_trgm_ops 인덱스가 만들어지지 않는다.
    """
    from neos.database.connection import get_session_ctx

    from scripts.enable_db_extensions import extension_statements

    init_sql = (_REPO_ROOT / "db" / "init.sql").read_text(encoding="utf-8")
    required = {
        match.group(1)
        for statement in extension_statements(init_sql)
        if (match := re.search(r"EXISTS\s+([a-z_]+)", statement))
    }
    assert required, "db/init.sql 에서 확장 이름을 못 읽었다"

    async with get_session_ctx() as session:
        found = await session.execute(text("SELECT extname FROM pg_extension"))
        installed = {row[0] for row in found}

    assert required <= installed, f"설치되지 않은 확장: {sorted(required - installed)}"
