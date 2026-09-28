# NEOS 백엔드 마이크로서비스화 검토 — 2026-09-27

**질문:** 백엔드 확장성을 위해 `neos/`를 마이크로서비스로 쪼갤 필요가 있는가?

**검증 원칙:** [`DIRECTION_260717.md`](DIRECTION_260717.md)와 같다. 사실 주장에는
`파일:줄` 근거를 달고, 확인하지 못한 것은 **미확인**으로 적는다.

**판정 기준:** `DIRECTION_260717.md` §1.2를 그대로 따른다. **품질/정확도와
유지보수성/복잡도**가 기준이다. 그 문서가 Neo4j를 "운영 DB 추가 = 유지보수성 비용"이라는
이유로 철회했으므로(§6), **운영 단위(서비스·DB·브로커)가 하나 늘 때마다 비용으로 계상한다.**

---

## 0. 결론

**지금은 마이크로서비스로 쪼개지 않는다.** 대신 **모듈러 모놀리스 + 역할별 배포**로 간다.
이미지와 코드베이스는 하나로 두고, 워크로드 성격별로 프로세스를 나눠 각각 따로 스케일한다.

근거는 세 가지다.

1. **지금 확장을 막는 결함은 "하나의 서비스"라서 생긴 것이 아니다.** 레플리카를 2대로
   늘리는 순간 깨지는 것들이다(§3). 프로세스 메모리에 둔 세션, 레플리카마다 뜨는 봇,
   로컬 디스크 기본값, 커넥션 풀 합계, 레플리카를 가리지 않는 IP 레이트리밋 같은 것들이다.
   서비스로 쪼개도 이 결함은 없어지지 않고, 쪼갠 서비스마다 하나씩 복제된다.
2. **경계를 네트워크로 바꿀 준비가 안 돼 있다.** 최상위 패키지 사이 import 순환이 13쌍이고,
   `users` FK가 거의 모든 도메인 테이블에 걸려 있으며, 설정 싱글톤 하나를 193개 파일이
   import한다(§2.5). 지금 네트워크 경계를 그으면 **분산 모놀리스**가 된다. 결합은 그대로이고
   네트워크 장애 모드만 더해지는 구조다.
3. **조직 규모가 요구하지 않는다.** 커밋의 약 95%가 한 사람이다(`git log`). 마이크로서비스의
   주된 이득인 팀별 독립 배포·소유권은 팀이 여럿일 때만 생긴다. 1인 운영에서는 서비스 N개가
   배포 파이프라인 N개, 대시보드 N개, 계약 버전 관리 N개가 될 뿐이다.

**마이크로서비스가 주려는 진짜 이득, 즉 워크로드별 독립 스케일링은 역할별 배포로
거의 전부 얻을 수 있다.** 코드도 이미 그쪽으로 가고 있다. Celery 큐 분리, deep_analysis
durable job, 코딩 outbox·lease·reconcile이 그렇다(§2.2). 남은 일은 그 패턴을 끝까지
마무리하고 레플리카 안전성 결함을 고치는 것이다.

**다시 검토할 조건은 §7에 둔다.** 조건이 충족되면 가장 먼저 떼어낼 후보는
**채널 게이트웨이 → 브라우저/fetch → 코딩 컨트롤 플레인** 순이다.
auth·chat·workflow는 마지막이거나 떼지 않는다.

---

## 1. 검토 범위

| 영역 | 규모 (Python 줄 수) |
|---|---|
| `neos/workflow` | 48,941 |
| `neos/coding` | 45,011 |
| `neos/agents` | 29,595 |
| `neos/api` | 19,715 |
| 기타 21개 패키지 | ~60,000 |
| **합계** | **~203,000** (테스트 파일 639개 별도) |

`api_gateway/`(Rust, Pingora, 1,303줄)와 `web/`(Next.js), 배포 파일
(`Dockerfile`, `docker-compose.*.yml`, `config/nginx/nginx.conf`)도 검토했다.

---

## 2. 현재 아키텍처 (실측)

### 2.1 프로세스 역할

코드에는 프로세스 역할이 여럿 있지만, **기본 구성에서는 전부 API 프로세스 하나에서 돈다.**

| 역할 | 진입점 | 기본 구성에서 실행 위치 |
|---|---|---|
| HTTP/SSE/WS API | `neos/main.py` (FastAPI, `lifespan` `:109-329`) | API 프로세스 |
| 채팅 턴 실행 | `ChatStreamPipeline.run`을 `StreamingResponse`로 (`neos/api/handlers/chat_handlers.py:751-780`) | **요청 코루틴 안** |
| deep_analysis job | `neos/tasks/deep_analysis_job_task.py` | `celery.enabled: false`(`config/neos.default.yaml:404`)면 **API 프로세스의 asyncio 태스크** (`:32` `_BACKGROUND_TASKS`) |
| 코딩 task | `neos/coding/workers/celery_tasks.py:40-95` | Celery 워커, Celery가 꺼져 있으면 dev 전용 in-process supervisor (`neos/main.py:181-185`) |
| 코딩 outbox 디스패처 | `neos/main.py:177-179` | API 프로세스 (레플리카마다 하나) |
| 코딩 워크스페이스 PTY/WS | `coding_runtime.workspace_streams` (`neos/main.py:184`) | API 프로세스 |
| 주기 작업 (cron 폴러, 만료, 정리) | Celery beat (`neos/workflow/celery_app.py:123`, `:170-275`) | beat 프로세스 |
| Telegram/Discord/Slack 봇 | `asyncio.create_task` (`neos/main.py:284-321`) | **API 프로세스 (레플리카마다 하나)** |
| Hyper-deep 병렬 실행 | Ray actor (`neos/workflow/ray_actors/executor_pool.py:25-36`) | `ray.enabled: false`(`config/neos.default.yaml:535`) |

