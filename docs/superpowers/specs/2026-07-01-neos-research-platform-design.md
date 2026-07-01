# NEOS 개인 리서치 플랫폼 개선 설계

- 작성일: 2026-07-01
- 상태: 승인된 상위 제품·기술 설계
- 우선 사용자: 개인 리서처·기획자 → 개발자·운영자 → 기업 분석팀
- 범위: 프론트엔드, 백엔드, 데이터 계약, 사용자 경험, 신뢰성, 단계별 제품화

> 이 문서는 여러 릴리스를 포괄하는 상위 설계다. 하나의 구현 계획으로 실행하지 않는다. 단계 0~6은 각각 별도의 세부 설계, 구현 계획, 승인 기준을 갖는다. 첫 번째 구현 단위는 `단계 0: 신뢰성 기반`이며, 이후 단계는 선행 단계의 완료 조건을 통과한 뒤 시작한다.

## 1. 요약

NEOS는 일반적인 챗봇보다 훨씬 강한 연구 실행 엔진을 이미 갖고 있다. LangGraph 기반 멀티 에이전트 워크플로, Hyper Deep Research(HDR), 문서 처리, Research Harness, Evidence Graph, 실행 승인, A2UI, 아티팩트 및 다양한 내보내기 기능이 구현되어 있다.

현재 가장 큰 문제는 기능 부족이 아니다. 백엔드에 존재하는 기능이 하나의 일관된 사용자 경험과 안정적인 데이터 계약으로 연결되지 않는다. 사용자는 범용 채팅 화면을 보지만 내부적으로는 복잡하고 오래 걸리는 연구 워크플로가 실행된다. 첨부파일, 모델 선택, 스트리밍 재개, 아티팩트, 승인과 같은 기능 중 일부는 화면상 동작하는 것처럼 보이지만 실제 백엔드 실행과 불일치할 수 있다. 리소스 소유권 검증이 일관되지 않은 API도 있어 신규 기능보다 신뢰성·보안 기반을 먼저 완성해야 한다.

목표 제품은 세 개의 별도 도구가 아니라 하나의 `리서치 프로젝트`다.

- 조사 깊이: 빠른 조사 / 심층 조사
- 근거 범위: 웹 / 내 문서 / 웹+내 문서
- 결과물: 요약 / 비교표 / 의사결정 메모 / 구조화 보고서

문서 연구는 독립 모드가 아니라 모든 조사에서 사용할 수 있는 근거 범위다. 빠른 조사 결과는 같은 프로젝트 안에서 심층 조사로 확장할 수 있다. 프로젝트는 연구 목표, 문서, 웹 출처, 실행 이력, 근거, 반론, 보고서와 아티팩트를 함께 보존한다.

## 2. 현재 코드 분석

### 2.1 강점

현재 구현에서 유지하고 제품화해야 할 핵심 자산은 다음과 같다.

1. `neos/workflow/graph.py`의 분류·검색·분석·생성·검증·수리 파이프라인
2. `neos/agents/search_agents/hyper_deep_research/`의 대규모 자료 수집과 반복 개선
3. `neos/workflow/harness/`의 인용·출처·품질 검증과 repair loop
4. `neos/services/evidence_graph_service.py`와 관련 마이그레이션의 주장·근거·모순 모델
5. `neos/workflow/autonomy/`와 approval handler의 사람 개입 구조
6. 문서 파서, contextual retrieval, pgvector 기반 검색
7. OpenResponses 기반 스트리밍 및 reasoning/function call item 모델
8. 아티팩트, 인라인 시각화, A2UI를 위한 기본 렌더링 계층
9. Prometheus, OpenTelemetry, 비용 계산과 연구 평가 프레임워크

이 설계는 해당 기능을 재작성하지 않는다. 사용자 과업을 중심으로 실행 경계를 명확히 하고, 기존 엔진을 내구성 있는 Research Run 뒤에 배치한다.

### 2.2 사용자 경험의 주요 문제

#### 범용 채팅 템플릿에 머문 첫 화면

`web/components/greeting.tsx`는 한국어 인사를 표시하지만 `web/components/suggested-actions.tsx`의 추천 질문은 Next.js, Dijkstra, Silicon Valley, 샌프란시스코 날씨 같은 범용 예제다. NEOS의 핵심 가치인 근거 조사, 문서 분석, 비교·검증, 보고서 생성은 진입점에서 드러나지 않는다.

백엔드에는 연구 템플릿, 문서, 예약 작업, 연구 세션, 내보내기, Evidence Graph 등이 있지만 프론트엔드의 주요 탐색 구조는 새 채팅과 대화 기록에 한정되어 있다.

#### 사용자 과업보다 내부 설정이 앞선다

