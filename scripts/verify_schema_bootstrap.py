"""배포 스키마가 **신선한 DB 에서 재현되는지** 검증한다 (SCHEMA1).

`db/README.md` 가 psql 명령을 나열하고 사람이 실행하는 방식인 한, 어떤 파일이
어떤 순서로 들어가는지는 산문에만 있다. 2026-08-25 실측이 그 대가를 보여줬다 --
README 순서로 55개를 적용하면 4개가 실패하고, 046 은 목록에서 아예 빠져 있었다.

이 스크립트는 두 층으로 검사한다.

**선언·이름·가드 검사** (Docker 불필요, `--check-list-only`)
    순서는 이제 `db/BOOTSTRAP_ORDER.txt` 의 규칙에서 **유도한다** -- 기반 스키마는
    `[base]` 에 명시하고(번호가 없어 유도 불가), 마이그레이션은 번호순 자동이며
    `[hoist]` 규칙만 그것을 덮는다. 2026-09-20 이전에는 69줄을 손으로 들었다.

    자동 유도의 대가를 세 가지 검사로 치른다. (1) `db/*.sql` 이 `[base]` 와
    양방향으로 맞는가. (2) `db/migrations/*.sql` 이 `NNN_이름.sql` 인가 --
    아무 파일이나 딸려 들어가지 않게 하는 울타리다. (3) **가드 자리가 맞는가** --
    아래 `guard_violations()`. 세 번째가 핵심이다: 손으로 들 때는 "어디에 넣을까" 가
    사람의 판단이었고 그 판단이 실제로 060 을 구했다. 자동 유도로 바꾼 이상
    기계가 대신 해야 한다.

**적용 검증** (Docker 필요)
    일회용 컨테이너의 빈 DB 에 정본 순서대로 전부 적용하고 실패 0 건을
    단언한다. 파일 하나가 `ON_ERROR_STOP` 으로 죽으면 **그 파일의 나머지가
    통째로 미적용**이라는 것이 이 검사의 핵심이다 -- `chat_similarity_search.sql`
    은 90 줄에서 죽어 함수 6개·뷰 2개·인덱스 10개를 잃고 있었다.

사용:
    python scripts/verify_schema_bootstrap.py
    python scripts/verify_schema_bootstrap.py --check-list-only
    python scripts/verify_schema_bootstrap.py --keep    # 컨테이너를 남긴다
"""

from __future__ import annotations

import argparse
import pathlib
import re
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass

_REPO = pathlib.Path(__file__).resolve().parents[1]
_ORDER_FILE = _REPO / "db" / "BOOTSTRAP_ORDER.txt"
_DEFAULT_IMAGE = "neos-paradedb:latest"

# 초기화 완료를 알리는 공식 postgres 엔트리포인트의 로그 문구.
# `pg_isready` 만으로는 부족하다 -- 엔트리포인트는 initdb 스크립트를 처리하려고
# 임시 서버를 띄웠다가 fast shutdown 후 진짜 서버를 재시작하고, 그 임시 서버도
# `pg_isready` 에 초록을 준다. 이 문구를 먼저 기다리지 않으면 적용 도중
# "the database system is shutting down" 이 쏟아진다 (2026-08-25 에 실제로 겪었다).
_INIT_DONE = "PostgreSQL init process complete"


@dataclass(frozen=True)
class Failure:
    """정본 순서 중 한 파일의 적용 실패."""

    path: str
    returncode: int
    message: str


_MIGRATION_NAME = re.compile(r"^(\d{3})_[A-Za-z0-9_]+\.sql$")

# `information_schema.tables` 로 "이 테이블이 이미 있어야 한다" 를 묻는 가드. 줄바꿈이
# 섞이므로 주석을 지우고 공백을 정규화한 뒤 같은 문장(세미콜론 전) 안에서만 찾는다.
_GUARD = re.compile(
    r"(?P<polarity>IF\s+(?:NOT\s+)?EXISTS|AND\s+(?:NOT\s+)?EXISTS)?\s*\(?\s*SELECT[^;]{0,120}?"
    r"information_schema\.tables\b[^;]{0,200}?table_name\s*=\s*'(?P<table>[A-Za-z_][A-Za-z0-9_]*)'",
    re.I,
)
_CREATE_TABLE = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[\"']?(?:public\.)?([A-Za-z_][A-Za-z0-9_]*)", re.I
)
_LINE_COMMENT = re.compile(r"--[^\n]*")
_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class Rules:
    """`BOOTSTRAP_ORDER.txt` 가 선언하는 것 전부."""

    base: list[str]
    hoists: list[tuple[str, str]]  # (앞당길 파일, 그 앞에 놓을 기준 파일) -- 파일명만