Celery 앱은 **공유 싱글톤 하나**다(`neos/workflow/celery_app.py:39`). 코딩 task도
그것을 import한다(`neos/coding/workers/celery_tasks.py:33`). 큐는 이미 나뉘어 있어서
(`celery_app.py:48-96`, 4개 + 코딩 큐) **큐별 워커 풀 운영은 지금도 설정만으로 가능하다.**

### 2.2 이미 존재하는 "분리 가능한" 패턴

마이크로서비스 없이 확장성을 얻는 데 필요한 부품의 절반은 이미 있다.

| 패턴 | 위치 | 성질 |
|---|---|---|
| **DB 이벤트 로그 + 커서 스트림** | `neos/workflow/deep_analysis/event_stream.py:1-13` | `DAEvent.seq`가 단조 커서다. 어느 레플리카든 재구독할 수 있다. 문서가 `stream_manager`를 **명시적으로 거부**한 이유가 바로 프로세스 경계다 |
| **durable job + resume** | `neos/workflow/deep_analysis/jobs.py`, `ledger.recover()` | 실행자(Celery·asyncio)는 운영 선택일 뿐 API 계약이 아니다 (`deep_analysis_job_task.py:3-13`) |
| **outbox + SKIP LOCKED** | `neos/coding/outbox/repository.py:50` | 레플리카 N대에서 중복 발행하지 않는다 |
| **실행 lease + CAS 펜싱** | `coding_run_leases` (migration 040), `acks_late`/`reject_on_worker_lost` | 워커가 죽으면 reconcile이 다시 집어 간다 |
| **SKIP LOCKED 스케줄러** | `neos/tasks/scheduled_task_runner.py:58,232` | 워커 N대가 같은 tick을 두고 경쟁해도 안전하다 |
| **Redis 기반 공유 상태** | 레이트리미터 `neos/utils/rate_limiter.py:19-59`, 코딩 이벤트 pub/sub `neos/coding/transport/redis_events.py`, WS 티켓 `redis_tickets.py` | 레플리카 사이에서 안전하다 |
| **스토리지 추상화** | `neos/storage/storage_service.py` (S3/RustFS/Local) | 기본값만 `local`이다 (§3) |
| **프로바이더 레지스트리** | `neos/providers/base.py` `ModelProviderBase` | 확장 지점 |
| **관리형 샌드박스 컨트롤 플레인** | `neos/coding/managed/*`, E2B/Modal 어댑터 | 코드 실행은 이미 프로세스 밖(벤더)으로 나가 있다 |

**요점:** 이 저장소는 "요청과 실행의 분리"를 도메인별로 다시 발명해 왔다.
deep_analysis는 DB 로그로, coding은 outbox와 Redis로 풀었다. 확장성 작업은 새 경계를 긋는 일이
아니다. **이 두 패턴 중 하나로 통일해 남은 경로(채팅, 승인)까지 덮는 일이다.**

### 2.3 워크로드 프로파일

| 성격 | 해당 코드 | 스케일 축 |
|---|---|---|
| **IO 대기 (지배적)** | LLM 호출(`neos/providers/*`), 웹 검색, fetch | 동시 연결 수. asyncio라 프로세스당 수용량이 크다 |
| **장시간 실행** | deep_analysis(`dig` 하나에 600s), hyper-deep(30-60분), subagent(최악 ~16분, `neos/subagent/runtime.py:26`), 코딩 task | 워커 수. **HTTP 요청 수명과 분리해야 한다** |
| **메모리 과중** | Playwright를 **in-process로, 호출마다** 실행 (`neos/agents/search_agents/web_lookup.py:292`), 풀 없음 | 격리. 다른 워크로드와 같은 프로세스에 두면 OOM이 옆 요청까지 죽인다 |
| **CPU** | PDF 파싱(`pdf_text.py`, PyMuPDF), grader, 텍스트 정규화 | 부차적 |
| **장수 연결** | 봇 게이트웨이, 코딩 PTY WS | 싱글톤 또는 sticky 라우팅 |

이 표가 곧 **역할 분리의 근거**다(§5). 성격이 다른 워크로드를 나누는 이유는 스케일 축이
다르기 때문이지 코드 소유권 때문이 아니다. 이 목적이라면 프로세스만 나눠도 되고 서비스까지
나눌 필요는 없다.

### 2.4 데이터

- **Postgres 하나**(ParadeDB 이미지, `docker/Dockerfile.psql:2`. pgvector + pg_trgm.
  `pg_search`는 아직 TODO, `neos/agents/search_agents/knowledge_search.py:83`).
  테이블은 약 100개이고 `db/BOOTSTRAP_ORDER.txt` 하나의 순서로 부트스트랩한다.
  `[hoist]` 예외가 3건 있다. 도메인별로 마이그레이션이 깔끔하게 나뉘어 있지 않다는 신호다.