채팅 헤더는 공개 범위와 에이전트 자율성을, 입력창은 원시 모델 목록을 강조한다. 개인 리서처에게 먼저 필요한 선택은 모델 공급자가 아니라 조사 깊이, 근거 범위, 결과물 형식, 예상 시간과 비용이다. 모델과 세부 자율성은 고급 설정으로 이동해야 한다.

#### 언어와 접근성의 불일치

- 루트 HTML은 `lang="en"`이지만 첫 화면은 한국어다.
- 로그인, 추천 질문, 오류, 히스토리와 승인 UI가 한국어와 영어로 혼재한다.
- `maximumScale: 1`은 모바일 확대를 제한한다.
- 자율성 선택 버튼은 모바일에서 숨겨져 동일 기능에 접근하기 어렵다.
- 아이콘 전용 버튼의 일부는 명확한 접근성 이름이나 비활성화 사유가 없다.

### 2.3 프론트엔드·백엔드 계약 문제

#### 첨부파일이 실제 조사로 연결되지 않는다

`web/app/(chat)/api/files/upload/route.ts`는 `name`, `documentId`, `processingStatus`를 반환한다. `web/components/multimodal-input.tsx`는 응답에서 `pathname`을 읽으므로 파일명이 유실될 수 있다. 이후 `web/app/(chat)/api/chat/route.ts`는 메시지의 텍스트 part만 합치고 file part와 document ID를 백엔드 요청에서 제거한다.

결과적으로 업로드가 성공해 보이더라도 해당 문서가 현재 질문의 근거 범위로 전달되지 않는다. 문서 처리 완료 전 질문 실행에 대한 상태 처리도 없다.

#### 모델 선택과 실제 실행 모델이 다를 수 있다

`web/lib/ai/models.ts`는 여러 공급자 모델을 하드코딩한다. 대화 생성 후 모델을 변경해도 기존 백엔드 conversation의 `model_name`은 갱신되지 않는다. `neos/api/services/chat_stream_strategy.py`의 기본 전략은 항상 `generate_response_stream_with_tools()`를 선택하고, 해당 구현은 Anthropic SDK를 직접 사용한다. `ChatLLMService._extract_provider_from_model()`도 GPT와 Claude 외 모델을 기본 Anthropic으로 처리한다.

사용자가 Google·OpenAI·xAI 모델을 선택해도 실제 실행과 다르거나 실패할 수 있다. 서버가 사용 가능한 모델과 tool/reasoning/file 호환성을 제공하고 실행마다 확정 모델을 기록해야 한다.

#### 스트리밍 상태가 장기 연구를 감당하지 못한다

Next.js 채팅 route의 `maxDuration`은 60초지만 HDR 문서는 30~60분 실행을 설명한다. 백엔드가 `[DONE]`을 보내는데 프록시 flush도 `[DONE]`을 추가한다. 프론트엔드는 `response.completed`와 `[DONE]` 모두에서 완료 콜백을 실행할 수 있다.

`use-chat-stream.ts`는 요청 시작 시 상태를 `streaming`으로 두지만 입력 컴포넌트의 중지 버튼과 Thinking UI 일부는 `submitted` 상태를 기준으로 한다. 진행률 이벤트는 data stream으로 보내지만 사용자 화면에서는 의미 있게 소비되지 않는다. reasoning delta도 메시지 part로 복원되지 않는다.

`use-auto-resume.ts`의 resume는 기존 실행에 재연결하지 않고 마지막 사용자 메시지를 다시 전송한다. 네트워크 단절이나 재방문 시 중복 실행과 비용이 발생할 수 있다.

#### 히스토리와 메시지 복원이 불완전하다

프론트 히스토리 API는 `ending_before`를 받지 않고 항상 offset 0을 호출한다. 무한 스크롤이 첫 페이지를 반복할 수 있다. 백엔드 메시지를 UI 메시지로 변환할 때 content는 단일 text part로 축소되어 첨부, reasoning, tool call과 일부 상태가 유실된다.

메시지 편집과 regenerate도 원래 메시지 수정·분기·새 실행의 의미가 분명하지 않다. UI 상태와 DB 이력이 다르게 보일 수 있다.

#### 문서와 아티팩트 API 경로가 충돌한다

`document_handlers.py`와 `artifact_handlers.py`가 모두 `/documents/{document_id}`를 사용한다. 문서 route가 먼저 등록되므로 UUID 아티팩트 요청이 정수 document route에서 검증 실패할 수 있다. 파일 자산은 `/assets`, 생성형 결과물은 `/artifacts`로 분리해야 한다.

#### A2UI의 지원 범위가 문서와 다르다

백엔드 schema와 문서는 file upload, card, chart, table, progress, divider, button 등을 포함하지만 프론트 form은 일부 입력 컴포넌트만 렌더링한다. divider는 사전 필터링되어 switch에 도달하지 않고, 생성된 추가 button은 onClick이 연결되지 않아 동작하지 않는다. 완성되지 않은 타입은 생성 대상에서 제외하거나 명시적으로 지원해야 한다.

