# NEOS 프론트엔드 감사 보고서 (2026-07-17)

**대상:** `web/` (Next.js 16 + React 19, `neos-web` v0.23.0, TS/TSX 202개)
**방법:** 백엔드 라우터 정의(`neos/main.py`, `neos/api/`)와 프론트 호출 지점을 코드로 직접 대조.
모든 주장에 `파일:줄` 근거를 붙였다. 확인하지 못한 항목은 **미확인**으로 명시했다.

> **선행 문서 정정 — `docs/FE_REVIEW_260302.md`는 낡았다.**
> 3월 문서의 핵심 주장인 "FE가 Vercel AI Gateway로 백엔드를 우회한다"는 **현재 사실이 아니다.**
> `web/app/(chat)/api/chat/route.ts:112`는 `callBackendAPI`로 백엔드 `/api/v1/chat/.../messages/stream`을
> 호출하며, auth·conversations·messages·documents·votes 전부 백엔드를 경유한다(§2 표 참조).
> 다만 Gateway 시절 잔재는 남아 있다 — `web/components/chat.tsx:105`의
> `error.message?.includes("AI Gateway requires a valid credit card")` 분기는 도달 불가능한 죽은 코드다.
> 3월 문서의 "SSE(FE) vs WebSocket(BE) 불일치"도 현재는 해당 없다. 백엔드가 SSE
> (`neos/api/handlers/chat_handlers.py:710`)를 제공하고 FE가 SSE로 소비한다. WebSocket 라우트
> (`chat_handlers.py:1361`, `workflow_stream_handlers.py:610`)는 FE가 쓰지 않을 뿐 불일치는 아니다.

---

## 1. 요약 — 가장 심각한 문제 5개

> **상태 갱신 (2026-07-17, 감사 작성 이후):** 5개 중 4개가 이미 수정됐다.
> `심각도`는 감사 시점의 원래 평가이며, `상태`는 코드 재확인 결과다.
> 상태 표시를 붙인 곳은 **아래 표 / §3.1 / §3.2 / §3.3 / §3.4 / §4.1 / §4.2 / §7 표(2·3·4·5·7행)** 뿐이다 —
> 나머지 항목은 재확인하지 않았으므로 **상태 미확인**이다(✅가 없다고 해서 미해결이라는 뜻이 아니다).
> 각 절의 원래 분석은 기록으로 그대로 보존했다.
>
> ⚠️ **§7 4행의 권고 하나를 정정했다.** 원문은 "백엔드 double-prefix 제거(권장)"였으나
> 이는 아티팩트 라우터를 깨뜨리는 잘못된 처방이다. 상세는 §3.1과 `web/lib/backend-routes.ts` 참조.

| # | 심각도 | 상태 | 문제 | 핵심 근거 |
|---|---|---|---|---|
| 1 | 🔴 | ✅ 해결됨 | **파일 첨부 기능이 완전히 동작하지 않는다.** 업로드 경로가 존재하지 않는 URL을 친다(백엔드 double-prefix). 설령 성공해도 채팅 라우트가 첨부를 버린다 | `web/app/(chat)/api/files/upload/route.ts:87` vs `neos/main.py:532` + `neos/api/handlers/document_handlers.py:34` / `web/app/(chat)/api/chat/route.ts:51-54` |
| 2 | 🔴 | ✅ 해결됨 | **리프레시 토큰 회전 파괴 → 예기치 않은 강제 로그아웃.** 백엔드는 1회용 토큰인데 FE가 회전된 새 리프레시 토큰을 버린다 | `web/lib/backend-api.ts:101-102` vs `neos/api/services/auth_service.py:209,226` |
| 3 | 🔴 | ✅ 해결됨 | **`autoResume`가 "재개"가 아니라 "재실행"이다.** 중단된 대화를 새로고침하면 워크플로우 전체가 재과금 실행된다 | `web/hooks/use-auto-resume.ts:30-31` + `web/hooks/use-chat-stream.ts:734-742` + `web/app/(chat)/chat/[id]/page.tsx:71` |
| 4 | 🟡 | ✅ 해결됨 | **정지(Stop) 버튼이 에러 토스트를 띄운다.** abort가 에러로 처리되고, 이를 거르는 코드는 도달 불가 | `web/hooks/use-chat-stream.ts:592-597` vs `:665-675` |
| 5 | 🟡 | ✅ 코드 완료 (라이브 검증 대기) | **사이드바 대화 목록 페이지네이션이 깨져 있다.** `ending_before`를 무시하고 항상 `offset=0` → 같은 페이지 무한 반복 | `web/app/(chat)/api/history/route.ts:20` vs `web/components/sidebar-history.tsx:97` |

**top-5 이슈 전부 코드 수정 완료.** #5(§3.4)는 keyset 커서 페이지네이션으로 교체했고(§3.4 참조),
자동화 테스트는 모두 통과한다. 다만 실제 Postgres에서의 keyset 정확성(페이지 겹침/누락 없음)은
라이브 스택 검증이 남아 있어 아직 완전 ✅로 표기하지 않는다 — 아래 §3.4의 검증 체크리스트 참조.

---

## 2. 미사용 백엔드 기능

`neos/main.py:516-557`에 등록된 라우터 전체를 FE 호출 지점(`callBackendAPI` / `fetch(backendUrl…)`)과 대조했다.

### 2.1 먼저 — 과제 지시서의 "알려진 후보" 중 **3개는 실제로 사용 중**이다