- **`users.user_id` FK가 거의 모든 도메인에 걸려 있다.** chat, cost, documents,
  coding(`db/migrations/038_add_coding_phase0.sql:5`), deep_analysis, mission, scheduled,
  approvals, preferences가 전부 여기에 묶인다. 비용 테이블은 `messages`·`conversations`에도
  FK가 있다(`db/chat_cost_tracking.sql:90-91`).
- **Redis 하나**를 캐시, 레이트리밋, 단기 메모리, pub/sub, WS 티켓, Celery broker/backend로
  동시에 쓴다(`neos/utils/cache.py:12-49`).

**DB-per-service로 가려면** `users` FK를 전부 ID 참조로 바꾸고, 신원 복제나 조회 API를
만들고, 비용 집계를 이벤트 기반으로 바꿔야 한다. 그 대가로 얻는 이득은 이 규모에서 없다.
**Postgres 하나로 수직 확장하고 읽기 복제본을 두는 방식이 판정 기준에 맞는다.**

### 2.5 결합도

최상위 패키지 사이 import를 grep한 결과, **양방향 순환이 13쌍** 나왔다.
대표적인 것만 적는다.

| 순환 | 근거 |
|---|---|
| `api ↔ coding` | `neos/coding/workers/celery_runtime.py:9-10`이 `neos.api.channels.*`를 import한다. 코딩 워커가 봇 레이어로 역참조한다 |
| `api ↔ workflow` | `neos/workflow/graph.py:3528,3549,3578,3604` |
| `workflow ↔ agents` | `graph.py:10-11` 주석이 "순환 import 회피"를 이유로 함수 안에서 lazy import한다 |
| `coding ↔ subagent`, `memory ↔ learn`, `database ↔ utils`, `api ↔ database` 등 | 데이터 결합도 분석 |

추가로:

- `neos/workflow/graph.py`는 **3,850줄**이고 `AgentState`(`neos/workflow/state.py:51`)는 공유 가변 상태다.
- `neos.config.settings`는 **193개 파일**이 import하는 싱글톤이고 스키마는 2,300줄이다
  (`neos/config/schema.py`).
- 결합도가 **가장 낮은** 패키지는 `observability`다(`config` 외 외부 의존 0).
  `deep_analysis`는 스스로 "내부 의존 4개, 프레임워크 프리" 원칙을 지킨다
  (`DIRECTION_260717.md` §2.4).

**해석:** `api`·`workflow`·`coding`이 허브 노드로 서로 얽혀 있다. 지금 이 사이에 네트워크
경계를 그으면 함수 호출이 RPC로 바뀔 뿐 의존은 그대로 남는다. **경계는 네트워크보다 먼저
코드에서 강제돼야 한다**(§6 P2).

---

## 3. 확장성 결함 — 실체

**전부 "API를 2대로 늘리면 깨지는가"를 기준으로 판정했다.** 서비스 분리 여부와는 관계없다.

| # | 결함 | 근거 | 레플리카 N>1에서 일어나는 일 | 심각도 |
|---|---|---|---|---|
| S1 | **채팅 턴이 HTTP 요청 수명에 묶여 있다** | `chat_handlers.py:751-780` | 배포·재시작·LB 타임아웃 때 진행 중인 턴이 사라진다. 다른 레플리카로 재접속해도 이어 받을 수 없다. 턴 하나가 subagent로 수 분까지 늘어난다 | 🔴 |
| S2 | **승인 스트림이 프로세스 메모리에 있다** | `approval_handlers.py:211,262`(POST가 세션 생성과 재개 태스크 실행) ↔ `:296`(GET이 `stream_manager.get_session`) | POST와 GET이 다른 레플리카로 가면 스트림이 세션을 못 찾는다. nginx는 `least_conn`이고 sticky가 없다(`config/nginx/nginx.conf:47-55`) | 🔴 |
| S3 | **봇이 레플리카마다 뜬다** | `neos/main.py:284-321` | 같은 토큰으로 N개가 붙어 인바운드를 중복 처리한다. `channel_inbound_idempotency`(migration 053)가 일부 막아 주는지는 **미확인** | 🔴 (봇을 켰을 때) |
| S4 | **IP 레이트리밋이 BFF 뒤에 걸려 있다** | `nginx.conf` `limit_req zone=api_limit` 60r/m burst 20, 키는 `$binary_remote_addr` | 브라우저 트래픽이 Next.js 서버를 거쳐 들어오므로(`web/lib/backend-api.ts`) **전체 사용자가 IP 하나의 60r/m를 나눠 쓴다.** 사용자가 늘면 가장 먼저 부딪힌다 | 🔴 |
| S5 | **Postgres 커넥션 예산이 초과된다** | 메인 풀 20+30(`neos/config/schema.py:70-71`) + 체크포인터 풀 20+40(`neos/workflow/checkpointer.py:97-98`, 별도 엔진) = **프로세스당 최대 110** | Postgres 기본 `max_connections`는 100이다. API 3대만 해도 330이고, Celery prefork 자식마다 또 곱해진다. 서비스를 쪼개면 **더 나빠진다** | 🔴 |
| S6 | **deep_analysis가 기본 구성에서 API 프로세스 안에서 돈다** | `celery.enabled: false` → `_BACKGROUND_TASKS` | 재시작하면 run이 죽는다. resume 진입점은 있지만 자동으로 트리거되지 않는다 | 🟠 |
| S7 | **로컬 디스크 기본값** | `storage.provider: local`(`config/neos.default.yaml:302-312`), `neos/dataset/record_sink.py:47-100`(프로세스별 JSONL, `rglob`으로 읽음) | 업로드한 문서가 받은 레플리카에만 존재한다. 데이터셋 레코드는 호스트마다 흩어진다 | 🟠 |
| S8 | **코딩 워크스페이스 WS가 nginx를 통과하지 못한다** | `nginx.conf`가 `Connection ""`로 고정하고 `Upgrade` 헤더가 없다. 브라우저가 백엔드에 직접 붙는다(`web/lib/server-config.ts:10-16`) | PTY가 프로세스 로컬이라 sticky가 필요한데, 라우팅 계층이 없다 | 🟠 |
| S9 | **Playwright를 in-process로 매 호출마다 실행한다** | `web_lookup.py:292` | 메모리 급증과 hang이 같은 프로세스의 모든 요청에 전파된다 | 🟠 |
| S10 | **서킷브레이커가 프로세스 로컬이다** | `neos/utils/circuit_breaker.py:21` | 레플리카마다 따로 트립하므로, 벤더 장애 때 N배로 두드린다 | 🟡 |
| S11 | **Celery 경계를 넘을 때 trace context가 전파되지 않는다** | `celery_tasks.py`에 inject/extract 없음 | 워커 span이 요청 trace와 끊긴다. 역할을 분리하면 관측성이 떨어진다 | 🟡 |
| S12 | **배포 산출물이 깨져 있다** | `Dockerfile:14-19`가 루트에 없는 `requirements.txt`를 쓰고 `EXPOSE 8000`인데 실제 포트는 8518이다. enterprise compose에 **Celery worker·beat가 없다** | 문서화된 "프로덕션" 토폴로지가 빌드되지 않는다. 떠도 스케줄 작업을 소비할 곳이 없다 | 🔴 (전제 조건) |
| S13 | **Ray 기동 경합** | `neos/main.py:213-250`에서 레플리카마다 named actor 생성 | 동시 부팅 시 경합한다. 기본값은 꺼져 있다 | 🟡 |