### 2.4 보안과 데이터 격리 문제

FastAPI의 스트리밍 채팅 엔드포인트에는 인증 의존성이 있지만 여러 chat CRUD, 문서 업로드·목록·상세·삭제·검색, 일반 query/history API에는 동일한 인증과 소유권 검증이 적용되지 않는다. 일부 API는 요청 body나 path의 `user_id`를 신뢰한다.

승인 API는 인증된 사용자를 받지만 `session_id`가 해당 사용자의 실행인지 검증하지 않는다. UI Frame submit도 frame 소유자를 확인하지 않는다. 리소스 ID를 아는 다른 사용자가 상태를 조회·수정하거나 실행을 승인할 위험이 있다.

백엔드는 BFF의 사전 확인에 의존하지 않고 모든 리소스 접근에서 `resource_id + current_user.user_id`를 강제해야 한다. public 공유는 별도의 share token 또는 명시적 ACL로 처리한다.

### 2.5 유지보수와 검증 문제

주요 파일이 지나치게 크다.

- `neos/workflow/graph.py`: 약 2,169줄
- `neos/api/handlers/chat_handlers.py`: 약 1,445줄
- `neos/agents/search_agents/hyper_deep_research/agent.py`: 약 1,689줄
- `web/hooks/use-chat-stream.ts`: 약 753줄
- `web/components/message.tsx`: 약 614줄

프론트에는 `components/elements`와 `components/ai-elements`에 유사 컴포넌트가 중복된다. 문서도 실제 코드와 차이가 있다. README가 존재하지 않는 문서를 링크하고, ROADMAP은 이미 구현된 기능을 미완료로 표시하며, `UI_REDESIGN.md`의 색상·폰트·경로는 현재 구현과 다르다.

검증 당시 TypeScript `tsc --noEmit`은 통과했고 프론트 소스 테스트 4개도 통과했다. 그러나 테스트는 테마와 일부 event type에 집중되어 있다. 선택한 모델과 실제 모델, 첨부→색인→인용, 사용자 간 접근 차단, SSE 재연결 같은 핵심 사용자 계약을 검증하지 않는다. 선택한 백엔드 테스트 묶음에서는 24개 통과, 1개 실패, 12개가 환경·누락 의존성으로 오류가 발생했다.

## 3. 고려한 제품 접근법

### 접근 A: 통합 리서치 프로젝트 — 채택

빠른 조사, 내 문서 조사, 심층 조사를 하나의 프로젝트와 공통 근거 모델로 제공한다. 사용자는 조사 깊이와 근거 범위를 조합하고 같은 결과를 확장한다.

장점:

- 기능 간 학습 비용과 데이터 중복이 적다.
- 빠른 조사에서 심층 조사로 자연스럽게 전환된다.
- 문서와 웹 근거를 동일한 Evidence 모델로 비교할 수 있다.
- 개발자 API도 동일한 Research Run 모델을 재사용한다.

단점:

- 초기 도메인 모델과 실행 상태 설계가 필요하다.
- 기존 chat 중심 API를 점진적으로 감싸야 한다.

### 접근 B: 빠른 조사·문서·HDR을 별도 제품으로 분리

각 기능을 별도 페이지와 API로 제공한다. 초기 화면 구현은 단순하지만 자료, 실행 상태, 보고서와 후속 질문이 세 군데로 나뉜다. 장기적으로 중복 구현과 사용자 혼란이 커져 채택하지 않는다.

### 접근 C: 기존 채팅을 유지하고 AI가 모든 모드를 자동 선택

개발 비용은 가장 낮지만 사용자는 예상 시간, 비용과 근거 범위를 통제하기 어렵다. 특히 HDR 자동 진입은 신뢰를 해칠 수 있다. 자동 추천은 제공하되 최종 실행 정책은 Research Brief에서 확인하도록 한다.

## 4. 제품 구조

### 4.1 핵심 개념

#### 조사 깊이

- `quick`: 제한된 시간과 출처 예산으로 결론·근거·권고안을 생성한다.
- `deep`: 다단계 계획, 대규모 수집, 교차 검증, Harness와 반복 개선을 수행한다.

심층 조사는 비동기 작업이며 실행 전 계획, 예상 시간과 예산을 확인한다.

#### 근거 범위

- `web`: 최신 웹·학술·도메인 소스를 사용한다.
- `documents`: 사용자가 선택한 프로젝트 문서만 사용한다.
- `combined`: 문서의 주장과 최신 웹 정보를 교차 검증한다.

문서가 선택되면 기본 추천은 `combined`이지만 사용자가 명시적으로 바꿀 수 있다.