지시서가 미사용 후보로 지목한 `approval`, `autonomy`, `ui_submit(A2UI)`는 **이미 연동돼 있다.**

| 기능 | 백엔드 | 프론트 |
|---|---|---|
| approval | `approval_handlers.py:92,238` → `/api/v1/approval/respond`, `/approval/stream/{session_id}` | `web/app/(chat)/api/approval/respond/route.ts:7`, `web/app/(chat)/api/approval/stream/[sessionId]/route.ts` |
| autonomy | `autonomy_handlers.py:32,46` → `/api/v1/autonomy/preference` | `web/app/(chat)/api/autonomy-preference/route.ts:6,16` + `components/agent-autonomy-selector.tsx` |
| ui_submit (A2UI) | `ui_submit_handlers.py:52` → `/api/v1/ui/submit` | `web/lib/backend-api.ts:173`, `web/components/ui-frame/UIFrameForm.tsx:83` |

harness 진행 UI도 존재한다(`web/components/harness-status.tsx`) — 단 전용 API가 아니라 채팅 SSE의
`neos:harness` 이벤트로만 공급된다(`web/hooks/use-chat-stream.ts:501-518`).

### 2.2 실제 미사용 목록

| 기능 | 백엔드 엔드포인트 | 프론트 사용 | 판단 |
|---|---|---|---|
| **deep-research** | `deep_research_handlers.py:1027,1138,1196,1246` → `/api/v1/deep-research/start`, `/{report_id}/stream`, `/{report_id}`, `/conversations/{id}/deep-research` | ❌ 전무 | **누락.** FE에 UI·호출 모두 없음. 백엔드는 SSE 스트림까지 완비. 가장 큰 미연동 자산 |
| **deep-analysis (하네스)** | `deep_analysis_handlers.py:48` → `POST /api/v1/deep-analysis` (인라인 SSE) | ❌ 전무 | **의도적(현 시점).** 채팅 그래프 노드 경유로만 도달. §5.4가 이 구조를 바꾼다 → §6 참조 |
| **deep_analysis_analytics** | `deep_analysis_analytics_handlers.py:23` → `/api/v1/deep-analysis/analytics` | ❌ | **의도적 추정.** 운영 분석용. 단 admin 게이트는 없음(일반 사용자 접근 가능) — 미확인 리스크 |
| **skills** | `skills_handlers.py:60-311` (9개) | ❌ | **의도적.** `neos/main.py:542`에서 `get_current_admin_user` 게이트. 챗 FE 대상 아님. (부수 발견: 실제 경로가 `/api/v1/skills/skills` — §3.6) |
| **multimodal** | `multimodal_handlers.py:23,118,193,213` → `/api/v1/multimodal/query`, `/image/analyze` 등 | ❌ | **누락.** FE는 이미지 첨부 UI를 갖고 있으나(§3.1) 멀티모달 API를 쓰지 않음. 첨부 파이프라인이 죽어 있는 것과 동일 원인 |
| **export** | `export_handlers.py:22` → `/api/v1/research/{session_id}/export` | ❌ | **누락.** research session 자체가 미연동이라 종속적으로 미사용 |
| **template** | `template_handlers.py:65,95` → `/api/v1/research/templates` | ❌ | **누락** |
| **refinement** | `refinement_handlers.py:27-118` (5개) → `/api/v1/research/refine/*` | ❌ | **누락.** FE의 `refine` 매칭은 zod `.refine()` 오탐 |
| **research_session** | `research_session_handlers.py:77-149` (5개) → `/api/v1/research/sessions/*` | ❌ | **누락** |
| **async_research** | `async_research_handlers.py:66,132,165` → `/api/v1/research/async`, `/async/{job_id}/status`, `/stream/{session_id}` | ❌ | **누락 — 그러나 §5.4의 참고 구현.** 이미 job 핸들 + 상태 폴링 + 스트림 3종 세트가 존재 |
| **scheduled_tasks** | `scheduled_tasks_handlers.py:80-225` (5개) → `/api/v1/scheduled-tasks/*` | ❌ | **누락.** Cron 스킬 백엔드는 완비, FE 진입점 없음 |
| **trending / related / history / stats** | `query_handlers.py:94,107,117,145` | ❌ | **누락** |
| **hyper-research 리포트** | `query_handlers.py:226,251` → `/api/v1/hyper-research`, `/{report_uuid}` | ❌ | **누락** |
| **unified** | `unified_handlers.py:76,144,217,305,373` → `/api/v1/unified/*` | ❌ | **의도적 추정.** 챗 경로와 기능 중복 |
| **similarity chat** | `similarity_chat_handlers.py:56-377` (6개) | ❌ | **의도적 추정.** 표준 챗 경로가 대체 |
| **votes/feedback** | `vote_handlers.py:82,106` → `/api/v1/votes/feedback`, `/feedback/aggregation` | ❌ | **누락.** `/votes` 본체는 사용 중(`web/app/(chat)/api/vote/route.ts`)이나 feedback 하위만 미사용 |
| **chat analytics/statistics/templates** | `chat_handlers.py:1246,1265,1284,1311,1329` | ❌ | **누락** |
| **auth 부가 기능** | `auth.py:203,219,266,284,391,420` → `/me`, `/api-keys`(3), `/oauth/{provider}/unlink`, `/oauth/accounts` | ❌ | **누락.** 계정 설정 UI 부재. `/logout`(`auth.py:184`) 미호출은 🟡 — 로그아웃해도 백엔드 리프레시 토큰이 살아 있음 |
| **web search analytics** | `analytics_handlers.py` (11개) | ❌ | **의도적.** `neos/main.py:529` admin 게이트 |
| **workflow stream** | `workflow_stream_handlers.py:452,610,763` → `/api/v1/query/stream`, WS 2종 | ❌ | **의도적 추정.** 챗 SSE가 대체 |
| **document (RAG)** | `document_handlers.py:37-273` (7개) | ⚠️ upload만 시도, **실패** | **버그.** §3.1 |