**S1~S13 중 마이크로서비스화로만 풀리는 결함은 없다.** S9(Playwright 격리) 하나만
"별도 프로세스"가 필요한데, 그것도 별도 **서비스**일 필요는 없다(§5의 `fetch` 워커 큐로 충분하다).

### 3.1 추가 결함 — 2026-09-28 코드 대조 (`403aeb77`)

[NEOS_MOMENTUM_ANALYSIS_20260928.md](NEOS_MOMENTUM_ANALYSIS_20260928.md) §5에서 찾았다. 판정 기준은 위 표와 같다.
S14·S15는 §2.2가 "DA는 durable job + resume으로 이미 분리 가능하다"고 본 판단을 **동시 실행 안전성 쪽에서** 보완한다.

| # | 결함 | 근거 | 레플리카·워커 N>1에서 일어나는 일 | 심각도 |
|---|---|---|---|---|
| S14 | **DA에 실행 lease가 없다** | `jobs.py:66` `RESUMABLE_STATUSES = {"running","failed"}` · resume 핸들러가 status만 본다 · `ledger.recover()`가 `investigating`을 `open`으로 되돌린다 | 살아 있는 run에 resume하면 실행자가 둘이 된다. 이중 지출, 질문 탈취, 원장 작성자 둘. 코딩의 `coding_run_leases`(펜싱 + heartbeat) 패턴이 없다 | 🔴 |
| S15 | **Celery `visibility_timeout`이 DA 시간 한도보다 짧다** | `task_acks_late=True`(`schema.py:682`) · DA `job_time_limit=3900` · `visibility_timeout` 설정 0건(kombu Redis 기본 1시간) | 1시간이 넘는 run은 원래 워커가 살아 있어도 다른 워커로 재전달된다. S14와 겹치면 lease 없이 동시에 실행된다 | 🔴 (Celery on) |
| S16 | **브로커가 축출 정책을 가진 캐시 Redis와 같다** | `docker-compose.enterprise.yml:26,94` — 브로커 db 2 + `--maxmemory-policy allkeys-lru` | 메모리가 차면 대기 태스크 키가 축출될 수 있다. 조용한 유실이다 | 🔴 |
| S17 | **워커 프로세스 전역 상태가 태스크 사이로 샌다** | `set_lesson_session_factory(None)`이 `_USE_MEMORY_ONLY`를 프로세스 전체에 고정(`learn/lessons.py`) · DA·gepa_opt 태스크가 `asyncio.run`마다 새 루프를 만드는데 전역 `db_manager`와 `LLMFactory._llm_cache`를 재사용한다 ⚠️ 미재현 | 같은 워커 자식에서 코딩 전달 다음에 도는 태스크가 lesson과 overlay를 못 읽는다. 풀과 클라이언트가 다른 루프에 묶여 있을 수 있다. 코딩 워커만 전달마다 새 매니저를 만들어 이를 피한다 | 🟠 |
| S18 | **LLM 호출 기록에 테넌트가 없다** | `coding/runtime.py:649-656`이 `TrackedCodingModel`에 `user_id`·`session_id`를 넘기지 않는다(기본값 `""`) | 비용 귀속과 테넌트별 계량이 불가능하다. S7의 JSONL에 테넌트 구분 없이 섞인다 | 🟠 |
| S19 | **memory 샌드박스를 production에서 거부하지 않는다** | `neos.default.yaml` `sandbox.enabled: false` + `provider: memory` · production·staging yaml에 `sandbox` 섹션 없음 | `enabled`만 켜면 host subprocess로 돈다. 지금은 off라 잠재 위험이다 | 🟠 |

