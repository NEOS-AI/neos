# Hermes Self-Improving → NEOS 갭 분석

README 마케팅은 “closed learning loop”를 기본 탑재처럼 적는다. 코드 기준 **Honcho·LLM 큐레이터 통합·write-approval·agent-created 보안스캔은 기본 꺼짐.**

작성: explore 서브에이전트 `Analyze Hermes self-improve` (2026-09-11). 메인 에이전트가 파일로 고정.

## 1. Hermes 학습 루프 아키텍처

```
[유저 턴]
   │  system: SKILLS_GUIDANCE + MEMORY_GUIDANCE + session_search 안내
   │  포그라운드: skill_view / skill_manage / memory (자율, 게이트 기본 OFF)
   ▼
[턴 종료 turn_finalizer]
   │  memory nudge: 유저 턴 N회마다  (기본 10)
   │  skill  nudge: 툴 이터레이션 N회마다 (코드 기본 10)
   ▼
[background_review 포크]  auxiliary.background_review.enabled 기본 ON (fail-open)
   │  대화 스냅샷 재생 → memory / skill_manage 기록
   │  메인 세션·state.db에 쓰지 않음
   ▼
[~/.hermes/skills/  +  MEMORY.md/USER.md]
   │
   ▼
[curator]  유휴+주기 (cron 아님). 기본: 결정론적 stale/archive만
           LLM consolidate는 curator.consolidate=false
   │
   ▼
[session_search] FTS5, LLM 없음  ← README의 “LLM summarization”은 과장
[Honcho] memory.provider=honcho 일 때만  ← 플러그인
```

| 요소 | 기본 | 근거 |
|---|---|---|
| MEMORY.md + USER.md | ON | `cli-config.yaml.example`; `agent_init._init_memory` |
| 메모리 넛지 | ON (10턴) | `agent_init.py` `_memory_nudge_interval=10` |
| 스킬 생성 넛지 | ON (코드 10) | `creation_nudge_interval` |
| post-turn background review | ON (fail-open) | `load_background_review_settings` default True |
| `/learn` | 온디맨드 | `learn_prompt.build_learn_prompt` |
| curator prune | ON, 7일+2시간 idle | `curator.is_enabled` default True |
| curator LLM consolidate | **OFF** | `DEFAULT_CONSOLIDATE = False` |
| `skills.write_approval` / `memory.write_approval` | **OFF** | `write_approval.py` default False |
| `skills.guard_agent_created` | **OFF** | `_guard_agent_created_enabled` |
| Honcho | **OFF** | `memory.provider` 비어 있으면 builtin만 |
| session_search | CLI 기본 toolset | `toolsets.py` `hermes-cli` |

**README vs 코드**

- “FTS5 + LLM summarization”: `tools/session_search_tool.py`는 **“No LLM calls”**. LLM 요약은 compaction과 세션 타이틀에 있다.
- “Autonomous skill creation after complex tasks”: 결정론적 추출기가 없다. 리뷰 포크가 대화를 읽고 `skill_manage`를 쓸지 판단.
- Honcho는 closed-loop 필수 부품이 아니라 플러그인.

## 2. 핵심 요소 카탈로그

| 요소 | Hermes 파일 | 기본 활성? | NEOS 대응 | 성숙도 |
|---|---|---|---|---|
| 절차 스킬(마크다운) | `skill_manage` → `~/.hermes/skills/` | ON (도구+넛지) | `neos/skills/`는 **실행형 Python+SKILL.md**; 에이전트 생성 경로 없음 | 로더만 |
| 대형 스킬팩 | `skills/` + `optional-skills/` | bundled 시드 ON | 레포 `skills/` 대량 + `autoskill` **미배선** | 자산은 큼 |
| `/learn` | `learn_prompt.build_learn_prompt` | 수동 | `MemoryManager.learn()`은 API만, **호출자 0** | 공백 |
| 사용 중 self-improve | Skills 블록 + `_SKILL_REVIEW_PROMPT` | 넛지 ON | 없음 | 공백 |
| 백그라운드 리뷰 포크 | `background_review.py`, `turn_finalizer` | ON | 없음 | 공백 |
| Curator pin/prune | `curator.py`, `curator_backup.py` | prune ON / LLM OFF | Beat는 청소·스케줄·DA 리포트 | 공백 |
| Bounded memory | MEMORY.md 2200 / USER.md 1375 | ON | `neos/memory/` 3계층 + `012_` | 스키마는 있음. chat/coding 미연결 |
| 메모리 넛지 | `_tick_memory_nudge` | ON | 없음 | 공백 |
| 크로스세션 검색 | FTS5 + `session_search` | ON (CLI) | `message_embeddings` / similarity-chat | 다른 패러다임 |
| 유저 모델 | USER.md + (옵션) Honcho | builtin ON / Honcho OFF | `autonomy_level`, refinement 소스 선호 | 얕음 |
| 궤적 수집 | `trajectory.py` | 연구용 | `dataset/collector.LLMCallCollector` | 학습 루프와 분리 |
| 피드백 | 대화 교정 = 스킬 신호 | — | `013_` Vote 카테고리 | 스킬로 안 흘러감 |
| 스케줄러 | curator는 **cron 아님**; idle tick | ON | Celery Beat | Beat는 이미 있음 |