**요약:** 백엔드 25개 핸들러 중 FE가 실제로 쓰는 것은 **auth / chat / votes / artifact(documents) / approval / autonomy / ui_submit 7계열**뿐이다.
research 계열(deep-research, session, export, template, refinement, async) **전체가 미연동**이며, 이것이 가장 큰 자산 낭비다.

---

## 3. FE↔BE 계약 불일치

### 3.1 ✅ 해결됨 (2026-07-17) — 파일 업로드 경로가 존재하지 않는다 (double-prefix)

> **해결:** FE가 실제 경로(`/api/v1/documents/documents`)를 호출하도록 고쳤다.
> 경로 상수는 `web/lib/backend-routes.ts`에 모으고 근거를 주석으로 남겼다
> (`RAG_DOCUMENT_UPLOAD_PATH`, `ragDocumentPath()`).
> 호출 지점: `web/app/(chat)/api/files/upload/route.ts:84,111`.
> 회귀 방지: `web/tests/source/backend-routes.test.ts`가 상수를 못박는다.
> 백엔드의 중복 prefix는 **의도적으로 그대로 뒀다** — 제거하면 아티팩트 라우터의
> `GET/DELETE /api/v1/documents/{id}`를 가로채기 때문이다(아래 분석 참조).
> 같은 수정을 `examples/document_api_example.py`에도 적용했다.
> 근본 해결(네임스페이스 분리)은 여전히 미착수:
> `docs/superpowers/specs/2026-07-01-neos-research-platform-design.md:92`.
>
> 아래는 감사 시점의 원래 분석이다(기록 보존).

**원인:** `document_handlers.py:34`가 `APIRouter(prefix="/documents")`인데,
`neos/main.py:532`가 **또다시** `prefix="/api/v1/documents"`로 마운트한다.
→ 실제 경로는 `/api/v1/documents/**documents**/upload`.

이는 추측이 아니다. 백엔드 자체 테스트가 이 경로를 못박고 있다:
- `tests/api/handlers/test_document_authorization.py:20` — `BASE_PATH = "/api/v1/documents/documents"`
- 같은 파일 `:44` — *"Preserve the production double-prefix while its URL design remains out of scope."*

**FE는 `/api/v1/documents/upload`를 호출한다** (`web/app/(chat)/api/files/upload/route.ts:87`).
이 경로는 artifact 라우터(`artifact_handlers.py:21`, `main.py:548`에서 `/api/v1` + `/documents`로 올바르게 마운트)의
`GET /{document_id}`와 경로만 겹치고 메서드(POST)가 없다 → **405**.

**재현:** 채팅 입력창에서 클립 버튼으로 아무 파일이나 첨부.
**영향:** `"Failed to upload file to backend"` 반환. 첨부 기능 전체 불능.

**2차 불일치:** 업로드가 성공한다 해도 `route.ts:112`가 `/api/v1/documents/{id}`로 `storage_url`을 조회하는데,
이 경로는 **artifact 핸들러**(`artifact_handlers.py:50`, `List[DocumentResponse]` 반환)로 라우팅된다.
RAG 문서의 `DocumentInfo`(`document_handlers.py:136`)가 아니다. 배열에는 `storage_url`이 없으므로
`docData.storage_url`은 `undefined` → `url: null`.
즉 **두 군데가 독립적으로 깨져 있다.**

### 3.2 ✅ 해결됨 (2026-07-17) — 첨부가 백엔드에 전달되지 않는다

> **해결:** file 파트를 폐기하지 않고 백엔드 `attachments` 필드로 전달한다.
> 추출 로직은 `web/lib/message-parts.ts`(`extractTextContent`, `extractAttachments`)로 분리했고,
> `web/app/(chat)/api/chat/route.ts:55-56`이 이를 호출해 `:124`에서 `attachments`를 실제로 채운다.
>
> 아래는 감사 시점의 원래 분석이다(기록 보존).

`web/components/multimodal-input.tsx:141-152`는 `{type:"file", url, name, mediaType}` 파트를 만든다.
그러나 `web/app/(chat)/api/chat/route.ts:51-54`:

```ts
const messageContent = message.parts
  .filter((part) => part.type === "text")   // ← file 파트 전량 폐기
  .map((part) => part.text)
  .join("\n");
```

백엔드 `SendMessageRequest`는 `attachments` 필드를 명시적으로 갖고 있으나
(`neos/api/models/chat_models.py:79`), FE는 이 필드를 **한 번도 채우지 않는다**
(`route.ts:116-125`가 보내는 것은 `content`/`role`/`metadata`뿐).

**영향:** 3.1이 고쳐져도 첨부는 여전히 LLM에 도달하지 않는다. 멀티모달 API 미사용(§2.2)과 같은 뿌리.

### 3.3 ✅ 해결됨 (2026-07-17) — 리프레시 토큰 회전 파괴 → 강제 로그아웃