**P0에 붙일 것:** S14(DA lease + resume 409) · S15(`broker_transport_options.visibility_timeout` > `job_time_limit`) · S16(브로커용 Redis `noeviction` 분리). S12의 compose worker·beat 추가와 같은 PR 묶음이 자연스럽다.

---

## 4. 마이크로서비스화 — 얻는 것과 잃는 것

| 기대 이득 | NEOS에서 실현되는가 | 대안 |
|---|---|---|
| 워크로드별 독립 스케일링 | ✅ 실현된다 | **역할별 배포로 동일하게 얻는다** (§5) |
| 장애 격리 | 부분적 | 프로세스 격리로 얻는다(Playwright, 봇). 네트워크 경계까지는 필요 없다 |
| 팀별 독립 배포 | ❌ 팀이 하나다 | — |
| 기술 스택 이질성 | ❌ 전부 Python이다(Rust 게이트웨이는 미배포) | — |
| 의존성 충돌 회피 | 약하다 (Playwright·Ray·PyMuPDF가 무겁지만 충돌은 없다) | 이미지 variant로 해결한다 |
| 보안 경계 | 이미 실현돼 있다 — 코드 실행은 샌드박스 프로바이더에 있다 | — |

| 비용 | 규모 |
|---|---|
| import 순환 13쌍을 RPC 계약으로 전환 | 대 |
| `users` FK 제거, 신원 전파, 분산 트랜잭션 또는 사가 | 대 |
| 설정 슬라이싱 (2,300줄 스키마, 193개 파일) | 중~대 |
| 서비스별 CI/CD·대시보드·알람·버전 호환성 | 서비스 수에 비례해 **영구적으로** 든다 |
| 커넥션 예산 악화 (S5) | 서비스 수에 비례한다 |
| 로컬 재현 비용 (dev compose 복잡도, 이미 CI가 Postgres 없이 도는 테스트가 있음) | 중 |

**판정:** 이득 쪽에서 실현되는 항목은 전부 대안으로 얻을 수 있다. 비용은 전부 유지보수성
비용이고 영구적이다. §1.2 기준으로 **기각**한다.

---

## 5. 권고 아키텍처 — 모듈러 모놀리스 + 역할별 배포

### 5.1 목표 토폴로지

```
                ┌──────────── web (Next.js BFF) ────────────┐
                │                                            │ (coding WS 직결)
                ▼                                            ▼
        ┌─────────────┐   ┌──────────────────────────────────────────┐
        │   ingress   │──▶│ api (N대, 무상태)                          │
        │ nginx/L7 LB │   │  HTTP CRUD · job 제출(202) · 이벤트 스트림   │
        └─────────────┘   │  (DB 커서 또는 Redis Streams에서 재생)        │
               │          └──────────────────────────────────────────┘
               │ sticky(task_id)          │ enqueue          ▲ events
               ▼                          ▼                  │
        ┌──────────────┐   ┌───────────────────────────────────────────┐
        │ coding-ws    │   │ Celery 워커 풀 (큐별, 독립 스케일)              │
        │ (PTY 소유)    │   │  q:chat      채팅 턴 (P1)                   │
        └──────────────┘   │  q:analysis  deep_analysis / hyper_deep     │
                           │  q:coding    코딩 task + managed 샌드박스     │
                           │  q:fetch     Playwright/PDF (메모리 격리)     │
                           │  q:default   기타                           │
                           └───────────────────────────────────────────┘
        ┌──────────────┐   ┌──────────────┐
        │ beat (1대)    │   │ channels (1대)│  Telegram/Discord/Slack
        └──────────────┘   └──────────────┘
                 │                 │
                 ▼                 ▼
         Postgres (primary + read replica, PgBouncer 앞단) · Redis · S3/RustFS
```

**원칙**

- **이미지 하나, 진입점 여러 개.** `neos api` / `neos worker -Q …` / `neos beat` /
  `neos channels` / `neos coding-ws`. 코드 경계는 그대로 두고 **lifespan에서 무엇을
  띄울지만 역할로 결정한다.**
- **API는 무상태다.** 장시간 실행은 전부 job으로 넘기고, 스트림은 **어느 레플리카에서든
  재생할 수 있는 매체**(DB 이벤트 로그 또는 Redis Streams)에서 읽는다.
- **싱글톤 역할은 명시적인 1대로 둔다**(beat, channels). 리더 선출을 만들지 않는다.
  배포 단위에서 replicas=1로 고정하는 것이 가장 단순하다.
- **sticky가 꼭 필요한 곳은 하나만 남긴다**(coding-ws, PTY 소유). 여기만 `task_id`로
  라우팅한다.

### 5.2 역할별 스펙