#### 결과물

초기 지원 결과물은 다음으로 제한한다.

- 핵심 요약과 권고안
- 비교 분석표
- 의사결정 메모
- 구조화 연구 보고서

코드, 스프레드시트, 이미지 아티팩트는 결과물의 부속 자료로 유지한다.

### 4.2 정보 구조

전역 탐색:

1. 홈
2. 프로젝트
3. 문서 라이브러리
4. 실행 중인 조사
5. 설정

개발자 기능은 초기 개인 사용자 화면을 방해하지 않도록 설정 또는 별도 Developer 영역에 둔다. 팀, 조직, 감사 로그는 기업 단계에서 추가한다.

### 4.3 홈

홈은 범용 채팅 화면이 아니라 연구 시작점이다.

- “무엇을 조사할까요?” 입력
- 빠른 설정: 조사 깊이, 근거 범위, 결과물
- 최근 프로젝트
- 진행 중인 조사
- 최근 문서
- 시장 조사, 문헌 검토, 기술 비교, 제품 비교 템플릿

모델 공급자 선택은 기본 화면에서 숨긴다. 고급 설정에서만 자동 선택을 해제할 수 있다.

### 4.4 Research Brief

실행 전 NEOS가 이해한 내용을 구조화해 보여준다.

- 핵심 목표와 질문
- 포함·제외 범위
- 선택 자료와 사용할 소스 유형
- 조사 깊이와 예상 단계
- 예상 시간과 비용 범위
- 결과물 형식
- 불확실한 요구사항

빠른 조사는 사용자가 설정한 정책에 따라 즉시 실행할 수 있다. 심층 조사는 항상 brief 확인을 요구한다. 자동 실행 설정을 켜더라도 예산 상한과 허용 작업 범위를 넘으면 승인을 요청한다.

### 4.5 리서치 워크스페이스

워크스페이스는 세 영역으로 구성하지만 작은 화면에서는 drawer/tab으로 전환한다.

1. 프로젝트 자료
   - 업로드 문서
   - 저장 URL
   - 자료별 처리 상태
   - 현재 run에 포함할 자료 선택
2. 조사·보고서 본문
   - Research Brief
   - 연구 계획
   - 진행 타임라인
   - 요약·보고서
   - 후속 질문
3. 근거 패널
   - 인라인 인용과 원문
   - 주장별 출처
   - 출처 신뢰도·최신성
   - 반론과 모순
   - Harness 결과의 사용자용 설명

### 4.6 실행 중 경험

내부 노드명 대신 사용자 의미 단계를 표시한다.

1. 질문과 범위 정리
2. 자료 수집
3. 출처 평가
4. 주장·반론 비교
5. 사실·인용 검증
6. 보고서 작성

표시 항목:

- 전체 및 현재 단계 진행률
- 경과 시간과 예상 잔여 범위
- 수집·채택·제외 출처 수
- 현재 비용과 예산 상한
- 일시정지, 취소, 범위 수정

사용자는 페이지를 닫아도 작업을 계속할 수 있고 동일 run에 재접속한다. 재접속은 메시지 재전송이 아니다.

### 4.7 결과 검토

결과는 세 층으로 제공한다.

1. 결론: 핵심 인사이트, 권고안, 중요한 불확실성
2. 보고서: 구조화 본문, 표와 시각화, 인라인 인용
3. 근거: 주장별 출처·반론·모순·검증 상태

내부 Harness 점수만 노출하지 않는다. 다음과 같이 해석 가능한 언어로 변환한다.

- 출처 다양성 양호
- 최신 자료가 부족함
- 핵심 주장 두 개의 근거가 약함
- 두 신뢰도 높은 출처가 상충함
- 인용 위치 검증 완료

빠른 조사 결과에는 `심층 조사로 확장` 동작을 제공한다. 기존 brief, 문서, 출처와 후속 질문을 그대로 가져간다.

### 4.8 문서 경험

문서 상태는 사용자에게 보이는 상태 머신으로 관리한다.

`uploading → stored → extracting → indexing → ready` 또는 `failed`

- 질문에는 `ready` 문서만 기본 포함한다.
- 처리 중 질문을 보내면 기다릴지, 준비된 자료로 먼저 실행할지 선택한다.
- 인용은 document ID, 버전, 페이지, chunk와 원문 범위를 포함한다.
- 파일 삭제는 저장 객체, chunk, embedding, 검색 색인과 파생 Evidence의 보존 정책을 함께 처리한다.
- 프로젝트에서 제거하는 것과 영구 삭제를 구분한다.

## 5. 도메인과 데이터 모델

### 5.1 Project

- `project_id`
- `owner_user_id`
- `title`, `description`
- `default_language`
- `default_depth`, `default_evidence_scope`
- `created_at`, `updated_at`, `archived_at`