> **해결:** 회전된 `refresh_token`을 버리지 않고 보존한다.
> 토큰 병합 로직을 `web/lib/auth-tokens.ts`로 분리했고(회전 토큰이 오면 반드시 교체),
> `web/app/(auth)/auth.ts:44,49`가 갱신 응답의 새 `refresh_token`을 세션에 반영한다.
>
> 아래는 감사 시점의 원래 분석이다(기록 보존).

백엔드 리프레시 토큰은 **1회용**이다:
- `neos/api/services/auth_service.py:209` — 조회 조건에 `~RefreshToken.is_used`
- `:226` — `db_token.is_used = True` (회전)

그런데 `web/lib/backend-api.ts:85-107`의 `refreshBackendToken`은 갱신 응답에서
**`access_token`만 반환하고 `refresh_token`은 버린다**(`:101-102`).
NextAuth 세션에는 여전히 방금 `is_used=True`가 된 낡은 리프레시 토큰이 남는다.

**재현:** 액세스 토큰 만료 직후 API 호출 1회(401 → `backend-api.ts:57`의 갱신 경로 진입) →
이후 NextAuth `jwt` 콜백의 정기 갱신(`web/app/(auth)/auth.ts:244`)이 이미 소비된 토큰으로 시도 → 401 →
`RefreshAccessTokenError`(`auth.ts:49`) → `useAuthMonitor`가 **강제 로그아웃**
(`web/hooks/use-auth-monitor.ts:36-44`, `app/layout.tsx:86`에 마운트됨).

**영향:** 사용자가 무작위로 로그인 페이지로 튕긴다. 두 개의 독립적인 갱신 경로
(`backend-api.ts:85` / `auth.ts:23`)가 같은 1회용 토큰을 경쟁적으로 소비하는 구조 자체가 결함이다.

**부기(정정):** `backend-api.ts:62` 주석은 "세션 업데이트는 클라이언트에서 `useSession().update()` 필요"라고
적었으나, 그 호출자는 코드베이스에 **없다**(`trigger === "update"` 경로 `auth.ts:235`는 죽은 코드).

### 3.4 ✅ 코드 완료 (2026-07-17, 라이브 검증 대기) — 대화 목록 페이지네이션 불일치

> **해결:** keyset(cursor) 페이지네이션으로 교체했다. 백엔드가 정렬 튜플
> `(is_pinned, last_message_at, created_at, conversation_id)`을 불투명 base64 커서로
> 발급하고(`neos/api/services/pagination.py`), 리포지토리가 keyset WHERE + `LIMIT n+1`
> has-more 프로브로 조회한다(`neos/database/repositories/chat_repository.py`,
> `conversation_id DESC` 유니크 타이브레이커 추가, `datetime.min` NULL 센티넬).
> 서비스가 커서를 디코딩하고 `next_cursor`를 발급하며(`neos/api/services/chat_service.py`),
> 핸들러는 `cursor` 쿼리 파라미터를 받고 손상 커서를 400으로 매핑한다
> (`neos/api/handlers/chat_handlers.py`). FE는 커서를 해석 없이 되돌려 보낸다
> (`web/lib/chat-history-pagination.ts`, `web/lib/adapters/chat-adapters.ts`,
> `web/app/(chat)/api/history/route.ts` — `offset=0` 하드코딩 제거).
>
> **회귀 테스트:** `tests/api/services/test_pagination.py`(코덱 왕복+타입검증),
> `tests/database/repositories/test_chat_repository_pagination.py`(keyset 쿼리 메커닉),
> `tests/test_chat_service.py`(커서 흐름·next_cursor), `web/tests/source/chat-history-pagination.test.ts`(키 빌더).
> 백엔드 63개 스위트 + FE 36개 소스 테스트 통과, `tsc --noEmit` 통과.
>
> **⚠️ 남은 검증(라이브 스택 필요, 이 세션에서 실행 불가):** 자동화 테스트는 코덱·쿼리
> 메커닉·타입 배선을 덮지만, **실제 Postgres에서 keyset이 페이지를 겹치거나 빠뜨리지 않는지**는
> 라이브 검증이 필요하다. 대화 40개 초과(고정/비고정 혼재, `last_message_at` NULL 포함)를 시드한 뒤:
> ① 사이드바를 바닥까지 반복 스크롤 → 중복 없이 새 대화만 추가되고 목록이 종료되는지,
> ② Network 탭에서 `?limit=20` → `?cursor=...&limit=20` 순으로 요청되고 마지막 응답이
> `next_cursor: null` / `has_more: false`인지, ③ `?cursor=garbage`가 500이 아니라 400인지 확인.
> 이 검증 통과 후 상태를 완전 ✅로 갱신할 것.
>
> **잔여(범위 밖):** FE는 `created_at`으로 날짜 그룹(Today/Yesterday/…)을 나누는데 BE 정렬은
> `last_message_at` 기준이다. 따라서 "더 보기"가 이미 렌더된 날짜 그룹 중간에 항목을 삽입할 수
> 있다 — 기존 동작이며 버그가 아니고, 정렬 기준 통일은 별도 제품 결정이라 이번 범위에서 제외했다.
> 설계: `docs/superpowers/specs/2026-07-17-sidebar-pagination-design.md`.
>
> 아래는 감사 시점의 원래 분석이다(기록 보존).

- FE 사이드바는 2페이지부터 `ending_before=<id>`를 보낸다 (`web/components/sidebar-history.tsx:97`)
- 그러나 `web/app/(chat)/api/history/route.ts:20`은 `ending_before`를 **읽지 않고** 항상
  `?limit=${limit}&offset=0`을 백엔드로 보낸다