교차검증: `MemoryManager.learn()` (`neos/memory/manager.py:166`) 호출자 grep 0건. `_save_episode_memory`는 `workflow/graph.py`에만 있다.

## 3. 스킬 생성 / 개선 / 큐레이터 상세

세 경로. 모두 최종 쓰기는 `skill_manage` → `SKILL.md`.

1. **포그라운드 자율** — `SKILLS_GUIDANCE`: non-trivial workflow면 저장, 이슈 있으면 patch.
2. **포스트턴 리뷰 포크** — `_iters_since_skill >= interval`이면 `_spawn_background_review`. `max_iterations=16`. 메인 세션에 쓰지 않음.
3. **`/learn` (사용자 명시)** — 소스 수집 → 기존 스킬 확장 또는 create. 소스 텍스트는 DATA (`_SOURCE_HYGIENE`).

사용 중 self-improve 신호는 구조화 평가가 아니라 **대화**. 백그라운드는 `skill_view` 없이 patch 거부. bundled/hub/pinned/user-owned는 리뷰가 못 고침.

Curator:
- 트리거: CLI 시작 / gateway housekeeping / serve 타이머. cron 잡이 아님.
- 1단계 (기본 ON): 30일 stale, 90일 archive. pin·cron 참조 면제.
- 2단계 (OFF): aux 포크 LLM consolidate.
- 백업: tar.gz keep 5. 최대 조치는 archive. 삭제는 사용자/명시 purge.

NEOS 스킬 현실:
- `SkillManager.register_builtin_skills(use_auto_discovery=False)` — **수동 15종**.
- API: list/init/execute/prompt. create/patch/curate 없음.
- 코딩 에이전트: skill/memory import **0**.

## 4. 메모리 / 세션검색 / 유저모델 상세

- Hermes 넛지는 유저 메시지에 텍스트를 주입하지 않음. N번째 턴 종료 후 리뷰 프롬프트.
- 절차는 스킬, 전세션 사실만 메모리. 명령형 금지 (“Always respond concisely” → 이후 세션이 지시로 재해석).
- 크로스세션: SQLite FTS5, 원문 메시지 반환. LLM 없음.
- NEOS: `build_context` / `save_episode`는 워크플로 시작/성공 시. 에피소드는 응답 앞 500자. 챗 API는 MemoryManager를 안 부름.
- 유저 모델: Hermes USER.md ~500토큰. NEOS는 autonomy_level 0–2뿐.

## 5. 안전장치

| 위험 | Hermes가 하는 일 | 기본으로 막히나 | NEOS |
|---|---|---|---|
| 학습 스킬 프롬프트 인젝션 | `_SOURCE_HYGIENE`, `_DO_NOT_CAPTURE_BLOCK` | 프롬프트 수준. 스캐너는 OFF | 자동 학습 스킬 없음 |
| 악성 스킬 코드 | `skills_guard.scan_skill` | **생성 스캔 OFF** | 실행형 스킬은 더 위험 |
| 비밀 유출 | `/learn` author는 리터럴 `Hermes` | 관례 | 에피소드 스크럽 약함 |
| 무한 성장 | 메모리 하드 캡, curator archive | prune ON이면 완화 | 에피소드/임베딩 TTL 약함 |
| 백그라운드가 유저 스킬을 오염 | pin / user-owned / bundled 쓰기 거부 | ON (리뷰 경로) | — |
| 승인 없는 영속 쓰기 | `write_approval` 스테이징 | **OFF** | 코딩 도구 승인은 별 축 |
| 스킬 인라인 셸 | `run_inline_shell` | 로드 시 실행 | **가져오면 안 됨** |

**핵심**: Hermes 학습 루프는 기본적으로 **모델이 자기 대화를 읽고 파일을 씀**. 정적 검증·휴먼 게이트는 opt-in. 멀티테넌트 NEOS에 그대로 켜면 스킬 포이즈닝이 곧 테넌트 프롬프트 포이즈닝이다.

## 6. 갭과 병합 후보