| 역할 | lifespan에서 띄우는 것 | 띄우지 않는 것 | 스케일 | 헬스 |
|---|---|---|---|---|
| `api` | DB·Redis 풀, OTel, 메트릭, 라우터 | 봇, outbox 디스패처¹, PTY reaper, Ray, in-process job | CPU/연결 수 기준 HPA | `/api/v1/health` |
| `worker:chat` (P1) | DB·Redis, LLM 팩토리 | HTTP | 큐 길이 기준 | Celery ping |
| `worker:analysis` | 위와 같음 + (선택) Ray 클라이언트 | HTTP | 큐 길이 기준, 긴 soft/hard timeout | Celery ping |
| `worker:coding` | 코딩 런타임, managed 어댑터 | HTTP | 큐 길이 기준 | Celery ping |
| `worker:fetch` | Playwright **브라우저 풀**(프로세스당 1개 재사용) | 나머지 | 메모리 기준, `max-tasks-per-child`로 누수 차단 | Celery ping |
| `beat` | 스케줄만 | 나머지 전부 | **replicas=1 고정** | 프로세스 생존 |
| `channels` | 봇 어댑터, `ChannelGateway` | HTTP 라우터 | **replicas=1 고정** (Discord 샤딩이 필요해지면 재검토) | 게이트웨이 연결 상태 |
| `coding-ws` | `workspace_streams`, PTY | 나머지 | sticky(`task_id`) | WS 핑 |

¹ outbox 디스패처는 SKIP LOCKED라 N대에서도 안전하다(`neos/coding/outbox/repository.py:50`).
다만 API의 지연 예산을 지키려고 워커로 옮긴다.

### 5.3 커넥션 예산 (S5)

- **PgBouncer**(transaction pooling)를 앞에 둔다. 운영 단위가 하나 늘어나지만 이것 없이는
  역할 분리가 S5를 더 악화시킨다. **이번 권고에서 유일하게 새로 추가하는 인프라다.**
- 체크포인터 엔진을 메인 `db_manager` 엔진과 **합친다**
  (`neos/workflow/checkpointer.py:146-148`). 프로세스당 풀을 하나로 만든다.
- 역할마다 풀 크기를 따로 둔다. 예를 들어 `api` 10+10, `worker` 는 동시성 × 2 정도다.
  구체 수치는 부하 측정 후에 정한다(**미정**).
- asyncpg + PgBouncer transaction 모드는 prepared statement 캐시를 꺼야 한다
  (`statement_cache_size=0`). 체크포인터·ORM 양쪽 모두 해당된다.

---

## 6. 로드맵

규모 표기: 소(≤1일) · 중(수일) · 대(1주+).

### P0 — 레플리카 2대가 되게 한다 (전제 조건)

| # | 작업 | 해소 | 규모 | 수용 기준 |
|---|---|---|---|---|
| P0-1 | Dockerfile을 `uv sync --locked` 기반으로 고치고 포트를 정리한다. enterprise compose에 worker·beat를 추가한다 | S12 | 소 | CI에서 이미지를 빌드하고, compose로 기동해 cron 작업 1건이 소비되는 것을 확인한다 |
| P0-2 | **역할 플래그 도입.** `NEOS_ROLE`(또는 역할별 진입점)으로 lifespan이 봇·PTY·outbox·Ray를 선택적으로 띄운다 | S3, S13, S8 일부 | 중 | `api` 역할로 2대를 띄웠을 때 봇 연결이 0개, `channels` 역할 1대에서 1개인 것을 확인한다 |
| P0-3 | 레이트리밋 키를 사용자 기준으로 바꾼다. BFF가 사용자 식별 헤더를 넘기고 nginx는 BFF IP를 신뢰한다. 또는 nginx 제한을 걷어내고 앱의 `RedisRateLimiter`로 일원화한다 | S4 | 소 | 사용자 A가 제한에 걸려도 사용자 B는 통과한다 |
| P0-4 | 커넥션 예산: 체크포인터 엔진을 통합하고 PgBouncer를 추가한다 | S5 | 중 | 역할별 최대 커넥션 합계가 `max_connections`의 80% 이하임을 계산표로 남긴다 |
| P0-5 | 승인 스트림을 `stream_manager`에서 DB 이벤트 로그나 Redis Streams로 옮긴다 | S2 | 중 | POST와 GET을 서로 다른 레플리카로 보내도 이벤트를 받는다 (통합 테스트) |
| P0-6 | 스토리지 기본값을 `s3`/`rustfs`로 바꾸고(최소한 production yaml), `record_sink`를 오브젝트 스토리지에 쓰게 하거나 공유 볼륨을 전제로 명시한다 | S7 | 소~중 | 레플리카 A에 업로드한 문서를 B에서 읽는다 |

### P1 — 장시간 실행을 요청에서 떼어낸다

| # | 작업 | 해소 | 규모 | 수용 기준 |
|---|---|---|---|---|
| P1-1 | **production에서 `celery.enabled: true`.** deep_analysis in-process 폴백은 dev에만 남긴다 | S6 | 소 | API를 재시작해도 run이 계속 진행된다 |
| P1-2 | **채팅 턴 durable화.** deep_analysis Phase 3 패턴(202 + run_id, DB 커서 스트림, 커서 재구독)을 채팅에 적용한다. 매체는 §8의 결정에 따른다 | S1 | **대**, FE 계약이 바뀐다 | 턴이 도는 중에 API를 롤링 배포해도 클라이언트가 커서로 재구독해 턴을 끝까지 받는다 |
| P1-3 | `fetch` 큐와 브라우저 풀. Playwright 호출을 워커로 옮기고, 인라인 경로는 HTTP-only fetch만 남긴다 | S9 | 중 | fetch 워커를 OOM-kill해도 API 에러율이 변하지 않는다 |
| P1-4 | Celery 헤더로 trace context를 전파한다 (W3C traceparent) | S11 | 소 | Jaeger에서 요청 → 워커 span이 한 trace로 이어진다 |
| P1-5 | coding-ws 라우팅: ingress에 WS 업그레이드와 `task_id` 해시 라우팅을 추가한다 | S8 | 중 | coding-ws 2대에서 같은 task의 재접속이 같은 인스턴스로 간다 |