### 5.2 Asset

- `asset_id`
- `owner_user_id`, `project_id`
- `kind`: document / url / note
- `filename`, `mime_type`, `size`, `checksum`
- `storage_key`
- `processing_status`, `processing_error_code`
- `version`, `created_at`, `ready_at`

물리 파일과 생성형 artifact를 같은 route에서 처리하지 않는다. Asset은 입력 자료, Artifact/Deliverable은 출력 결과다.

### 5.3 ResearchBrief

- `brief_id`, `project_id`
- `question`, `objective`
- `in_scope`, `out_of_scope`
- `depth`: quick / deep
- `evidence_scope`: web / documents / combined
- `selected_asset_ids`
- `deliverable_type`
- `language`
- `budget_limit`, `time_limit`
- `version`, `confirmed_at`

### 5.4 ResearchRun

- `run_id`, `project_id`, `brief_id`, `owner_user_id`
- `status`
- `current_phase`, `progress_percent`
- `selected_model`, `selected_provider`, `capability_snapshot`
- `budget_limit`, `cost_so_far`
- `started_at`, `last_event_at`, `completed_at`
- `error_code`, `error_phase`, `retryable`
- `idempotency_key`
- `parent_run_id`: 빠른 조사에서 심층 조사로 확장한 계보

상태:

`draft → planned → queued → running → waiting_input/waiting_approval/paused → completed/partially_completed/failed/canceled`

### 5.5 Evidence

기존 Evidence Graph를 확장하거나 adapter로 연결한다.

- claim
- supporting/opposing source
- source version과 인용 위치
- relevance, reliability, freshness
- contradiction group과 resolution
- verification status
- 생성한 run과 최종 deliverable 연결

### 5.6 Deliverable

- `deliverable_id`, `project_id`, `run_id`
- `kind`
- `title`, `content`, `structured_content`
- `version`, `status`
- `citation_manifest`
- `created_at`, `updated_at`

## 6. 목표 기술 아키텍처

```text
Web Client
    │
Next.js BFF — 세션 변환, SSR, same-origin proxy
    │
FastAPI — 인증, 권한, 요청 검증, 도메인 API
    ├── Project / Asset / Research Run / Evidence / Deliverable modules
    ├── PostgreSQL — 상태·이벤트·권한·결과
    ├── Object Storage — 원본 문서·내보내기
    ├── Queue — Celery/Ray worker 실행
    └── Event Stream — 저장 이벤트 + SSE 재전송
             │
       Existing NEOS Workflow adapters
       ├── Quick research workflow
       ├── Document retrieval
       └── HDR / recursive / harness workflow
```

초기에는 마이크로서비스로 분리하지 않는다. FastAPI 내부의 명확한 모듈 경계와 worker 경계를 먼저 만든다. 독립 확장이 실제로 필요한 처리만 queue worker로 분리한다.

### 6.1 Research Run 실행 원칙

빠른 조사와 심층 조사 모두 Research Run을 생성한다. 빠른 조사는 짧게 끝날 수 있지만 동일한 저장·이벤트·재시도 모델을 사용한다. 이렇게 해야 두 실행 방식의 UX와 관측이 갈라지지 않는다.

실행 요청은 즉시 `run_id`를 반환한다. worker가 실행을 시작하면 phase event를 DB 또는 내구성 있는 event store에 기록한다. SSE는 실시간 전달 수단일 뿐 진실의 원천이 아니다.

### 6.2 이벤트 모델

최소 이벤트:

- `run.created`, `run.queued`, `run.started`
- `phase.started`, `phase.progress`, `phase.completed`, `phase.failed`
- `source.discovered`, `source.accepted`, `source.rejected`
- `approval.requested`, `approval.resolved`
- `artifact.updated`
- `run.paused`, `run.resumed`, `run.canceled`
- `run.completed`, `run.partially_completed`, `run.failed`

모든 이벤트는 `event_id`, `run_id`, `sequence`, `occurred_at`, `schema_version`을 가진다. 클라이언트는 마지막 event ID를 저장하고 재연결 시 `Last-Event-ID`를 보낸다.

OpenResponses는 LLM output item의 표준으로 유지한다. Research Run lifecycle event와 LLM content event의 역할을 구분하고 명시적으로 버전 관리한다. legacy adapter는 마이그레이션 기간 후 제거한다.

### 6.3 모델 capability registry

프론트 하드코딩 대신 서버가 다음을 제공한다.

- 활성 공급자와 모델
- tool calling, reasoning, vision, file 지원 여부
- context/output 한도
- 비용 등급과 권장 용도
- 현재 가용성

자동 선택은 brief와 capability를 기반으로 한다. 사용자가 수동 선택하면 실행 전 호환성을 검증한다. 실제 선택 모델과 fallback 이력은 Research Run에 저장하고 결과 화면에 확인 가능하게 한다.

