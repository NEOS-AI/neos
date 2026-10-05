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

.PHONY: help image-build image-push db-up db-down db-bootstrap db-reset db-check db-verify db-shell release dev-jev-shadow dev-jev-enforce jev-shadow-report

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

## ── 개발 서버 ─────────────────────────────────────────────────────────

# L2 -- Jev 도구 위험 섀도 (로드맵 §12.12). 판정은 바꾸지 않고 확률만 원장에 남긴다.
#
# 왜 `development.yaml` 이나 `config/neos.local.yaml` 이 아니라 여기인가:
# 앞의 것은 CI 가 `TYPESAFE_API_KEY` 를 요구하게 되고, 뒤의 것은 `.env` 의
# `NEOS_CONFIG_PATH` 를 통해 **테스트 실행에도 걸린다** -- 키가 채워진 기계에서
# 테스트가 진짜 Jev 를 부른다. 이 타깃은 개발 서버 **프로세스 하나에만** 오버레이를
# 건다. 켠 날짜를 적어 두고 `jev-shadow-report SINCE=<그날>` 로 읽는다.
JEV_SHADOW_CONFIG ?= config/samples/jev-l2-shadow.yaml
DEV_PORT          ?= 8518

dev-jev-shadow: ## 개발 서버를 L2 섀도 오버레이로 띄운다 (게이트는 꺼진 채)
	NEOS_CONFIG_PATH=$(JEV_SHADOW_CONFIG) uvicorn neos.main:app --reload --host 0.0.0.0 --port $(DEV_PORT)

JEV_ENFORCE_CONFIG ?= config/samples/dev-jev-enforce.yaml

dev-jev-enforce: ## 개발 서버를 Jev 집행 오버레이로 띄운다 (L3 게이트·Q5b 멈춤·L6 판정자, 잠정 경계)
	NEOS_CONFIG_PATH=$(JEV_ENFORCE_CONFIG) uvicorn neos.main:app --reload --host 0.0.0.0 --port $(DEV_PORT)

jev-shadow-report: ## 섀도 판독 (SINCE=YYYY-MM-DD 필수, TRY=0.2:0.9 후보 경계)
	@test -n "$(SINCE)" || { echo "SINCE=<섀도를 켠 날> 을 주어야 한다"; exit 2; }
	python -m scripts.jev_l2_shadow_report --since $(SINCE) --try $(or $(TRY),0.2:0.9)