**P1-2가 이 문서에서 가장 비싸고 가장 중요한 항목이다.** `DIRECTION_260717.md` §3.2가
deep_analysis에서 이미 증명했다. "동기 요청 안에서 장시간 작업을 완주시키는 구조는
틀렸다"는 결론은 채팅에도 그대로 적용된다. subagent가 채팅 턴을 수 분으로 늘리는 순간
같은 문제가 생긴다. 다만 짧은 턴까지 job으로 돌리면 첫 토큰 지연이 늘어나므로,
**"짧은 턴은 인라인, 도구·subagent 진입 시 job으로 승격"하는 하이브리드**도 선택지다(§8).

### P2 — 경계를 코드에서 강제한다 (미래의 분리를 싸게 만든다)

| # | 작업 | 규모 | 수용 기준 |
|---|---|---|---|
| P2-1 | **import-linter 계약을 CI에 넣는다.** 최상위 레이어 규칙(`api → application → domain`, `workflow ↛ api`, `coding ↛ api.channels`)을 정한다. 지금의 위반은 baseline으로 동결하고 새 위반만 막는다 | 중 | 새 순환 import가 CI에서 실패한다 |
| P2-2 | `coding ↛ api.channels` 역참조를 제거한다 (`celery_runtime.py:9-10`). 라이프사이클 푸시를 이벤트(outbox)로 바꾸고 `channels` 역할이 소비하게 한다 | 중 | `neos/coding`에서 `neos.api` import가 0개 |
| P2-3 | `workflow ↔ agents` 순환: `AgentRuntime` 프로토콜을 도입한다 (`ModelProviderBase`와 같은 방식) | 대 | `graph.py`의 lazy import 회피 주석을 삭제할 수 있다 |
| P2-4 | 서킷브레이커 상태를 Redis로 옮긴다 (S10) | 소 | 레플리카 A가 트립하면 B도 차단한다 |
| P2-5 | 설정 슬라이스: 역할별로 필요한 설정 섹션을 선언한다 (분리의 선행 작업. 지금은 문서화만) | 소 | — |

**P2는 확장성 작업이 아니다.** 나중에 마이크로서비스가 필요해졌을 때 분리 비용을 "대"에서
"중"으로 낮추는 **옵션 가치**에 대한 투자다. 동시에 지금의 유지보수성도 개선한다.

---

## 7. 재검토 트리거 — 언제 서비스를 분리하나

아래 중 **하나라도** 실제로 관측되면 해당 후보를 다시 검토한다. "예상된다"는 트리거가 아니다.

| 트리거 | 관측 지표 |
|---|---|
| 팀이 2개 이상이 되고 배포 충돌이 생긴다 | 한 도메인 배포가 다른 도메인 롤백을 유발하는 일이 분기당 2회 이상 |
| 역할별 배포로는 풀리지 않는 의존성 충돌이 생긴다 | 한 역할의 의존성 업그레이드가 다른 역할을 깬다 (예: 브라우저·ML 런타임) |
| 이질적인 하드웨어가 필요해진다 | GPU 추론, 로컬 임베딩 모델 상주 |
| 보안·규제상 격리가 필요해진다 | 테넌트별 데이터 격리 요구 (`DIRECTION_260717.md` §3.5 — 현재 격리는 0이다) · 🆕 (2026-09-28) 이 줄은 **서비스 분리**의 트리거다. 멀티테넌트 SaaS로 판다면 테넌트 격리는 트리거가 아니라 **전제**다. 서비스를 분리하지 않아도 `tenant_id`(런·원장·스토어·overlay·비용 기록), 테넌트별 admission과 레이트리밋이 필요하다. 이것은 §8 결정 D-6으로 올린다 |
| 외부 공개 API가 생긴다 | 제3자에게 버전 계약을 약속해야 한다 |

### 분리 후보 우선순위 (트리거가 충족됐을 때)

| 순위 | 후보 | 이유 | 선결 조건 |
|---|---|---|---|
| 1 | **channels (봇 게이트웨이)** | 이미 싱글톤이고, 외부 연결 수명이 다르며, 인바운드가 멱등 처리된다(migration 053) | P0-2, P2-2 (코딩 → 채널 역참조 제거) |
| 2 | **fetch/브라우저** | 자원 프로파일이 가장 이질적이고 인터페이스가 좁다 (URL → 텍스트·blob) | P1-3 |
| 3 | **coding 컨트롤 플레인** | 테이블 20개를 자체 소유하고, 큐·API·WS가 따로 있다. 가장 큰 자족 도메인이다 | P2-2, `users` FK를 ID 참조로 전환, `neos.coding`을 import하는 비-coding 파일 27개 정리 |
| — | auth·chat·workflow·cost | FK와 import 허브. 분리 비용이 이득보다 크다 | 분리하지 않는다 |

**`observability`는 서비스가 아니라 라이브러리다.** 의존이 가장 적어 패키지로 떼기는
쉽지만, 네트워크 경계로 만들 이유는 없다.

