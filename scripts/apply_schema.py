"""정본 순서대로 **실재하는 DB** 에 스키마를 적용한다 (SCHEMA1 의 배포 측 짝).

`verify_schema_bootstrap.py` 는 일회용 컨테이너에 적용해 **재현되는지**만 보고
컨테이너를 버린다. 배포·로컬에서 실제로 쓸 DB 를 채우는 경로는 여태 `db/README.md`
의 psql 명령을 사람이 68줄 복사해 붙이는 것이었다. 같은 순서를 두 곳에 두면
어긋나므로, 이 스크립트는 순서를 `BOOTSTRAP_ORDER.txt` 에서 읽고 파서는
`verify_schema_bootstrap.bootstrap_order()` 를 **그대로 쓴다** -- 사본을 만들지 않는다.

적용 전에 목록 완전성(`check_list`)을 먼저 본다. 목록에 없는 새 마이그레이션을
들고 배포하는 것이 SCHEMA1 이 막으려던 바로 그 사고다.

사용:
    python scripts/apply_schema.py                       # localhost:5432/neos
    python scripts/apply_schema.py --database neos_db --host db.internal
    python scripts/apply_schema.py --create-database     # 없으면 먼저 만든다
    python scripts/apply_schema.py --dry-run             # 적용할 파일만 출력
환경변수 `PGPASSWORD` 로 비밀번호를 준다 (psql 규약 그대로).
"""

from __future__ import annotations

import argparse
import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from verify_schema_bootstrap import bootstrap_order, check_list  # noqa: E402

_REPO = pathlib.Path(__file__).resolve().parents[1]


def _psql(args: argparse.Namespace, database: str, extra: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["psql", "-U", args.user, "-h", args.host, "-p", str(args.port), "-d", database, *extra],
        capture_output=True,
        text=True,
    )


def _ensure_database(args: argparse.Namespace) -> None:
    """없으면 만든다. 이미 있으면 아무것도 하지 않는다."""
    exists = _psql(
        args, args.maintenance_db,
        ["-Atc", f"SELECT 1 FROM pg_database WHERE datname='{args.database}'"],
    )
    if exists.returncode != 0:
        raise SystemExit(f"서버에 연결하지 못했다: {exists.stderr.strip()}")
    if exists.stdout.strip() == "1":
        print(f"데이터베이스 {args.database} 는 이미 있다")
        return
    created = _psql(args, args.maintenance_db, ["-c", f'CREATE DATABASE "{args.database}"'])
    if created.returncode != 0:
        raise SystemExit(f"데이터베이스 생성 실패: {created.stderr.strip()}")
    print(f"데이터베이스 {args.database} 를 만들었다")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=5432)
    parser.add_argument("--user", default="postgres")
    parser.add_argument("--database", default="neos")
    parser.add_argument("--maintenance-db", default="postgres", help="CREATE DATABASE 를 실행할 DB")
    parser.add_argument("--create-database", action="store_true", help="대상 DB 가 없으면 만든다")
    parser.add_argument("--dry-run", action="store_true", help="적용하지 않고 순서만 출력한다")
    args = parser.parse_args()

    problems = check_list()
    if problems:
        print("정본 순서와 저장소가 어긋난다 -- 적용하지 않는다:")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    order = bootstrap_order()
    print(f"목록 완전성 통과 -- {len(order)}개 파일")

    if args.dry_run:
        for relative in order:
            print(f"  {relative}")
        return 0

    if args.create_database:
        _ensure_database(args)

    # 첫 실패에서 멈춘다. `verify_schema_bootstrap.py` 가 전부 모아 보고하는 것과
    # 반대인데, 저쪽은 버릴 DB 를 진단하고 이쪽은 **쓸 DB 를 만들기** 때문이다.
    # 의존 파일이 빠진 채 뒤를 계속 밀어 넣으면 반쯤 채워진 DB 가 남는다.
    for index, relative in enumerate(order, start=1):
        path = _REPO / relative
        result = _psql(args, args.database, ["-v", "ON_ERROR_STOP=1", "-q", "-f", str(path)])
        if result.returncode != 0:
            print(f"\n[{index}/{len(order)}] {relative} 실패:")
            print(result.stderr.strip())
            print("\n이 파일의 **나머지 구문은 통째로 미적용**이다. 고친 뒤 다시 돌려라.")
            return 1
        print(f"[{index}/{len(order)}] {relative}")

    print(f"\n{len(order)}개 전부 적용했다 -- {args.user}@{args.host}:{args.port}/{args.database}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