- 백엔드는 `offset` 기반 페이지네이션을 지원한다 (`neos/api/handlers/chat_handlers.py:305-306`)

**재현:** 대화 20개 초과 상태에서 사이드바 스크롤.
**영향:** 2페이지 이후 동일한 첫 페이지가 반복 반환된다. `has_more`가 계속 `true`이므로
(`chat_handlers.py:324`) 무한 스크롤이 끝나지 않고 React 중복 key가 발생한다.

### 3.5 🟡 입력 스키마가 UI보다 좁다

`web/app/(chat)/api/chat/schema.ts`:
- `:41` — 텍스트 `max(2000)`. 2000자 초과 입력 시 `postRequestBodySchema.parse` 실패
  (`route.ts:17`) → `bad_request:api`. UI에 글자수 제한 표시나 사전 검증 없음
- `:49` — 파일 `mediaType`이 `["image/jpeg","image/png"]`뿐. 그러나 업로드 라우트는 9종을 허용한다
  (`web/app/(chat)/api/files/upload/route.ts:7-19`: gif/webp/pdf/doc/docx/txt/md 포함).
  PDF를 첨부하면 스키마 검증에서 전체 요청이 400으로 죽는다
- `:41` `min(1)` — 첨부만 하고 텍스트를 비우면 400. `multimodal-input.tsx:148-151`이 빈 텍스트 파트를 항상 추가하기 때문

**영향:** 전부 원인 불명의 일반 400으로 표면화된다.

### 3.6 🟢 (백엔드 측) skills 라우터도 double-prefix

`skills_handlers.py:13`(`APIRouter()`) + `:60`(`@router.get("/skills")`) + `main.py:539-540`(`prefix=".../skills"`)
→ 실제 경로 `/api/v1/skills/skills`. `main.py:279`의 기동 로그는 `/api/v1/skills`라고 안내한다(불일치).
FE 미사용이라 현재 영향은 없으나, §3.1과 동일한 구조적 실수다.

### 3.7 🟢 하드코딩된 토큰 수명

`web/app/(auth)/auth.ts:44,231,237`이 `15 * 60 * 1000`을 하드코딩한다.
백엔드는 `expires_in`을 응답에 포함하고(`neos/api/models/auth_models.py:60`,
`auth_service.py:165`) 값은 설정 가능하다(`config/neos.default.yaml:180`).
**현재는 기본값 15분이라 우연히 일치**하므로 버그는 아니다. 운영자가 이 값을 바꾸면 조용히 어긋난다.

### 3.8 🟢 죽은 코드 / 미사용 계약

- `web/components/chat.tsx:105` — AI Gateway 신용카드 에러 분기(도달 불가)
- `web/app/(chat)/api/chat/schema.ts:111,137` — `convertToOpenResponsesPart` / `convertToLegacyPart` 미사용
- `web/lib/backend-api.ts:146` — `callBackendAPIWithKey` 미사용
- `web/app/(chat)/api/chat/route.ts:152,154` — `X-OpenResponses-Version` / `X-Conversation-Id` 헤더를
  설정하지만 읽는 곳이 없다. (버전 값 `"2024-01-01"`은 백엔드 `chat_handlers.py:87`과 일치 — 문제 아님)

---

## 4. 일관성·안정성 이슈

### 4.1 ✅ 해결됨 (2026-07-17) — 정지(Stop) 버튼이 에러 토스트를 띄운다

> **해결:** abort를 에러로 처리하지 않는다. `web/hooks/use-chat-stream.ts:594-597`이
> `isAbortError`(`web/lib/stream-errors.ts`)로 판별해 그대로 재던지고,
> 바깥 `sendMessage`의 AbortError 분기가 정상적으로 도달한다.
>
> 아래는 감사 시점의 원래 분석이다(기록 보존).

`web/hooks/use-chat-stream.ts:686-692`의 `stop()`은 `abortController.abort()` 후 `setStatus("ready")`를 부른다.
그러나 abort는 `reader.read()`를 `AbortError`(DOMException, `instanceof Error === true`)로 거부시키고,
이는 `processStream` **내부** catch(`:592-597`)에 잡혀 `setStatus("error")` + `onError(error)`를 부른다.
`onError`는 토스트를 띄운다(`web/components/chat.tsx:109-113,115-118`).

`sendMessage`의 바깥 catch에는 AbortError를 정상 처리하는 분기가 있으나(`:666-668`),
`processStream`이 예외를 **다시 던지지 않으므로** 이 분기는 **도달 불가**다.

**영향:** 정지할 때마다 빨간 에러 토스트 + 최종 상태 `error`.
(`stop()`의 `setStatus("ready")`는 동기, 거부는 마이크로태스크 → `error`가 최종 승자)

### 4.2 ✅ 해결됨 (2026-07-17) — `autoResume`는 재개가 아니라 재실행이다

> **해결:** 재과금을 막기 위해 `resumeStream`을 의도적 no-op으로 바꿨다
> (`web/hooks/use-chat-stream.ts:754-757`). 새로고침해도 워크플로우가 재실행되지 않는다.
> 단, **진짜 "재개"는 아직 없다** — 이벤트 재생 기반 재개는 Phase 3 과제로 남아 있고,
> 이는 §6의 AC6(늦은 접속 시 전체 이력 재생) 미준비와 같은 뿌리다.
>
> 아래는 감사 시점의 원래 분석이다(기록 보존).

