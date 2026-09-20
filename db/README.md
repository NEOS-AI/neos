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
가운데 단계가 방금 빌드한 **그 이미지**로 빈 DB 를 만들어 69개를 전부 적용하고,
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

`db-check` 는 `db/**/*.sql` 중 정본 목록에 없는 파일을 잡는다. **새 마이그레이션을
더하면 `BOOTSTRAP_ORDER.txt` 에도 반드시 한 줄 적어야 한다** -- 적지 않으면 CI 의
`Schema bootstrap list is complete` 에서 걸린다. 테스트는 이것을 못 잡는다:
`tests/conftest.py` 는 정본 순서가 아니라 ORM `create_all()` + 번호순으로 따로
스키마를 세우므로, 목록에서 빠진 파일이 있어도 초록이다.

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