def parse_rules(order_file: pathlib.Path = _ORDER_FILE) -> Rules:
    """`[base]` 목록과 `[hoist]` 규칙을 읽는다. 빈 줄과 주석은 버린다."""
    base: list[str] = []
    hoists: list[tuple[str, str]] = []
    section = None
    for raw in order_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].lower()
            continue
        if section == "base":
            base.append(line)
        elif section == "hoist":
            parts = line.split()
            if len(parts) != 3 or parts[1].lower() != "before":
                raise ValueError(f"[hoist] 형식은 `<파일> before <파일>` 이다: {line!r}")
            hoists.append((parts[0], parts[2]))
        else:
            raise ValueError(f"[base]/[hoist] 밖에 내용이 있다: {line!r}")
    return Rules(base=base, hoists=hoists)


def discovered_migrations(repo: pathlib.Path = _REPO) -> list[str]:
    """`db/migrations/*.sql` 을 번호순으로. 이름 규칙 위반은 여기서 거른다."""
    found = []
    for path in sorted((repo / "db" / "migrations").glob("*.sql")):
        match = _MIGRATION_NAME.match(path.name)
        if match:
            found.append((int(match.group(1)), f"db/migrations/{path.name}"))
    return [relative for _, relative in sorted(found)]


def bootstrap_order(order_file: pathlib.Path = _ORDER_FILE, repo: pathlib.Path = _REPO) -> list[str]:
    """정본 순서를 **유도한다**: 기반 스키마 + (번호순 마이그레이션에 hoist 적용).

    예전에는 이 함수가 69줄을 그대로 읽었다. 이제 마이그레이션은 번호순으로 자동
    유도되고 `[hoist]` 규칙만 그것을 덮는다 -- 새 마이그레이션이 파일을 건드리지
    않고 들어온다. 자리를 잘못 잡는 위험은 `guard_violations()` 가 대신 잡는다.
    """
    rules = parse_rules(order_file)
    migrations = discovered_migrations(repo)

    hoisted = {name for name, _ in rules.hoists}
    remaining = [p for p in migrations if pathlib.Path(p).name not in hoisted]

    # 기준 파일 앞에 규칙 선언 순서대로 끼워 넣는다.
    for name, anchor in rules.hoists:
        relative = f"db/migrations/{name}"
        anchor_relative = f"db/migrations/{anchor}"
        if anchor_relative not in remaining:
            raise ValueError(f"[hoist] 기준 파일을 순서에서 찾지 못했다: {anchor}")
        remaining.insert(remaining.index(anchor_relative), relative)

    return list(rules.base) + remaining


def discovered_sql_files(repo: pathlib.Path = _REPO) -> list[str]:
    """저장소가 실제로 들고 있는 스키마 SQL 전량 (경로는 루트 기준)."""
    found = sorted(repo.glob("db/*.sql")) + sorted(repo.glob("db/migrations/*.sql"))
    return [str(path.relative_to(repo)) for path in found]


def _normalized(path: pathlib.Path) -> str:
    return _WHITESPACE.sub(" ", _LINE_COMMENT.sub("", path.read_text(encoding="utf-8")))


def guard_violations(order: list[str], repo: pathlib.Path = _REPO) -> list[str]:
    """선행 테이블을 요구하는 가드보다 그 테이블을 만드는 파일이 **뒤에** 있는 경우.

    이것이 자동 유도의 안전망이다. `IF EXISTS (SELECT 1 FROM information_schema.tables
    WHERE table_name = 'X')` 로 감싼 블록은 X 가 없으면 **에러 없이 통째로 건너뛴다**.
    그래서 적용은 초록인데 컬럼·인덱스·트리거가 조용히 빠진다 -- 2026-09-20 에 060 이
    정확히 그랬다(1회 적용과 2회 적용의 스키마가 달랐다). 사람이 목록을 손으로 들 때는
    "어디에 넣을까" 가 그 판단이었고, 자동 유도로 바꾼 이상 여기서 대신 잡아야 한다.

    `NOT EXISTS` 는 "없으면 만든다" 이므로 선행 요구가 아니다 -- 건너뛴다.
    """
    positions = {relative: index for index, relative in enumerate(order)}
    creator: dict[str, str] = {}
    guards: list[tuple[str, str]] = []

    for relative in order:
        text = _normalized(repo / relative)
        for match in _CREATE_TABLE.finditer(text):
            creator.setdefault(match.group(1), relative)
        for match in _GUARD.finditer(text):
            if "NOT" in (match.group("polarity") or "").upper():
                continue
            guards.append((relative, match.group("table")))

    problems: list[str] = []
    for relative, table in guards:
        source = creator.get(table)
        if source is None or positions[source] <= positions[relative]:
            continue
        problems.append(
            f"{relative} 가 `{table}` 이 이미 있기를 요구하는데, 그것을 만드는 "
            f"{source} 가 뒤에 있다 (db/BOOTSTRAP_ORDER.txt 의 [hoist] 에 "
            f"`{pathlib.Path(source).name} before {pathlib.Path(relative).name}` 를 더할 것 -- "
            "지금 상태로는 그 가드 블록이 에러 없이 통째로 건너뛰어진다)"
        )
    return problems