`web/hooks/use-auto-resume.ts:30-31`은 마지막 메시지가 user면 `resumeStream()`을 호출한다.
그런데 `web/hooks/use-chat-stream.ts:734-742`의 `resumeStream`은 **`sendMessage`를 다시 부른다** —
즉 `POST /api/chat`으로 워크플로우 전체를 **새로 실행**한다. 이벤트 재생도, 커서도, 멱등키도 없다.

`web/app/(chat)/chat/[id]/page.tsx:71`이 `autoResume={true}`다.

**재현:** 스트리밍 중 탭을 닫거나 네트워크가 끊겨 assistant 메시지가 저장되지 않은 상태 →
해당 대화를 다시 연다.
**영향:** 사용자 의도 없이 멀티에이전트 워크플로우가 재과금 실행되고 메시지가 중복 생성된다.
`regenerate`(`:697-729`)도 같은 재실행 방식이다.

### 4.3 🟡 스트림에 재연결·하트비트·타임아웃이 없다

- 재연결 로직 부재. `while(true) { reader.read() }`(`:257-259`)가 전부다
- 백엔드가 바이트를 보내지 않고 멈추면 `reader.read()`가 **무한 대기**한다. 클라이언트 타임아웃 없음 → 상태가 `streaming`에 영구 고착
- `web/app/(chat)/api/chat/route.ts:10`의 `maxDuration = 60` — 60초를 넘기는 심층 워크플로우는 함수가 종료된다.
  이때 `TransformStream.flush`(`:138-141`)가 실행되면 `data: [DONE]`이 나가고 클라이언트는 **성공으로 오인**해
  잘린 답변을 완료 처리한다(`use-chat-stream.ts:267-271`). **미확인:** 실제 60초 초과 시
  flush 실행 여부는 런타임(Vercel/Node) 의존이라 코드만으로 단정할 수 없다
- 클라이언트 abort가 백엔드로 전파되지 않는다. `route.ts:112`의 `callBackendAPI` 호출에
  `request.signal`이 전달되지 않으므로, 사용자가 정지해도 **백엔드는 계속 생성하고 계속 과금된다**

### 4.4 🟡 SSE 파서가 두 벌이고 계약이 다르다

- `web/hooks/use-chat-stream.ts:216` — OpenResponses 형식(`{type: "response.*"}`) 처리
- `web/lib/sse-stream.ts:20` — `{event, data}` 형식 처리. `readSseStream`은 `parsed.event === "completed"`를 본다

두 파서가 서로 다른 이벤트 스키마를 가정한다. 후자는 UIFrameForm·approval 스트림이 쓴다.
`web/lib/sse-stream.ts:39`는 `JSON.parse(...) as SseEvent`로 **무검증 캐스팅**하고,
`:45-47`은 파싱 오류를 **조용히 삼킨다**.

### 4.5 🟡 백엔드 응답에 런타임 검증이 없다

zod 검증은 **FE로 들어오는 요청**에만 있다(`chat/schema.ts`, `(auth)/actions.ts:23,59`, `files/upload/route.ts:61`).
**백엔드 응답은 전부 무검증**이다 — `await res.json()` 결과를 어댑터에 그대로 넣는다
(`web/app/(chat)/api/history/route.ts:27-28`, `web/lib/adapters/chat-adapters.ts:33-40`).

유일한 예외가 SSE의 `inline_viz`다(`use-chat-stream.ts:561`). 즉 **검증 패턴을 알고는 있으나 한 곳에만 적용**했다.

`any` 사용은 44곳. 집중부: `lib/message-converter.ts`(9), `hooks/use-chat-stream.ts`(6),
`components/message.tsx`(5). `use-chat-stream.ts:156`의 `ChatRequestOptions`는 `[key: string]: any`로 완전 개방이다.

### 4.6 🟢 스트리밍 중 메시지 변이(mutation)

`use-chat-stream.ts:248-254`의 `updateMessage()`는 항상 **마지막** 메시지를 교체한다
(`newMessages[newMessages.length - 1] = {...assistantMessage}`).
또한 `:312-315`가 `textPart.text += delta`로 `parts` 배열 내부를 **직접 변이**하는데,
얕은 복사(`{...assistantMessage}`)는 `parts` 참조를 공유한다.
**미확인:** `components/message.tsx`의 메모이제이션 비교 방식에 따라 렌더 누락이 발생할 수 있으나,
현재 실제 증상이 있는지는 확인하지 못했다.

---

## 5. 테스트 커버리지 실태

| 항목 | 실태 |
|---|---|
| 테스트 파일 | **9개** (소스 202개 대비) |
| 구성 | e2e 4개(`tests/e2e/api|auth|chat|model-selector.test.ts`), source 2개(`tests/source/blueblack-theme`, `open-responses-types`), 나머지는 fixture/helper/page-object |
| 테스트 케이스 | 약 34개 (e2e 30, source 4) |
| 러너 | Playwright(e2e) + `tsx --test`(source 2개뿐). **vitest/jest 없음** (`web/package.json:11-12`) |
| **CI** | **없음.** `.github/`에 `dependabot.yml`만 존재하고 **workflows 디렉터리 자체가 없다** |
| 백엔드 모킹 | 사실상 없음. `page.route` 사용은 `tests/e2e/api.test.ts:59` **단 1곳** |

**핵심 문제:**
1. **CI가 없으므로 어떤 테스트도 자동 실행되지 않는다.** 회귀는 수동 실행에만 의존한다.
2. e2e가 실제 백엔드 + 실제 LLM을 요구한다(`api.test.ts:7-21`은 `/`로 가서 실제 응답 30초 대기).
   백엔드 없이는 전부 실패 → 실질적으로 상시 실행 불가.
