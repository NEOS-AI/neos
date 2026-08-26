"""배포 스키마가 **신선한 DB 에서 재현되는지** 검증한다 (SCHEMA1).

`db/README.md` 가 psql 명령을 나열하고 사람이 실행하는 방식인 한, 어떤 파일이
어떤 순서로 들어가는지는 산문에만 있다. 2026-08-25 실측이 그 대가를 보여줬다 --
README 순서로 55개를 적용하면 4개가 실패하고, 046 은 목록에서 아예 빠져 있었다.

이 스크립트는 두 층으로 검사한다.

**목록 완전성** (Docker 불필요, `--check-list-only`)
    `db/**/*.sql` 중 `db/BOOTSTRAP_ORDER.txt` 에 없는 파일이 있으면 실패한다.
    순서는 번호순이 아니라서 자동 유도가 불가능하다 -- 목록을 손으로 드는
    비용은 치르되, **누락은 기계가 잡는다.** 새 마이그레이션을 더하고 목록에
    적지 않으면 여기서 걸린다.

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


def bootstrap_order(order_file: pathlib.Path = _ORDER_FILE) -> list[str]:
    """정본 순서를 읽는다. 빈 줄과 주석은 버린다."""
    lines = order_file.read_text(encoding="utf-8").splitlines()
    return [
        stripped
        for line in lines
        if (stripped := line.strip()) and not stripped.startswith("#")
    ]


def discovered_sql_files(repo: pathlib.Path = _REPO) -> list[str]:
    """저장소가 실제로 들고 있는 스키마 SQL 전량 (경로는 루트 기준)."""
    found = sorted(repo.glob("db/*.sql")) + sorted(repo.glob("db/migrations/*.sql"))
    return [str(path.relative_to(repo)) for path in found]


def check_list(repo: pathlib.Path = _REPO) -> list[str]:
    """목록과 실물의 차이를 사람이 읽을 문장으로 낸다. 빈 리스트면 통과."""
    ordered = bootstrap_order()
    problems: list[str] = []

    duplicates = sorted({p for p in ordered if ordered.count(p) > 1})
    for path in duplicates:
        problems.append(f"정본 순서에 중복으로 실려 있다: {path}")

    on_disk = set(discovered_sql_files(repo))
    listed = set(ordered)

    for path in sorted(on_disk - listed):
        problems.append(
            f"저장소에 있으나 정본 순서에 없다: {path} "
            "(db/BOOTSTRAP_ORDER.txt 에 적을 것 -- 적지 않으면 배포에서 빠진다)"
        )
    for path in sorted(listed - on_disk):
        problems.append(f"정본 순서가 없는 파일을 가리킨다: {path}")

    return problems


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


def verify_against_fresh_database(image: str, keep: bool) -> list[Failure]:
    """일회용 컨테이너를 띄워 빈 DB 에 정본 순서를 전량 적용한다."""
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
        return apply_all(container, database, bootstrap_order())
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
        help="목록 완전성만 검사한다 (Docker 불필요)",
    )
    parser.add_argument("--image", default=_DEFAULT_IMAGE, help="사용할 postgres 이미지")
    parser.add_argument("--keep", action="store_true", help="검증 컨테이너를 남긴다")
    args = parser.parse_args()

    problems = check_list()
    if problems:
        print("정본 순서와 저장소가 어긋난다:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    order = bootstrap_order()
    print(f"목록 완전성 통과 -- {len(order)}개 파일")

    if args.check_list_only:
        return 0

    failures = verify_against_fresh_database(args.image, args.keep)
    if failures:
        print(f"\n신선한 DB 에서 {len(failures)}개가 실패한다:")
        for failure in failures:
            print(f"  - {failure.path}")
            print(f"      {failure.message}")
        print(
            "\n파일 하나가 죽으면 그 파일의 **나머지 구문이 통째로 미적용**이다. "
            "실패 건수가 아니라 잃은 객체를 세야 한다."
        )
        return 1

    print(f"신선한 DB 적용 통과 -- {len(order)}개 전부 성공")
    return 0


if __name__ == "__main__":
    sys.exit(main())