## 7. API 설계

핵심 route의 예시는 다음과 같다.

- `POST /api/v1/projects`
- `GET /api/v1/projects/{project_id}`
- `POST /api/v1/projects/{project_id}/assets`
- `GET /api/v1/assets/{asset_id}`
- `DELETE /api/v1/assets/{asset_id}`
- `POST /api/v1/projects/{project_id}/briefs`
- `POST /api/v1/research-runs`
- `GET /api/v1/research-runs/{run_id}`
- `GET /api/v1/research-runs/{run_id}/events`
- `POST /api/v1/research-runs/{run_id}/pause`
- `POST /api/v1/research-runs/{run_id}/resume`
- `POST /api/v1/research-runs/{run_id}/cancel`
- `POST /api/v1/research-runs/{run_id}/approvals/{approval_id}`
- `GET /api/v1/research-runs/{run_id}/evidence`
- `GET /api/v1/projects/{project_id}/deliverables`
- `GET /api/v1/capabilities`

모든 mutation은 idempotency key를 지원한다. 모든 project-scoped route는 서버에서 소유권 또는 ACL을 검사한다. 사용자가 path/body에 임의 user ID를 넣어 권한을 결정하지 않는다.

API 오류는 RFC 9457 Problem Details 형식으로 통일한다.

- 안정적인 `type`, `code`
- 사용자용 `title`, `detail`
- `request_id`, `run_id`
- `retryable`, `retry_after`
- 필드 검증 오류

내부 예외 문자열과 stack 정보는 사용자 응답에 직접 노출하지 않는다.

## 8. 프론트엔드 구조

### 8.1 상태 분리

- 서버 상태: Project, Asset, Run, Evidence, Deliverable query cache
- 로컬 UI 상태: panel open, draft 입력, 선택 상태
- 스트림 상태: event reducer가 서버 이벤트를 query cache에 투영

`use-chat-stream.ts`의 단일 대형 hook을 다음으로 분리한다.

- SSE transport와 reconnect
- event parser와 schema validation
- run state reducer
- message/output item reducer
- artifact/evidence handlers
- mutation actions

스트림에서 수신한 객체를 직접 변형하지 않고 reducer와 immutable update를 사용한다. 완료·실패·취소는 중복 이벤트에도 안전해야 한다.

### 8.2 메시지 저장

단일 text 필드로 축소하지 않고 content part를 저장한다.

- text
- reasoning summary
- file/document reference
- function/tool call
- citation/evidence reference
- UI frame
- artifact reference

원시 비공개 reasoning은 저장·표시 정책을 별도로 적용한다. 사용자에게는 필요한 경우 요약된 reasoning 또는 실행 계획만 보여준다.

### 8.3 국제화와 접근성

- 한국어와 영어 message catalog 도입
- 프로젝트 언어에 맞는 `lang` 설정
- 모바일 확대 허용
- 모든 아이콘 버튼에 accessible name과 tooltip
- 키보드만으로 brief 확인, 실행, 승인, evidence 탐색 가능
- `prefers-reduced-motion` 지원
- 모바일에서 조사 설정과 승인 기능을 숨기지 않음

## 9. 오류 처리와 복구

오류는 실패한 응답이 아니라 Research Run의 영구 상태다.

- 실패 단계, 사용자용 원인, 해결 방법을 저장한다.
- 완료된 자료 수집과 중간 결과는 보존한다.
- 전체 run이 아니라 실패 phase부터 재시도한다.
- provider 장애 시 대체 모델의 품질·비용 차이를 알린다.
- 문서별 실패 원인과 재처리 동작을 제공한다.
- 승인 대기, 만료, 거절을 구분한다.
- `partially_completed` 결과를 열람·내보낼 수 있다.

예: “42개 출처 수집과 31개 채택은 완료됐지만 인용 검증 단계가 실패했습니다. 검증 단계만 다시 실행할 수 있습니다.”

비용이 발생하는 재시도는 예상 추가 비용을 표시한다. 브라우저 재연결은 재실행을 일으키지 않는다.

## 10. 보안과 프라이버시

### 필수 원칙

1. 인증은 모든 비공개 route에서 필수다.
2. 서비스와 repository 계층 모두 owner/ACL scope를 받는다.
3. Project, Asset, Run, Approval, UI Frame, Artifact에 교차 사용자 테스트를 둔다.
4. public 공유는 원본 ID만으로 접근하지 않고 취소 가능한 share token을 사용한다.
5. 문서 storage URL은 짧은 만료 signed URL을 사용한다.
6. 로그에서 문서 본문, query와 token을 기본 마스킹한다.
7. `/metrics`, `/info` 등 운영 endpoint는 내부 네트워크 또는 관리자 권한으로 제한한다.
8. 삭제 시 파생 chunk, embedding, cache와 retention 기록을 처리한다.

