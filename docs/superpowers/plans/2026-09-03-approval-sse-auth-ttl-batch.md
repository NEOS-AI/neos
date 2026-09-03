# 승인 SSE 계약 · 토큰 TTL · 스트림 취소 전파 (배치)

FE↔BE 통신 감사(2026-09-03)의 3·7·8번을 닫는다. 1·2·5·4번은 이미 커밋됐다
(`0bef0c4b`·`3e1c816a`·`6db93c8a`·`b8094698`·`ac6ff4cd`·`916e3265`).

세 태스크는 **파일이 겹치지 않으며 서로를 읽지 않는다.** 각자 독립 워크트리에서
병렬로 실행한다.

## Global Constraints

1. **BE 와이어 계약을 새로 만들지 않는다.** 3번은 이미 있는 SSE 포맷
   (`StreamEvent.to_sse_format()`)을 타임아웃 경로에도 적용하는 것이지, 새 이벤트
   종류를 도입하는 것이 아니다.
2. **새 테스트는 반드시 고치기 전에 빨갛게 만들고** 그 실패 출력(기대 대 실제)을
   보고서에 그대로 붙인다.
3. 기존 테스트를 통과시키려고 프로덕션 의미를 바꾸지 않는다. 반대도 같다.
4. 자기 태스크가 소유한 파일 밖을 수정하지 않는다. 다른 태스크의 파일이 막고 있다고
   판단되면 고치지 말고 보고서에 적는다.
5. 커밋에 `Co-Authored-By` 트레일러를 넣지 않는다 (저장소 금지 규칙).

---

## Task 1 — 승인 resume 스트림의 타임아웃이 성공으로 읽힌다 (#3)

**소유 파일:** `neos/api/handlers/approval_handlers.py`,
`web/components/message.tsx`, 신규 `web/lib/approval-stream.ts`

### 무엇이 깨져 있나

BE의 정상 경로는 `StreamEvent.to_sse_format()`을 쓰므로 `event: <종류>` 줄이 붙는다
(`neos/workflow/stream_manager.py:30-45`). 그런데 **타임아웃 경로만** 손으로
`data:` 한 줄만 내보낸다:

```python
# approval_handlers.py:311-312
except asyncio.TimeoutError:
    yield f"data: {json.dumps({'event': 'error', 'message': '...'})}\n\n"   # event: 줄 없음
```

FE는 `event:` 줄로만 종류를 판별하고 그 변수를 **이벤트 사이에 초기화하지 않는다**
(`message.tsx:182-215`). 그래서 타임아웃 payload가 오면 `eventName`은 직전
`node_complete`에 머물러 있고, `completed`·`error` 어느 분기도 타지 않는다.
스트림이 닫히면 루프가 정상 종료하고 호출부가 상태를 `"completed"`로 찍는다
(`message.tsx:248`).

**결과:** 워크플로우가 60초 안에 응답하지 못하면 UI가 "완료"라고 말한다. 본문은
비어 있고 승인 카드는 그대로 남는다.

### 고칠 것 — BE

타임아웃도 정상 경로와 같은 포맷으로 내보낸다. 손으로 문자열을 만들지 말고
`StreamEvent`를 만들어 `to_sse_format()`을 태운다 — 포맷터가 하나여야 이런
불일치가 다시 생기지 않는다. 이벤트 종류는 기존과 같은 `error`, payload도 기존
키(`event`·`message`)를 유지한다.

### 고칠 것 — FE

`readApprovalResumeStream`은 지금 컴포넌트 안에 있어 **테스트할 수 없다.** 순수
함수로 빼서 `web/lib/approval-stream.ts`에 두고 `message.tsx`가 그것을 부르게 한다.

파서가 지켜야 할 것:

- 종류는 `event:` 줄 **또는 payload의 `event` 필드**로 판별한다. 저장소에 이미
  후자를 쓰는 파서가 있다(`web/lib/sse-stream.ts`의 `readSseStream`은
  `parsed.event === "completed"`를 본다) — 두 관례가 공존하므로 둘 다 받는다.
- **이벤트 경계(빈 줄)에서 `eventName`을 초기화한다.** 초기화하지 않는 것이 이번
  버그의 직접 원인이다.
- `data:` 줄의 JSON 파싱 실패는 그 줄만 건너뛴다 — 스트림 전체를 죽이지 않는다.
  (지금은 `JSON.parse`가 try 밖에 있어 keepalive 한 줄에도 던진다.)
- 스트림이 `completed`·`error` 없이 끝나면 그것은 **성공이 아니다.** 호출부가
  성공과 구분할 수 있는 결과를 돌려준다.

`message.tsx`는 그 결과에 따라 성공/실패를 표시하도록 최소한으로 고친다. 승인
카드의 시각적 구조나 다른 분기는 건드리지 않는다.

### 테스트

- BE: `tests/api/handlers/` 에. 타임아웃 경로가 `event: error` 줄을 포함하는 SSE를
  내보내는지 고정한다. `asyncio.wait_for`가 즉시 타임아웃하도록 만들 것
  (60초를 실제로 기다리지 말 것 — 테스트 타임아웃은 30초다).
- FE: `web/tests/source/` 에 신규. 최소한 —
  `event:` 줄이 있는 정상 `completed`, `event:` 줄 **없는** 타임아웃 payload,
  직전 이벤트 이름이 새 이벤트로 새지 않는 것, 깨진 JSON 줄을 건너뛰는 것,
  종결 이벤트 없이 끝난 스트림이 성공으로 보고되지 않는 것.