NEOS는 **연구 플랫폼 + durable coding agent**다. Hermes식 “홈 디렉터리에 마크다운을 쌓는 개인 비서”를 통째로 이식하면 안 된다.

### P0 — 코딩 런에서 교훈 추출 (검증 게이트 필수)

- 코딩 루프는 이미 event log/checkpoint가 있다 (`038_`+). 반복 실패가 다음 런에 안 남는다.
- 붙일 곳: 런 종료 → Celery 후처리. 출력은 **유저/워크스페이스 스코프 markdown lesson**. 프로덕션 `neos/skills/builtin`에 쓰지 않음.
- 가져올 것: `_LESSON_LAYER_BLOCK` + `_DO_NOT_CAPTURE_BLOCK`. read-before-write.
- 작업량 M. 기본은 stage + 승인. 실행 스크립트 자동 생성 금지.

### P0 — `MemoryManager.learn()` 실제 배선

- LTM 테이블·플래그는 켜져 있는데 writer가 없다.
- 붙일 곳: (1) 챗 유저 교정 / Vote `feedback_category`, (2) refinement 소스 선호, (3) 워크플로 종료 시 구조화 fact.
- 작업량 S–M. 명령형 문장 필터 + 캡.

### P1 — 워크플로 / 딥리서치에서 절차 스킬

- 성공한 파이프라인(소스 순서, fetch 함정, 인용 규칙)이 에피소드 500자에만 남음.
- 클래스 레벨 문서만. 실행형 `skill.py` 자동 생성 금지.
- 인덱스는 시스템 프롬프트 60자 description. 본문은 on-demand.

### P1 — Curator를 Celery Beat에

- Hermes idle tick은 멀티워커 NEOS에 안 맞음.
- `neos/tasks/`에 `curate_learned_skills`. 1단계 결정론만. LLM consolidate는 플래그 OFF.
- bundled 15종·레포 `skills/`는 큐레이터 대상 제외. 테넌트별 네임스페이스.

### P1 — 세션 검색을 에이전트 도구로

- 기존 `message_embeddings` + conversations. FTS를 새로 깔기보다 hybrid.
- 검색 결과에 LLM 요약 층을 기본 넣지 말 것. `user_id` 강제.

### P2

- 스킬 usage sidecar → curator 입력
- `/learn` UX: 유저가 “이 절차를 스킬로” — 포그라운드 한 턴 + 스테이징
- `LLMCallCollector`를 스킬 추출 피처로 쓰는 실험은 연구 트랙으로 분리

## 7. 권장 구현 순서

1. 정책: 학습 아티팩트는 `org/user/workspace` 스코프, 기본 `write_approval=on`, bundled/레포 스킬 불변.
2. P0 `learn()` 배선.
3. P0 코딩 런 교훈 — 이벤트 로그 → staged lesson. 승인 전 다음 런에 안 넣음.
4. P1 연구 절차 스킬.
5. P1 Beat curator — prune-only.
6. P1 크로스세션 도구 — 임베딩 테이블 재사용.
7. 관측: 생성 수, 승인율, 이후 런 재사용률. 재사용 없는 자동 생성은 끈다.

코딩과 연구를 **한 전역 스킬 폴더**에 섞지 말 것.

## 8. 가져오면 안 되는 것

- Honcho 강결합
- 성격 / 펫
- 검증 없는 자동 프로덕션 스킬 배포 (`skill.py` 생성, builtin 핫로드)
- 리뷰 fail-open + write_approval OFF 조합
- 스킬 인라인 셸 전처리
- curator LLM consolidate 기본 ON
- README식 “session_search가 LLM 요약”을 스펙으로 복제
- learning graph를 코어 런타임에 넣기

## 9. 근거 파일 목록

Hermes: `README.md`, `agent/{learn_prompt,background_review,turn_finalizer,turn_context,turn_iteration_prep,agent_init,prompt_builder,curator,curator_backup,learning_graph,memory_manager,skill_preprocessing}.py`, `tools/{skill_manager_tool,skill_manager_guards,skill_usage,skills_guard,write_approval,session_search_tool}.py`, `hermes_state_fts.py`, `plugins/memory/honcho/`, `cli-config.yaml.example`.

NEOS: `neos/skills/manager/skill_manager.py`, `neos/memory/manager.py`, `neos/workflow/graph.py`, `neos/dataset/collector.py`, `neos/workflow/celery_app.py`, `db/migrations/{012,013,017,030,038}_*.sql`, `db/chat_similarity_search.sql`, `docs/ROADMAP.md`, `config/neos.default.yaml`, `skills/autoskill/`, `skills/skill-creator/`.