3. **이번 감사에서 찾은 모든 결함이 단위 테스트로 잡혔어야 할 것들이다.**
   `use-chat-stream.ts`(753줄, 스트리밍 핵심), `lib/backend-api.ts`(토큰 회전), `lib/adapters/*`(응답 변환),
   `app/(chat)/api/*/route.ts`(계약) — **전부 테스트 0개.**
4. 첨부 업로드(§3.1)가 405로 죽는데도 아무도 몰랐던 이유가 여기 있다.

---

## 6. §5.4 계약 변경 대응 준비도 — **낮음 (미준비)**

`docs/superpowers/specs/2026-07-17-loop-architecture-consolidation-design.md:317-330`이 요구하는 변경:

| | 현재 | 목표(§5.1) |
|---|---|---|
| 제출 | 챗 노드 블로킹 완주 | `POST /api/v1/deep-analysis` → **202 + run_id 즉시 반환** |
| 진행 | 챗=no-op | `GET /api/v1/deep-analysis/{run_id}/events` — **이벤트 로그 재생 + 라이브 tail** |
| 재개 | 없음 | Ledger에서 복원 후 속행 |

### 준비된 자산 (부분 긍정)

- `components/harness-status.tsx` + `use-chat-stream.ts:501-518`(`applyHarnessEvent`, `:60-152`)이
  이미 harness 이벤트(started/check/repair/completed)를 상태 기계로 처리한다. **이벤트 스키마 이해는 있다.**
- `lib/sse-stream.ts`가 재사용 가능한 SSE 리더로 존재하며, 주석(`:4`)이 "향후 ApprovalStream 등"을 상정한다.
- approval 흐름(`app/(chat)/api/approval/stream/[sessionId]/route.ts`)이 이미
  **"POST로 제출 → 별도 GET SSE로 재구독"** 패턴의 선례다. §5.4와 구조가 같다.
- `async_research_handlers.py:66,132,165`에 job 핸들 + 상태 + 스트림 3종 참고 구현이 이미 있다.

### 차단 요인 (핵심)

1. **🔴 AC6(늦은 접속 시 전체 이력 재생)을 받을 구조가 없다.**
   FE에는 이벤트 커서/`Last-Event-ID`/재생 개념이 전무하다. 현재의 "재개"는 §4.2대로 **재실행**이다.
   §5.4를 받으려면 `resumeStream`을 **재실행에서 재구독으로 의미부터 뒤집어야** 한다.
   이건 추가가 아니라 교체다.
2. **🔴 run_id를 담을 곳이 없다.** FE는 `id`(=conversation_id) 단일 키만 다룬다.
   run_id 영속화(URL/스토리지/DB)·복원 경로가 없어, 새로고침하면 진행 중 job으로 되돌아갈 방법이 없다.
   `X-Conversation-Id` 헤더 선례(`route.ts:154`)는 **읽는 쪽이 아예 없어**(§3.8) 재사용 가치가 없다.
3. **🔴 `maxDuration = 60`**(`route.ts:10`)이 장시간 job 스트림과 정면충돌한다.
   job 방식으로 바뀌면 제출(202)은 빨라지지만, 이벤트 tail은 60초에서 끊긴다.
   §4.3의 "flush가 `[DONE]`을 보내 성공으로 오인" 문제가 그대로 재현된다.
4. **🟡 스트림 소비가 `POST /api/chat` 응답에 강결합**돼 있다.
   `use-chat-stream.ts:643-664`는 "POST 후 그 응답 본문을 읽는다"는 전제다.
   `GET .../{run_id}/events` 구독은 **새 트랜스포트**를 요구한다.
5. **🟡 안전망이 없다.** 스트리밍 핵심 로직에 단위 테스트 0개(§5) + CI 없음.
   이 규모의 계약 변경을 검증 없이 진행하는 셈이다.

### 결론