---

## Task 2 — 로그인이 `expires_in`을 버린다 (#7)

**소유 파일:** `web/app/(auth)/auth.ts`

### 무엇이 깨져 있나

BE `TokenResponse`는 `expires_in`(초)을 항상 포함한다
(`neos/api/models/auth_models.py:60`). 갱신 경로는 그것을 쓴다 —
`mergeRefreshedTokens` → `resolveAccessTokenExpiry`
(`web/lib/auth-tokens.ts:47`). 그런데 **최초 로그인 경로는 하드코딩한다:**

```ts
// auth.ts:235
token.accessTokenExpires = Date.now() + DEFAULT_ACCESS_TOKEN_TTL_MS;  // 15분 고정
```

`authorize()` 세 곳(credentials `:133`, guest `:172`, google OAuth `:207`)이 모두
`data.expires_in`을 읽지 않고 버린다. 배포가 `auth.access_token_expire_minutes`를
15가 아닌 값으로 두면(스키마상 자유 값, `neos/config/schema.py:402`) 그 차이만큼
FE가 만료된 토큰으로 요청을 계속 보낸다. 갱신은 맞고 로그인만 틀린 **비대칭**이라
눈에 띄지 않았다.

### 고칠 것

세 `authorize()`/`signIn` 경로가 BE 응답의 `expires_in`을 `user` 객체에 실어
보내고, `jwt` 콜백이 그것을 `resolveAccessTokenExpiry`에 태운다. TTL 계산은
**`lib/auth-tokens.ts`의 기존 헬퍼 하나**를 쓴다 — 새로 만들지 말 것. 값이 없거나
이상하면 그 헬퍼가 이미 기본값으로 폴백한다.

`declare module "next-auth"`의 `User`/`JWT` 인터페이스에 필드 추가가 필요하다.

**`trigger === "update"` 분기(`:239-242`)**: 그 경로에는 BE 응답이 없다. 세션이
값을 실어 오면 쓰고 아니면 폴백하도록 **같은 헬퍼를 태우기만** 한다. 그 분기를
호출하는 쪽을 새로 만들지 말 것.

**바꾸지 말 것:** `lib/auth-tokens.ts`의 갱신 로직(이미 옳다), 리프레시 토큰 회전
처리, 갱신 경로가 하나뿐이라는 성질.

### 테스트

`web/tests/source/`에. 기존 `auth-tokens.test.ts`가 헬퍼를 다루므로 겹치지 않게 할 것.
고정할 것: BE가 준 `expires_in`이 만료 시각으로 반영된다 · `expires_in`이 없거나
0/음수/비수치면 15분 기본값으로 떨어진다 · 세 로그인 경로 전부.

`jwt` 콜백을 직접 테스트하기 어려우면 **만료 시각을 계산하는 부분을 순수 함수로
빼서** 그것을 테스트한다(Task 1이 파서에 쓰는 것과 같은 방법). 테스트하기 위해
프로덕션 구조를 바꾸는 것은 허용되지만, 동작은 바뀌면 안 된다.

---

## Task 3 — 승인 SSE 프록시가 취소를 전파하지 않는다 (#8)

**소유 파일:** `web/app/(chat)/api/approval/stream/[sessionId]/route.ts`

### 무엇이 깨져 있나

이 라우트는 첫 인자를 `_request`로 받아 **아예 쓰지 않는다.** 형제 프록시인
`app/(chat)/api/deep-analysis/[runId]/events/route.ts:57`은 `request.signal`을
백엔드 호출에 넘긴다. 사용자가 탭을 닫아도 백엔드 제너레이터가 최대 60초 동안
세션 큐를 계속 소비한다.

`maxDuration` 선언도 없다. 형제는 `300`이다. 이 라우트는 BE가 60초에 끊으므로
그보다 여유 있는 값이면 된다.

### 고칠 것

- `request.signal`을 `callBackendAPI`에 넘긴다 (`{ signal: request.signal }`).
- `maxDuration`을 선언한다. 형제 라우트와 같은 이유·같은 방식으로 쓰되, 이 스트림의
  실제 상한(BE 60초)을 근거로 값을 고르고 그 근거를 주석에 남긴다.
- ⚠️ 형제 라우트 주석이 설명하듯 `export const dynamic`은 쓸 수 없다
  (`next.config.ts`가 `cacheComponents: true`라 빌드가 거부한다). 선언하지 말 것.

### 테스트

`web/tests/source/`에. `callBackendAPI`를 대역으로 두고 —
넘겨받은 `request.signal`이 그대로 백엔드 호출 옵션에 실리는지, 그리고 백엔드가
비정상 응답일 때 기존 동작(상태 코드 통과)이 유지되는지 고정한다.
기존 `coding-*` 테스트들이 fetch/대역을 다루는 방식을 참고할 것.

---

## 완료 기준

- `python -m pytest tests/ -q -p no:randomly` → 3523+ passed, 회귀 0
- `cd web && pnpm test:source` → 240+ passed, 회귀 0
- `cd web && pnpm exec tsc --noEmit` clean
- 승인 타임아웃이 UI에서 실패로 보인다
- 로그인 직후 토큰 만료 시각이 BE가 말한 값이다
- 승인 스트림 구독을 끊으면 백엔드 호출도 함께 끊긴다