def check_list(repo: pathlib.Path = _REPO) -> list[str]:
    """선언과 실물의 차이를 사람이 읽을 문장으로 낸다. 빈 리스트면 통과."""
    problems: list[str] = []
    try:
        rules = parse_rules()
    except ValueError as error:
        return [str(error)]

    # `[base]` 는 양방향으로 맞아야 한다 -- 번호가 없어 유도할 수 없기 때문이다.
    base_on_disk = {str(p.relative_to(repo)) for p in repo.glob("db/*.sql")}
    base_listed = set(rules.base)
    for path in sorted({p for p in rules.base if rules.base.count(p) > 1}):
        problems.append(f"[base] 에 중복으로 실려 있다: {path}")
    for path in sorted(base_on_disk - base_listed):
        problems.append(
            f"저장소에 있으나 [base] 에 없다: {path} "
            "(db/BOOTSTRAP_ORDER.txt 의 [base] 에 적을 것 -- 적지 않으면 배포에서 빠진다)"
        )
    for path in sorted(base_listed - base_on_disk):
        problems.append(f"[base] 가 없는 파일을 가리킨다: {path}")

    # 마이그레이션은 자동 포함이므로, 그 대가로 이름 규칙을 강제한다.
    numbers: dict[str, list[str]] = {}
    for path in sorted((repo / "db" / "migrations").glob("*.sql")):
        match = _MIGRATION_NAME.match(path.name)
        if not match:
            problems.append(
                f"마이그레이션 이름 규칙 위반: db/migrations/{path.name} "
                "(`NNN_이름.sql` 이어야 자동 포함된다)"
            )
            continue
        numbers.setdefault(match.group(1), []).append(path.name)
    for number, names in sorted(numbers.items()):
        if len(names) > 1:
            problems.append(f"마이그레이션 번호 {number} 가 중복이다: {', '.join(sorted(names))}")

    # hoist 규칙이 가리키는 파일이 실재하는가.
    migration_names = {pathlib.Path(p).name for p in discovered_migrations(repo)}
    for name, anchor in rules.hoists:
        for which, value in (("앞당길 파일", name), ("기준 파일", anchor)):
            if value not in migration_names:
                problems.append(f"[hoist] 의 {which}을 찾지 못했다: {value}")

    if problems:
        return problems

    # 자리까지 맞는가 -- 자동 유도의 안전망.
    return guard_violations(bootstrap_order(repo=repo), repo)


def _run(argv: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, capture_output=True, text=True, **kwargs)