스펙 자체가 이 위험을 예견했다 — 같은 문서 `:366`의 **K4("단계 3의 챗 계약 변경이 프론트와 어긋남 →
FE 준비 전까지 플래그로 격리")**. 현재 상태는 **K4가 현실이 될 조건을 충족**한다.
플래그 격리는 필수이고, 그 전에 §4.2(재개 의미)와 §7 P0 항목이 선행돼야 한다.

---

## 7. 권고 사항 (우선순위 순)

규모 표기: **S** ≈ 반나절 이하 / **M** ≈ 1~3일 / **L** ≈ 1주 이상

| # | 우선순위 | 항목 | 규모 | 비고 |
|---|---|---|---|---|
| 1 | ~~**P0**~~ ✅ 완료(프론트) | **CI 구축.** `.github/workflows` 신설 — typecheck + `test:source` + (백엔드 모킹된) 단위 테스트 | **S** | 2026-09-02 완료 — `.github/workflows/frontend-ci.yml` (`pnpm install --frozen-lockfile` → `test:source` → `tsc --noEmit`). ⚠️ **이 항목은 2026-08 에 생긴 `backend-ci.yml` 때문에 닫힌 것처럼 보였으나 아니었다** — 그것은 백엔드 전용이라 `web/tests/source/` **35파일 199건이 CI 에서 한 번도 돌지 않았다.** 그 공백이 로드맵 FE6·FE9 의 공유 fixture 를 **절반만 물게** 만들고 있었다(빨개질 수 있는 쪽이 백엔드뿐이었다). 정본은 로드맵 §5.4 ‖ **`paths:` 필터를 두지 말 것** — 프론트 테스트가 저장소 루트의 공유 fixture 를 읽으므로 `web/**` 로 좁히면 백엔드-단독 fixture 변경에서 꺼진다. `tests/config/test_test_environment_policy.py` 의 가드 셋이 이 결정을 기계로 고정한다 ‖ **린트·e2e 는 뺐다**: `progress.ts` 의 biome 경고 2건이 선행 정리 대상이고, e2e 는 실 백엔드·실 LLM 을 요구한다(§5) |
| 2 | ~~**P0**~~ ✅ 완료 | **리프레시 토큰 회전 수정**(§3.3). 갱신 경로를 `auth.ts` **한 곳으로 단일화**하고 `backend-api.ts`의 중복 갱신 제거. 회전된 refresh_token을 반드시 세션에 반영 | **S~M** | 2026-07-17 완료 (`web/lib/auth-tokens.ts`, `auth.ts:44,49`) |
| 3 | ~~**P0**~~ ✅ 완료(부분) | **`autoResume` 재실행 차단**(§4.2). 최소 조치로 `chat/[id]/page.tsx:71`을 `false`로 내리고, 재개는 §5.4의 이벤트 재생 위에서 재설계 | **S**(차단) / **L**(재설계) | 차단만 완료 — `resumeStream`을 no-op으로(`use-chat-stream.ts:754`). **재설계(L)는 미착수** |
| 4 | ~~**P1**~~ ✅ 완료 | **첨부 파이프라인 복구**(§3.1, §3.2). ① 업로드 URL을 실제 경로로 정정 ② `storage_url` 조회를 올바른 핸들러로 ③ `route.ts`가 file 파트를 `attachments`로 전달 ④ 스키마 MIME 목록 일치(§3.5) | **M** | ①②③ 2026-07-17 완료 (`web/lib/backend-routes.ts`, `message-parts.ts`). **④(§3.5)는 미확인.** ⚠️ **정정:** 원래 이 항목은 "백엔드 double-prefix 제거(권장)"를 적었으나 **그렇게 하면 안 된다** — `/api/v1/documents`는 아티팩트 라우터(`main.py:548`, `:539`가 아님)가 점유하며, 먼저 등록된 RAG(`:532`)가 `GET/DELETE /{id}`를 가로챈다. 백엔드는 그대로 두고 FE가 실제 경로를 부르는 것이 정답이다 |
| 5 | ~~**P1**~~ ✅ 완료 | **Stop 버튼 에러 토스트 제거**(§4.1). `processStream`에서 AbortError를 재던지거나 catch에서 제외 | **S** | 2026-07-17 완료 (`use-chat-stream.ts:594-597`, `lib/stream-errors.ts`) |
| 6 | **P1** | **클라이언트 abort를 백엔드로 전파**(§4.3). `callBackendAPI`에 `signal` 전달 | **S** | 정지 후에도 계속되는 과금을 막는다 |
| 7 | ~~**P1**~~ ✅ 코드 완료 | **페이지네이션 수정**(§3.4). | **S** | 2026-07-17 코드 완료. ⚠️ 원 권고는 "offset 방식"이었으나 **keyset 커서**로 구현했다 — offset은 스크롤 중 `last_message_at` 변동 시 항목 중복/누락이 생기기 때문. `neos/api/services/pagination.py` + `web/lib/chat-history-pagination.ts`. 라이브 keyset 검증은 §3.4 체크리스트 참조 |
| 8 | **P2** | **§5.4 대비 트랜스포트 분리**(§6). run_id 영속화 + `GET /{run_id}/events` 재구독 훅. `maxDuration` 재검토 | **L** | approval 스트림·`async_research`를 선례로 삼을 것. **플래그 격리 필수(K4)** |
| 9 | **P2** | **백엔드 응답 런타임 검증**(§4.5). 어댑터 경계에 zod `safeParse` 도입 | **M** | `inline_viz` 패턴을 확대 적용 |
| 10 | **P2** | **SSE 파서 단일화**(§4.4) | **M** | §5.4 작업과 묶는 것이 효율적 |
| 11 | **P3** | **미사용 기능 로드맵 결정**(§2.2). research 계열(deep-research/session/export/template/refinement)을 **연동할지 폐기할지** 명시적으로 판단 | **S**(판단) / **L**(연동) | 백엔드 유지비만 발생 중인 최대 미연동 자산 |
| 12 | **P3** | 죽은 코드 정리(§3.8), `/logout` 연동(§2.2), 하드코딩 TTL을 `expires_in`으로 대체(§3.7) | **S** | |

---

## 8. 감사 한계 (미확인 항목)

- **런타임 미검증.** 백엔드·프론트를 기동해 실제 응답을 확인하지 않았다. 라우트 해석은
  FastAPI 등록 순서와 백엔드 자체 테스트(`test_document_authorization.py:20,44`)를 근거로 한 **정적 추론**이다.
  §3.1의 405 판정은 이 추론에 의존한다(경로 double-prefix 자체는 백엔드 테스트로 확증됨).
- `maxDuration=60` 초과 시 `TransformStream.flush` 실행 여부는 런타임 의존이라 미확인(§4.3).
- `components/message.tsx` 메모이제이션과 `parts` 변이의 상호작용은 미확인(§4.6).
- `deep_analysis_analytics`에 admin 게이트가 없어 보이는 점의 의도 여부는 미확인(§2.2).
- `.next/`, `node_modules/`는 감사 범위에서 제외했다.