현재 gateway 모드에서 trusted IP 목록이 비어 있을 때 모든 IP를 신뢰하는 설정은 운영 환경에서 시작 실패 또는 강한 경고 대상으로 바꾼다.

## 11. 테스트와 평가

### 11.1 계약 테스트

- OpenAPI에서 TypeScript 타입·클라이언트 생성
- backend schema와 frontend event schema의 golden test
- capability response와 모델 라우팅 일치
- attachment/document reference round-trip

### 11.2 보안 테스트

- 사용자 A가 사용자 B의 Project, Asset, Run, Approval, Artifact에 접근 불가
- public share token의 scope, 만료, 취소
- body/path user ID 조작 방어
- 문서 삭제 후 signed URL과 검색 결과 접근 차단

### 11.3 실행·스트림 테스트

- 같은 idempotency key는 run 하나만 생성
- 연결 단절 후 event sequence부터 재개
- 중복·순서 역전 이벤트에 reducer가 안전
- worker 재시작 후 queued/running run 복구
- pause/cancel/approval timeout
- 부분 실패 후 phase 재시도

### 11.4 사용자 E2E

1. 웹 빠른 조사 → 근거 열람 → 보고서 저장
2. PDF 업로드 → ready 확인 → 문서 전용 질문 → 페이지 인용 이동
3. 문서+웹 교차 검증 → 모순 확인
4. 빠른 조사 → 심층 조사 확장
5. 심층 조사 페이지 이탈 → 재방문 → 동일 run 재개
6. 승인 요청 → 승인/거절 → 결과 상태 확인
7. 모바일과 키보드 탐색

### 11.5 연구 평가

기존 `neos_evals`와 runtime Harness를 실제 제품 run에 연결한다.

- 사실 정확도
- 인용 정확도와 원문 entailment
- 출처 다양성·신뢰도·최신성
- 문서 grounding 정확도
- 반대 관점 포함 여부
- 보고서 완성도와 권고안 유용성
- latency와 성공한 조사당 비용

한국어 개인 리서처 시나리오를 회귀 데이터셋에 포함한다. 모델·prompt·검색 변경은 동일 task의 품질, 일관성, 비용을 비교한 뒤 배포한다.

## 12. 제품 지표

핵심 지표:

- 검증된 첫 인사이트까지 걸린 시간
- 빠른/심층 조사 완료율
- 중단 후 재개 성공률
- 인용 출처 열람률
- 문서 근거 정확도
- 사용자 수정 없이 채택된 보고서 비율
- 빠른 조사에서 심층 조사로 확장한 비율
- 성공한 조사당 비용
- 오류 후 복구 성공률

메시지 수나 단순 실행 횟수는 보조 지표로만 사용한다.

## 13. 단계별 로드맵

로드맵은 기간이 아니라 완료 조건으로 관리한다. 팀 규모와 운영 환경이 확정되기 전에는 인위적인 날짜를 약속하지 않는다.

각 단계는 독립된 sub-project다. 데이터베이스 마이그레이션, API 호환 정책, 테스트, rollout·rollback 계획을 포함한 별도 세부 spec을 작성한다. 여러 단계를 한 번에 구현하거나 하나의 대형 PR로 묶지 않는다.

### 단계 0: 신뢰성 기반

- 모든 리소스 인증·소유권 검증
- 문서와 아티팩트 route 분리
- 첨부 업로드·document ID·chat request 계약 수정
- 실제 실행 모델과 UI 선택 일치
- 히스토리 cursor pagination
- 메시지 content part 보존
- 스트림 상태·중지·완료 중복 수정
- A2UI 미지원 타입 비활성화 또는 구현
- 해당 회귀·교차 사용자 테스트

완료 조건: 화면에서 성공으로 보인 핵심 동작이 백엔드와 일치하고, 다른 사용자의 비공개 리소스에 접근할 수 없다.

단계 0도 다음 순서의 작은 작업 묶음으로 분해한다.

1. 리소스 인증·소유권과 교차 사용자 회귀 테스트
2. `/assets`와 `/artifacts` route 및 호환 adapter
3. 첨부 업로드→문서 준비→질문 참조 계약
4. capability 기반 모델 선택과 실제 실행 기록
5. 스트림 상태·중복 완료·재접속·히스토리 pagination
6. content part 영속화와 A2UI 지원 범위 정합성

각 묶음은 기존 클라이언트와 API의 호환 전략을 먼저 확정한 뒤 구현한다.

### 단계 1: 프로젝트와 문서 라이브러리

- Project, Asset, ResearchBrief 모델
- 프로젝트 홈과 자료 panel
- 문서 처리 상태와 재처리
- 프로젝트별 문서 선택
- 페이지·chunk citation manifest

