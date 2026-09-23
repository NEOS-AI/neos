"""테스트 DB 에 `db/init.sql` 이 요구하는 PostgreSQL 확장을 설치한다.

CI 의 세 잡이 각자 인라인으로 `CREATE EXTENSION IF NOT EXISTS vector` **하나만**
실행하고 있었다. `db/init.sql` 은 `vector` 와 `pg_trgm` 둘을 만들고, 채팅 스키마
(`db/chat_system.sql`)의 gin_trgm_ops 인덱스는 후자를 필요로 한다 -- 손으로 고른
부분집합은 항목이 늘어나는 순간 낡는다(같은 이유로 Ruff 의 파일 목록도
디렉터리로 바꿨다). 그래서 목록을 적지 않고 **파일에서 읽는다**.

스키마 자체(테이블)는 여기서 적용하지 않는다. `db/init.sql` 의 `users` 는 ORM
모델의 `users` 와 모양이 다르고 둘 다 `IF NOT EXISTS` 라, 먼저 실행한 쪽이
이긴다. 테스트가 쓰는 것은 ORM 쪽이므로 확장만 떼어 온다.
"""

import os
import pathlib
import re
import sys

_EXTENSION = re.compile(r"^\s*CREATE EXTENSION[^;]*;", re.IGNORECASE | re.MULTILINE)
_INIT_SQL = pathlib.Path(__file__).resolve().parents[1] / "db" / "init.sql"


def extension_statements(sql: str) -> list[str]:
    return [match.group(0).strip() for match in _EXTENSION.finditer(sql)]


def main() -> int:
    import psycopg2

    statements = extension_statements(_INIT_SQL.read_text(encoding="utf-8"))
    if not statements:
        print(f"확장 문장을 찾지 못했다: {_INIT_SQL}", file=sys.stderr)
        return 1

    connection = psycopg2.connect(
        host=os.environ.get("POSTGRES_HOST", "localhost"),
        dbname=os.environ.get("POSTGRES_DB", "neos_test"),
        user=os.environ.get("POSTGRES_USER", "neos"),
        password=os.environ.get("POSTGRES_PASSWORD", "neos_password"),
    )
    connection.autocommit = True
    try:
        with connection.cursor() as cursor:
            for statement in statements:
                print(statement)
                cursor.execute(statement)
    finally:
        connection.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
