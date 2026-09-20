# DB

## Docker setup

```bash
make image-build    # docker build --network=host -t neos-paradedb -f docker/Dockerfile.psql .
make db-up          # 컨테이너 기동 후 pg_isready 까지 기다린다
```

> **`sudo docker build` 가 필요했던 이유**는 docker 가 아니라 한 디렉터리의
> 소유권이다. 과거에 한 번 `sudo docker build` 를 돌린 탓에
> `~/.docker/buildx/refs/orbstack/` 이 root 소유로 남았고, 그래서 그 뒤로는
> 일반 사용자 빌드가 `permission denied` 로 죽는다 -- sudo 로 도는 것이 다시
> root 소유 파일을 남기므로 스스로를 유지하는 고리다. 한 번 끊으면 된다:
>
> ```bash
> sudo chown -R "$USER" ~/.docker/buildx
> ```
>
> 이후로는 sudo 없이 빌드된다. `make release` 가 sudo 를 요구하지 않으려면
> 이 정리가 필요하다.

Running valkey:
```bash
docker pull valkey/valkey

docker run --name neos-valkey -p 6379:6379 -d valkey/valkey
```

Running rustfs:
```bash
# Using latest version
docker run --name neos-rustfs -d -p 9000:9000 -p 9001:9001 rustfs/rustfs:latest
```

Running jaeger for OpenTelemetry tracing:
```bash
docker run -d --name neos-jaeger -p 16686:16686 \
    -e LOG_LEVEL=info \
    -e COLLECTOR_OTLP_ENABLED=true \
    jaegertracing/all-in-one:latest
```

## Connecting to the database

```bash
psql postgres --host localhost --port 5432 --user postgres
```

## Publish the database image to docker hub

```bash
# 빌드 -> 스키마 검증 -> push 를 한 타깃으로 (검증에 실패하면 push 에 못 간다)
make release
```

`release` 는 `image-build` -> `db-verify` -> `image-push` 순서로 묶여 있다.
가운데 단계가 방금 빌드한 **그 이미지**로 빈 DB 를 만들어 선언된 것을 전부 적용하고,
한 번 더 적용해 멱등성까지 본다. 여태 빌드와 스키마 검증 사이에 아무 연결이
없었고, 그래서 스키마가 재현되지 않는 이미지도 그냥 push 됐다.

손으로 하려면:

```bash
# ParadeDB
docker tag neos-paradedb neos960518/neos-paradedb:latest
docker push neos960518/neos-paradedb:latest

# Valkey
docker tag valkey/valkey neos960518/neos-valkey:latest
docker push neos960518/neos-valkey:latest
```

## Migrate database schema

적용 순서의 **정본은 [`db/BOOTSTRAP_ORDER.txt`](BOOTSTRAP_ORDER.txt)** 다 (SCHEMA1).
여기 있던 psql 명령 138줄은 걷어냈다 -- 사람이 손으로 옮겨 적는 사본은 낡는다는
것이 증명됐기 때문이다. 그 목록은 `048` 에서 멈춰 있었고 `049`~`060` 이 빠져
있었으며, 그 이전에는 `046` 이 통째로 누락돼 배포하면
`coding_sandbox_provider_health` 가 없었다.

```bash
# 컨테이너 기동 + 스키마 전량 적용 (DB 가 없으면 만든다)
make db-up
make db-bootstrap

# 처음부터 다시
make db-reset
```

`make db-bootstrap` 은 `scripts/apply_schema.py` 를 부르고, 그 스크립트는 순서를
`BOOTSTRAP_ORDER.txt` 에서 **읽는다**. 순서가 적힌 곳은 한 군데뿐이다.

기본값은 `postgres@localhost:5432/neos` 이고 변수로 바꾼다:

```bash
make db-bootstrap PGDATABASE=neos_db PGHOST=db.internal PGUSER=neos_user
```

### 검증

```bash
make db-check    # 목록 완전성만 (Docker 불필요, CI 가 도는 것과 같은 검사)
make db-verify   # 일회용 컨테이너의 빈 DB 에 전량 적용 + 재적용 멱등성
```

### 새 마이그레이션을 더할 때

**보통은 `BOOTSTRAP_ORDER.txt` 를 건드리지 않는다.** `db/migrations/NNN_이름.sql` 로
만들면 번호순으로 자동 포함된다 (2026-09-20 부터. 그전에는 69줄을 손으로 들었다).

건드려야 하는 경우는 하나다 -- 새 테이블을 만드는데 **이미 그 테이블을 `IF EXISTS` 로
패치하는 기존 마이그레이션이 있을 때**. 그때는 `[hoist]` 에 한 줄을 더해 앞으로 당긴다.
직접 찾을 필요는 없다. `make db-check` 가 잡아서 더할 규칙까지 문장으로 알려준다:

```
db/migrations/061_x.sql 가 `widget_stats` 이 이미 있기를 요구하는데, 그것을 만드는
db/migrations/062_y.sql 가 뒤에 있다 ([hoist] 에 `062_y.sql before 061_x.sql` 를 더할 것
-- 지금 상태로는 그 가드 블록이 에러 없이 통째로 건너뛰어진다)
```

이 검사가 있는 이유는 `IF EXISTS` 가드가 **실패하지 않고 침묵하기 때문**이다. 대상
테이블이 없으면 블록 전체를 에러 없이 건너뛰므로 적용은 초록인데 컬럼·인덱스가 빠진다.
2026-09-20 에 `060` 이 정확히 그랬다 -- 1회 적용과 2회 적용의 스키마가 달랐다.

`db-check` 는 그 밖에 `db/*.sql` 이 `[base]` 와 양방향으로 맞는지, 마이그레이션 이름이
`NNN_이름.sql` 규칙을 지키는지(자동 포함의 울타리), 번호가 중복되지 않는지도 본다.
테스트는 이것들을 못 잡는다: `tests/conftest.py` 는 정본 순서가 아니라 ORM
`create_all()` + 번호순으로 따로 스키마를 세우므로, 선언이 어긋나도 초록이다.

`db-verify` 는 **재적용 멱등성**까지 본다. 같은 순서를 두 번 적용해도 실패가
없어야 하고, 1회 적용과 2회 적용의 스키마 모양이 같아야 한다. 2026-09-20 에
`060` 을 넣으며 실제로 걸린 사례가 있다 -- `007` 이 `knowledge_graphs` 를
`IF EXISTS` 로 감싸 패치하는데 그 테이블을 만드는 `060` 이 순서상 뒤라, 1회
적용에서는 컬럼이 안 붙고 2회부터 붙었다. 적용 횟수가 스키마를 바꾸면 안 된다.

## 테스트 DB 는 따로 쓰는 것이 좋다

`tests/conftest.py` 는 **ORM `create_all()` + 마이그레이션 번호순**으로, 배포는
**`BOOTSTRAP_ORDER.txt` 순서**로 같은 스키마를 세운다. 두 경로를 같은 데이터베이스에
겨누면 먼저 도착한 쪽이 이기고, 진 쪽은 `CREATE TABLE IF NOT EXISTS` 때문에
**에러 없이 조용히 no-op** 한다. 2026-09-20 에 실측했다: 배포용 부트스트랩을 도는
중에 pytest 가 같은 `neos` DB 에 ORM 테이블을 만들어, `document_chunks` 가 ORM
모양(`embedding_provider` 없음)으로 자리를 차지했고 `028` 이 그 뒤에서 죽었다.

```bash
make db-bootstrap PGDATABASE=neos_test   # 테스트용은 이름을 나눠라
```