완료 조건: 사용자가 프로젝트를 만들고 문서를 올린 뒤 선택 문서만으로 근거가 추적되는 답변을 얻는다.

### 단계 2: 빠른 조사

- Research Brief 확인
- Quick Research Run
- 사용자 의미의 phase progress
- 결론·보고서·근거 패널
- 결과 저장과 후속 질문

완료 조건: 대표 개인 리서치 task에서 제한된 시간·비용 안에 인용 가능한 의사결정 자료를 만든다.

### 단계 3: 심층 조사

- HDR의 내구성 있는 background run 전환
- 이벤트 저장과 SSE resume
- pause/cancel/approval/partial result
- quick run에서 deep run 확장
- Harness 결과의 사용자용 설명

완료 조건: 브라우저·서버 연결이 끊겨도 연구가 중복되지 않고 완료 또는 명시적 부분 완료 상태로 복구된다.

### 단계 4: 결과물 제작

- 보고서 편집과 버전 관리
- Evidence를 유지하는 PDF, DOCX, Markdown 내보내기
- 표·다이어그램·프레젠테이션 결과물
- citation manifest 포함

완료 조건: 사용자가 외부 업무에 바로 사용할 수 있는 결과물을 출처 추적과 함께 내보낸다.

### 단계 5: 개발자 경험

- Research Run API와 SDK
- webhook
- workflow template
- capability discovery
- 실행 로그와 비용 정보

완료 조건: 개발자가 채팅 UI 없이도 동일한 project/run/evidence 모델로 연구를 자동화한다.

### 단계 6: 기업 기능

- 팀 워크스페이스
- 역할·리소스 권한
- 감사 로그
- 데이터 보존·리전·프라이버시 정책
- 조직 단위 사용량과 예산

완료 조건: 팀이 공유 프로젝트를 운영하면서 누가 어떤 자료와 실행에 접근·승인했는지 감사할 수 있다.

## 14. 비목표

초기 개인 사용자 단계에서는 다음을 만들지 않는다.

- 독립적인 세 개의 연구 제품
- 모든 A2UI component type
- 일반 사용자를 위한 원시 workflow builder
- 플러그인 marketplace
- 실시간 다중 사용자 공동 편집
- 모든 모델 공급자의 완전한 동일 기능 지원
- 자동으로 무제한 HDR을 시작하는 라우팅

이 항목은 핵심 사용자 여정과 신뢰성 기반이 검증된 후 재평가한다.

## 15. 주요 위험과 대응

### 기능 범위가 다시 넓어질 위험

대응: Project/Asset/Run/Evidence/Deliverable에 직접 기여하지 않는 신규 기능은 후순위로 둔다.

### 기존 workflow와 새 run 모델이 이중 상태를 만드는 위험

대응: Research Run을 외부 lifecycle의 진실 원천으로 두고 기존 AgentState는 실행 내부 상태로 한정한다. adapter가 둘 사이를 변환한다.

### 깊은 조사의 시간·비용 예측이 부정확한 위험

대응: 범위 추정치를 구간으로 표시하고 hard budget, source cap, phase별 비용 기록을 적용한다.

### 품질 점수가 사용자 신뢰로 이어지지 않는 위험

대응: 내부 점수보다 약한 주장, 상충 출처, 최신성 부족과 실제 인용 원문을 보여준다.

### 문서와 웹 자료의 데이터 프라이버시 위험

대응: 프로젝트별 ACL, signed URL, 검색 tenant scope, 삭제 전파와 로그 마스킹을 기본값으로 한다.

## 16. 전체 승인 기준

다음 조건을 만족하면 통합 리서치 플랫폼의 1차 설계 목표를 달성한 것으로 본다.

1. 개인 사용자가 프로젝트 안에서 웹, 문서 또는 결합 근거를 선택할 수 있다.
2. 빠른 조사와 심층 조사가 동일한 Research Run·Evidence·Deliverable 모델을 사용한다.
3. 빠른 조사 결과를 입력 손실 없이 심층 조사로 확장할 수 있다.
4. 장기 실행이 브라우저 연결과 분리되고 안전하게 재개된다.
5. 모든 비공개 리소스가 백엔드 소유권 검증을 통과한다.
6. 선택 모델, 첨부 자료, 실행 상태와 화면 표시가 실제 백엔드 동작과 일치한다.
7. 결과의 핵심 주장에 원문 위치가 있는 근거 또는 명시적 불확실성이 표시된다.
8. 실패 시 완료된 작업을 보존하고 실패 단계부터 재시도할 수 있다.
9. 핵심 흐름이 계약·보안·스트림·E2E·연구 평가 테스트로 보호된다.
10. 개발자 API와 이후 팀 기능이 같은 도메인 모델 위에 확장될 수 있다.
