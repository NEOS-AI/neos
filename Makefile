# NEOS 데이터베이스 · 이미지 릴리스 자동화
#
# 손으로 `docker build` 하고 `db/README.md` 의 psql 69줄을 붙여넣던 경로를 타깃으로
# 옮긴다. 핵심은 `release` 다 -- **스키마가 신선한 DB 에서 재현되지 않는 이미지는
# push 되지 않는다.** 여태 빌드와 스키마 검증 사이에 아무 연결이 없었다.

SHELL := /bin/bash

IMAGE       ?= neos-paradedb
TAG         ?= latest
REGISTRY    ?= neos960518
CONTAINER   ?= neos-paradedb

PGHOST      ?= localhost
PGPORT      ?= 5432
PGUSER      ?= postgres
PGDATABASE  ?= neos
export PGPASSWORD ?= password

.PHONY: help image-build image-push db-up db-down db-bootstrap db-reset db-check db-verify db-shell release

help:
	@grep -E '^[a-z][a-zA-Z0-9_-]*:.*?## ' $(MAKEFILE_LIST) | sed 's/:.*## /\t/' | expand -t22

## ── 이미지 ────────────────────────────────────────────────────────────

image-build: ## 이미지를 빌드한다
	docker build --network=host -t $(IMAGE):$(TAG) -f docker/Dockerfile.psql .

image-push: ## 빌드한 이미지에 태그를 달아 레지스트리로 민다
	docker tag $(IMAGE):$(TAG) $(REGISTRY)/$(IMAGE):$(TAG)
	docker push $(REGISTRY)/$(IMAGE):$(TAG)

## ── 로컬 DB ───────────────────────────────────────────────────────────

db-up: ## 컨테이너를 띄운다 (이미 있으면 start)
	docker start $(CONTAINER) 2>/dev/null || \
		docker run --name $(CONTAINER) -e POSTGRES_PASSWORD=$$PGPASSWORD \
			-p $(PGPORT):5432 -d $(IMAGE):$(TAG)
	@until docker exec $(CONTAINER) pg_isready -U postgres -q 2>/dev/null; do sleep 1; done
	@echo "$(CONTAINER) 준비됨"

db-down: ## 컨테이너를 멈춘다 (데이터는 남는다)
	docker stop $(CONTAINER)

db-bootstrap: ## 정본 순서대로 스키마를 적용한다 (없으면 DB 부터 만든다)
	python scripts/apply_schema.py --host $(PGHOST) --port $(PGPORT) \
		--user $(PGUSER) --database $(PGDATABASE) --create-database

db-reset: ## DB 를 지우고 처음부터 다시 올린다
	@echo "$(PGDATABASE) 를 DROP 한다. 5초 안에 Ctrl-C."; sleep 5
	psql -U $(PGUSER) -h $(PGHOST) -p $(PGPORT) -d postgres -q \
		-c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='$(PGDATABASE)';" \
		-c 'DROP DATABASE IF EXISTS "$(PGDATABASE)";'
	$(MAKE) db-bootstrap

db-shell: ## psql 을 연다
	psql -U $(PGUSER) -h $(PGHOST) -p $(PGPORT) -d $(PGDATABASE)

## ── 검증 ──────────────────────────────────────────────────────────────

db-check: ## 목록 완전성만 본다 (Docker 불필요, CI 와 같은 검사)
	python scripts/verify_schema_bootstrap.py --check-list-only

db-verify: ## 일회용 컨테이너의 빈 DB 에 전량 적용 + 재적용 멱등성까지 본다
	python scripts/verify_schema_bootstrap.py --image $(IMAGE):$(TAG)

## ── 릴리스 ────────────────────────────────────────────────────────────

# 빌드 → 검증 → push 를 한 타깃으로 묶는 이유는 순서를 강제하기 위해서다.
# `db-verify` 는 방금 빌드한 **그 이미지**로 신선한 DB 를 만들어 69개를 전부
# 적용하고, 한 번 더 적용해 멱등성까지 본다. 여기서 실패하면 push 에 도달하지
# 못한다 -- make 는 앞 타깃이 0 이 아니면 멈춘다.
release: image-build db-verify image-push ## 빌드 → 스키마 검증 → push (검증 실패 시 push 안 함)
	@echo "$(REGISTRY)/$(IMAGE):$(TAG) push 완료 -- 스키마 검증을 통과한 이미지다"