def _wait_until_ready(container: str, timeout_s: int = 180) -> None:
    """초기화 완료 로그를 본 **뒤** 연결 가능해질 때까지 기다린다."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        logs = _run(["docker", "logs", container])
        if _INIT_DONE in (logs.stdout + logs.stderr):
            break
        time.sleep(1)
    else:
        raise RuntimeError(f"{timeout_s}초 안에 초기화 완료 로그를 못 봤다")

    while time.monotonic() < deadline:
        if _run(["docker", "exec", container, "pg_isready", "-U", "postgres"]).returncode == 0:
            return
        time.sleep(1)
    raise RuntimeError("초기화는 끝났는데 연결이 열리지 않는다")


def apply_all(container: str, database: str, order: list[str]) -> list[Failure]:
    """정본 순서대로 적용하고 실패만 모아 돌려준다.

    실패해도 멈추지 않는다 -- 첫 실패에서 멈추면 그 뒤에 몇 개가 더 깨지는지
    알 수 없고, 한 번에 하나씩 고치느라 실행을 반복하게 된다.
    """
    failures: list[Failure] = []
    for relative in order:
        result = _run(
            [
                "docker", "exec", container,
                "psql", "-U", "postgres", "-d", database,
                "-v", "ON_ERROR_STOP=1", "-q", "-f", f"/{relative}",
            ]
        )
        if result.returncode != 0:
            message = next(
                (
                    line.strip()
                    for line in result.stderr.splitlines()
                    if "ERROR" in line or "FATAL" in line
                ),
                result.stderr.strip().splitlines()[0] if result.stderr.strip() else "",
            )
            failures.append(Failure(relative, result.returncode, message))
    return failures


def verify_against_fresh_database(
    image: str, keep: bool, *, check_reapply: bool = True
) -> tuple[list[Failure], list[Failure]]:
    """일회용 컨테이너를 띄워 정본 순서를 적용한다. `(1회차 실패, 2회차 실패)`.

    두 번 적용하는 이유: 신선한 DB 재현(SCHEMA1)과 **재적용 멱등성**(SCHEMA3)은
    다른 성질이고 둘 다 실제로 쓰인다. `tests/conftest.py` 는 세션마다 전량을
    다시 적용하므로 후자가 오히려 일상 경로다.

    멱등하지 않을 때의 대가는 추상적이지 않다 -- 2026-08-27 에 개발 DB 에
    **append-only 트리거가 아예 없는 것**이 발견됐다. 036 이 중간에서 죽어
    `CREATE TRIGGER` 에 도달하지 못했고, "재적용은 원래 몇 개 실패한다" 는
    상태가 그것을 가리고 있었다.

    1회차가 실패하면 2회차는 돌리지 않는다 -- 무엇이 원인인지 섞인다.
    """
    container = f"neos-schema-verify-{uuid.uuid4().hex[:8]}"
    database = "neos_verify"

    started = _run(
        [
            "docker", "run", "--name", container,
            "-e", "POSTGRES_PASSWORD=password",
            "-v", f"{_REPO}/db:/db:ro",
            "-d", image,
        ]
    )
    if started.returncode != 0:
        raise RuntimeError(f"컨테이너 기동 실패: {started.stderr.strip()}")

    try:
        _wait_until_ready(container)
        created = _run(
            ["docker", "exec", container, "psql", "-U", "postgres", "-c", f"CREATE DATABASE {database};"]
        )
        if created.returncode != 0:
            raise RuntimeError(f"DB 생성 실패: {created.stderr.strip()}")
        order = bootstrap_order()
        first = apply_all(container, database, order)
        if first or not check_reapply:
            return first, []
        # 두 번째 적용 -- 이미 적용된 DB 에 다시 돌려도 실패가 없어야 한다.
        # `tests/conftest.py` 가 세션마다 전량 적용하므로 이것이 일상 경로다.
        return first, apply_all(container, database, order)
    finally:
        if keep:
            print(f"\n컨테이너를 남긴다: {container} (docker rm -f {container} 로 정리)")
        else:
            _run(["docker", "rm", "-f", container])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check-list-only",
        action="store_true",
        help="선언·이름·가드 검사만 한다 (Docker 불필요)",
    )
    parser.add_argument("--image", default=_DEFAULT_IMAGE, help="사용할 postgres 이미지")
    parser.add_argument("--keep", action="store_true", help="검증 컨테이너를 남긴다")
    parser.add_argument(
        "--skip-reapply",
        action="store_true",
        help="재적용 멱등성 검사를 건너뛴다 (1회차만 본다)",
    )
    args = parser.parse_args()

    problems = check_list()
    if problems:
        print("정본 순서 선언과 저장소가 어긋난다:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    order = bootstrap_order()
    print(f"선언·이름·가드 검사 통과 -- 적용 대상 {len(order)}개 파일")

    if args.check_list_only:
        return 0

    first, second = verify_against_fresh_database(
        args.image, args.keep, check_reapply=not args.skip_reapply
    )
    if first:
        print(f"\n신선한 DB 에서 {len(first)}개가 실패한다:")
        for failure in first:
            print(f"  - {failure.path}")
            print(f"      {failure.message}")
        print(
            "\n파일 하나가 죽으면 그 파일의 **나머지 구문이 통째로 미적용**이다. "
            "실패 건수가 아니라 잃은 객체를 세야 한다."
        )
        return 1
    if second:
        print(f"\n신선한 DB 적용 통과 -- {len(order)}개 전부 성공")
        print(f"그러나 **재적용에서 {len(second)}개가 실패한다** (SCHEMA3):")
        for failure in second:
            print(f"  - {failure.path}")
            print(f"      {failure.message}")
        print(
            "\n`tests/conftest.py` 가 세션마다 전량을 다시 적용하므로 이것이 일상 "
            "경로다. 멱등하지 않으면 그 파일의 나머지가 미적용으로 남고, "
            "'재적용은 원래 몇 개 실패한다' 는 상태가 진짜 실패를 가린다."
        )
        return 1

    print(f"신선한 DB 적용 통과 -- {len(order)}개 전부 성공")
    return 0


if __name__ == "__main__":
    sys.exit(main())