**Rust `api_gateway/`:** 어느 compose에도 포함돼 있지 않다. upstream이 하나라
로드밸런싱이 사실상 no-op이고(`api_gateway/src/proxy.rs:41-53`), rate_limit 설정은
파싱만 하고 적용하지 않는다(`config.rs:100-106`). Python 쪽 인증도 그대로 남아 있다.
**채택하든 제거하든 결정이 필요하다**(§8). 채택하지 않을 거라면
`API_GATEWAY_ENABLED` 경로를 걷어내야 한다. `API_GATEWAY_TRUSTED_IPS`가 비어 있으면
**모든 IP를 신뢰한다**(`neos/api/dependencies/auth.py:87-93`). 플래그 하나만 잘못
켜도 `X-User-ID` 위조가 가능해진다.

---

## 8. 결정이 필요한 것

| # | 결정 | 선택지 | 권고 |
|---|---|---|---|
| D-1 | 채팅 이벤트 매체 (P1-2) | (a) deep_analysis처럼 DB 이벤트 로그 + 커서 폴링 (b) Redis Streams (c) 하이브리드 — 토큰 델타는 Redis, 확정 이벤트는 DB | **(c)**. 토큰 델타를 DB에 행 단위로 쓰면 쓰기 증폭이 크다. 확정 이벤트만 DB에 두면 D8(append-only) 불변식과 재생성이 유지된다. 단, 매체가 둘이 되는 복잡도 비용이 있으므로 (a)로 먼저 측정해 볼 가치가 있다 |
| D-2 | 채팅 job화 범위 | 전부 job / 도구·subagent 진입 시 승격 / 인라인 유지 + 드레인만 | **승격 방식.** 짧은 턴의 첫 토큰 지연을 보존한다 |
| D-3 | Ray 존속 | 유지 / Celery로 통합 | **통합을 검토한다.** 작업 분산 기구가 둘이면(Celery + Ray) 유지보수성 비용이다. 기본값이 꺼져 있고 SSE 콜백이 Ray 경계에서 유실된다(`executor_pool.py:9`). 실제 사용량 데이터를 본 뒤 결정한다 |
| D-4 | Rust 게이트웨이 | 채택 (upstream 다중화, rate limit 구현) / 제거 | **제거에 무게를 둔다.** 인증 이중화와 운영 단위 증가를 정당화할 근거가 지금은 없다. 제거한다면 Python의 gateway-trust 경로도 함께 걷어낸다 |
| D-5 | 코딩 Docker 프로바이더 | 단일 호스트로 고정 유지 / managed(E2B/Modal)로 일원화 | Docker 볼륨이 호스트 로컬이다(`neos/coding/sandbox/docker.py:382`). 멀티 호스트로 간다면 managed가 유일한 경로다 |
| D-6 🆕 | 테넌트 경계 (2026-09-28) | user 단위 유지 / org(tenant) 단위 도입 | 판정하지 않았다. 지금 격리는 전부 `owner`(user)에서 끝난다. org 차원은 관리형 샌드박스 할당 평면(migration 045)에만 있다. 벤더 키, 레이트리밋, 서킷을 모든 테넌트가 공유한다. SaaS로 간다면 **org 단위 + 런 경계의 `RunContext`/`TenantContext` 주입**을 권한다. S17·S18이 같은 객체로 풀린다 |

---

## 9. 미확인

- **채팅 SSE에서 클라이언트가 끊겼을 때 파이프라인이 취소되는지, 끝까지 돌며 과금되는지.**
  S1의 실제 비용을 좌우한다.
- `channel_inbound_idempotency`가 봇 N개 중복 연결 상황에서 중복 응답까지 막는지.
  S3의 심각도를 좌우한다.
- 실제 트래픽·동시성 수치. **이 문서는 부하 측정 없이 구조만으로 판정했다.**
  P0-4의 풀 크기와 워커 수는 측정 후에 정한다.
- 운영 환경의 실제 배포 형태(k8s 여부, 관리형 Postgres 여부). 저장소 안에는 compose뿐이다.
- `neos/workflow/async_research_event_stream.py`(Redis Streams)는 자기 파일 밖에서
  참조되지 않는다. 사용 예정인 코드인지 죽은 코드인지 확인이 필요하다. 살아 있다면
  D-1 (b)의 기반이 된다.

---

## 10. 요약

1. **쪼갤 필요는 없다. 지금은.** 확장을 막는 13개 결함 중 서비스 분리로만 풀리는 것은 0개다.
   서비스 분리는 오히려 S5(커넥션)를 악화시키고 결함을 서비스 수만큼 복제한다.
2. **이득은 역할별 배포로 가져간다.** 이미지 하나, 진입점 여러 개로 api(무상태),
   큐별 워커, beat·channels 싱글톤, coding-ws(sticky)를 둔다. 새로 추가하는 인프라는
   PgBouncer 하나다.
3. **가장 중요한 작업은 채팅 턴을 요청 수명에서 떼는 것이다(P1-2).** deep_analysis Phase 3가
   이미 증명한 패턴을 채팅까지 넓히면 된다.
4. **P0(레플리카 2대 가능) → P1(장시간 실행 분리) → P2(경계 강제)** 순서로 간다.
   P2는 미래의 분리를 싸게 만드는 보험이다.
5. **재검토 트리거는 조직·하드웨어·보안이지 트래픽이 아니다.** 트리거가 충족되면
   channels → fetch → coding 순으로 떼어낸다.
