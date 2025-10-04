# DB

## Docker setup

```bash
cd ..

# 이미지 빌드
docker build -t neos-paradedb -f docker/Dockerfile.psql .

# 컨테이너 실행
docker run --name neos-paradedb -e POSTGRES_PASSWORD=password -p 5432:5432 -d neos-paradedb
```

Running valkey:
```bash
docker pull valkey/valkey

docker run --name neos-valkey -p 6379:6379 -d valkey/valkey
```

## Connecting to the database

```bash
psql postgres --host localhost --port 5432 --user postgres
```

## Publish the database image to docker hub

```bash
# ParadeDB
docker tag neos-paradedb neos960518/neos-paradedb:latest
docker push neos960518/neos-paradedb:latest
```
