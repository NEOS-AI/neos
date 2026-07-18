# 사이드바 대화 목록 페이지네이션 수정 — 설계 (2026-07-17)

## 배경

`web/components/sidebar-history.tsx`의 대화 목록이 무한 스크롤에서 **같은 페이지를
반복 로드**한다. 감사 문서 `docs/FE_AUDIT_260717.md` §3.4 / §7 #7 항목.

### 근본 원인

FE와 BE가 서로 다른 페이지네이션 언어를 쓰고, 그 사이의 라우트가 커서를 조용히 버린다.

1. **사이드바**는 커서 방식으로 요청한다:
   `getChatHistoryPaginationKey`(`sidebar-history.tsx:79`)가
   `/api/history?ending_before=<마지막 chat id>&limit=20`을 만든다.
2. **BE 엔드포인트**(`GET /api/v1/chat/users/{user_id}/conversations`,
   `chat_handlers.py:301`)는 `limit`/`offset`만 받는다 — 커서 개념이 없다.
3. **중간 라우트**(`web/app/(chat)/api/history/route.ts:20`)가 `ending_before`를
   무시하고 `offset=0`을 하드코딩한다.
4. BE 서비스(`chat_service.py:176`)는 `has_more = (offset + limit) < total_count`로
   계산한다. `offset`이 영구히 0이므로, 대화가 20개를 넘으면 `has_more`가 **항상 true**다.
5. `useSWRInfinite`는 `hasMore !== false`인 한 다음 페이지를 계속 요청하지만,
   매번 `offset=0` 첫 페이지만 돌려받는다 → 무한 반복.

### 추가로 확인된 사실 (설계에 영향)

- **BE 정렬 키가 복합·가변이다**:
  `ORDER BY is_pinned DESC, last_message_at DESC NULLS LAST, created_at DESC`
  (`chat_repository.py:384`). 유니크 컬럼이 없어 동점 시 순서가 비결정적이다.
- **FE는 정렬 키를 볼 수 없다**: `adaptBEConversation`(`chat-adapters.ts:20`)이
  `is_pinned`·`last_message_at`을 버리고 `id`/`created_at`만 남긴다. 따라서 FE가
  커서 튜플을 조립하는 것은 불가능하다 → **커서는 BE가 발급하는 불투명 토큰이어야 한다.**
- **컬럼 타입**: `last_message_at`, `created_at` 모두 `TIMESTAMP`(no tz,
  `db/chat_system.sql:39,43`), `is_pinned`는 `BOOLEAN`, `conversation_id`는 PK 문자열.
- **소비자는 FE 라우트 단 하나**다. 이 BE 엔드포인트를 호출하는 다른 Python 코드는 없다
  (`list_user_conversations`/`list_conversations` grep 결과). 기존 BE 테스트
  (`tests/test_chat_service.py:280`)는 리포지토리를 목킹하므로 SQL 정렬을 검증하지 않는다.
  → 정렬 변경의 폭발 반경이 작다.
- **테스트 러너**: `test:source`는 `tsx --test tests/source/**/*.test.ts`만 실행한다
  (`web/package.json:12`). 순수 함수 단위 테스트에 적합하다.

## 선택한 접근 (A안: 기존 정렬 보존)

키셋(keyset/cursor) 페이지네이션. **커서 술어는 `ORDER BY`와 정확히 일치해야 한다**는
원칙에 따라, 기존 정렬을 그대로 두고 유니크 타이브레이커만 추가한다.

- 정렬: `is_pinned DESC, last_message_at DESC NULLS LAST, created_at DESC, conversation_id DESC`
- 제품 동작(고정 우선 → 최근 활동순)은 **변경 없음**. `conversation_id`는 동점일 때만
  개입하는 결정적 타이브레이커다.

### 대안과 기각 사유

- **B안 `(is_pinned, created_at, id)`**: 불변 키라 드리프트가 없지만 "최근 활동순"을
  잃어 정렬 UX가 바뀐다. 페이지네이션 수정에 제품 변경을 몰래 끼워넣게 됨 → 기각.
- **C안 `(created_at, id)`**: 가장 단순하나 고정(pin)까지 정렬에서 제거 → UX 변경 최대 → 기각.
- **FE-only offset 방식**(사이드바가 `pageIndex*PAGE_SIZE` offset 전송): 규모는 가장 작지만
  스크롤 중 `last_message_at` 변동 시 항목 중복/누락. 사용자가 "진짜 커서" 방식을 선택함 → 기각.

### A안의 알려진 한계

`last_message_at`이 가변이라 이론상 스크롤 도중 커서 드리프트가 가능하다. 실무 영향은
극미하다 — 스크롤 중 `last_message_at`이 바뀌는 대화는 사용자가 지금 대화 중인 그 하나뿐이고,
그건 이미 목록 최상단(첫 페이지)에 있어 커서 경계에 걸리지 않는다.

## 컴포넌트 설계

### ① 커서 코덱 (신규, BE) — `neos/api/services/pagination.py`

작고 순수한 모듈. 프레임워크·DB 의존성 없음.

- `encode_conversation_cursor(is_pinned: bool, last_message_at: datetime | None,
  created_at: datetime, conversation_id: str) -> str`
  - JSON `{"p": bool, "m": ISO8601 | null, "t": ISO8601, "i": str}`을 UTF-8 → base64url로.
- `decode_conversation_cursor(token: str) -> ConversationCursor`
  - base64url → JSON → 타입 검증. 손상/형식 오류 시 `ValueError`.
  - `ConversationCursor`는 `p/m/t/i` 필드를 가진 dataclass 또는 TypedDict.
- **불변식**: `decode(encode(x)) == x` (datetime은 마이크로초까지 왕복).

### ② 리포지토리 — `neos/database/repositories/chat_repository.py:list_conversations`

- 시그니처에 `cursor: ConversationCursor | None = None` 추가. 기존 `offset`은 유지
  (하위호환). `cursor`가 주어지면 `offset`은 무시한다.
- `ORDER BY`에 `, conversation_id DESC` 추가.
- `cursor`가 있으면 아래 WHERE 절을 `where_clauses`에 추가. NULL-안전을 위해
  `COALESCE(last_message_at, :null_sentinel)`을 쓰되, **센티넬은 SQL 리터럴 `-infinity`가
  아니라 Python `datetime.min`(`0001-01-01 00:00:00`)을 바인드 파라미터로 넘긴다** —
  asyncpg가 `TIMESTAMP` 컬럼에 문자열 `'-infinity'`를 인코딩하지 못하기 때문. 이 센티넬은
  어떤 실제 `last_message_at`보다도 작아 `NULLS LAST`와 동일한 정렬을 준다:
  ```sql
  (
        is_pinned < :p
     OR (is_pinned = :p AND COALESCE(last_message_at, :sentinel) < :m)
     OR (is_pinned = :p AND COALESCE(last_message_at, :sentinel) = :m
         AND created_at < :t)
     OR (is_pinned = :p AND COALESCE(last_message_at, :sentinel) = :m
         AND created_at = :t AND conversation_id < :i)
  )
  ```
  - `:sentinel`과 `:m` 모두 실제 `datetime` 값을 바인드한다. `:m`은 커서의
    `last_message_at`이며, 커서에 없으면(원래 NULL) `datetime.min`을 바인드한다.
  - ORDER BY의 `last_message_at DESC NULLS LAST`는 그대로 둔다 — WHERE의 COALESCE 정규화와
    정렬 결과가 일치한다(NULL은 항상 최하위).
- `has_more` 판정: `LIMIT :limit + 1`로 한 행 더 읽는다. `limit+1`행이 오면
  `has_more=True`, 초과분 1행을 잘라 버린다. `total_count`용 count 쿼리는 그대로 유지.
- 반환값에 `has_more: bool`을 포함 (현재는 서비스에서 계산 중이나, 커서 방식에선
  리포지토리가 limit+1 트릭으로 판정하므로 여기로 이동).

### ③ 서비스 — `neos/api/services/chat_service.py:list_conversations`

- `cursor: str | None = None` 인자 추가. 문자열이면 `decode_conversation_cursor`로 디코딩,
  실패 시 400에 매핑되도록 `ValueError`를 그대로 전파(핸들러에서 처리).
- `next_cursor` 계산: `has_more`가 True일 때만, **초과분을 잘라낸 뒤 반환되는 `limit`행 중
  마지막 행**(= 소비자가 페이지 끝에서 보는 항목)의 4-튜플을 `encode_conversation_cursor`로
  인코딩한다. 이 행 다음부터 다음 페이지가 시작되므로 경계가 정확히 이어진다.
  `has_more`가 False면 `None`.
- 반환 dict에 `next_cursor: str | None` 추가. `has_more`는 리포지토리 값 사용
  (`(offset+limit) < total_count` 계산식 제거).

### ④ 모델·핸들러 — `neos/api/models/chat_models.py`, `chat_handlers.py`

- `ConversationListResponse`에 `next_cursor: Optional[str] = None` 추가.
  `total_count`·`has_more`는 유지.
- `list_user_conversations` 핸들러에 `cursor: Optional[str] = None` 쿼리 파라미터 추가,
  서비스로 전달. 디코딩 실패(`ValueError`)는 `HTTPException(status_code=400)`으로 변환
  (현재의 광범위 `except Exception → 500`보다 앞에 배치).

### ⑤ FE 어댑터 — `web/lib/adapters/chat-adapters.ts`

- `BEConversationListResponse`에 `next_cursor?: string | null` 추가.
- `adaptBEConversationList` 반환 타입에 `nextCursor: string | null` 추가
  (`data.next_cursor ?? null`).

### ⑥ FE 라우트 — `web/app/(chat)/api/history/route.ts`

- `offset=0` 하드코딩 제거.
- `const cursor = searchParams.get("cursor")` 읽어, 있으면
  `?limit=${limit}&cursor=${encodeURIComponent(cursor)}`, 없으면 `?limit=${limit}`로
  백엔드 호출.
- `DELETE` 핸들러는 변경 없음.

### ⑦ FE 사이드바 — `web/components/sidebar-history.tsx`

- `ChatHistory` 타입에 `nextCursor: string | null` 추가.
- `getChatHistoryPaginationKey`:
  - `previousPageData.hasMore === false` 또는 `previousPageData.nextCursor == null`이면
    `null` 반환(종료).
  - `pageIndex === 0` → `/api/history?limit=${PAGE_SIZE}`.
  - 그 외 → `/api/history?cursor=${encodeURIComponent(previousPageData.nextCursor)}&limit=${PAGE_SIZE}`.
  - `ending_before`와 `firstChatFromPage` 로직 제거.
- 낙관적 삭제 `mutate`(`sidebar-history.tsx:142`)는 `{...chatHistory, chats: filtered}`
  스프레드라 `nextCursor`를 자동 보존한다 — 코드 변경 불필요(타입 추가만으로 타입체크 통과).

## 데이터 흐름

```
사이드바(SWRInfinite)
  page0: GET /api/history?limit=20
    → route: GET BE /users/{id}/conversations?limit=20
    → BE: keyset 첫 페이지 21행 읽고 20행 반환 + next_cursor=encode(20번째 행)
    → adapter: { chats, hasMore:true, nextCursor }
  page1: GET /api/history?cursor=<t>&limit=20
    → route: GET BE ...?limit=20&cursor=<t>
    → BE: decode(t)로 keyset WHERE, 다음 20행 + next_cursor
    → ... hasMore=false & next_cursor=null 이면 SWR 종료
```

## 에러 처리

- **손상된 커서**: BE `decode`가 `ValueError` → 핸들러가 400. FE 라우트는 400을
  `ChatSDKError("bad_request:database")`로 표면화(기존 패턴 유지).
- **마지막 페이지**: `has_more=false`, `next_cursor=null`. `getChatHistoryPaginationKey`가
  `null`을 반환해 SWR이 멈춘다.
- **빈 목록**: 0행 → `has_more=false`, `next_cursor=null`. 기존 `hasEmptyChatHistory` 경로 유지.

## 테스트

- **BE 단위** (`tests/` pytest):
  - `pagination.py` 코덱 왕복: `decode(encode(x)) == x`, `last_message_at=None` 포함,
    손상 토큰 → `ValueError`.
  - 리포지토리 keyset: 시드 데이터로 페이지 경계가 겹치거나 빠지지 않고 이어지는지
    (동점 타이브레이커, `last_message_at NULL` 혼재 케이스 포함).
- **FE 소스 단위** (`web/tests/source/`, `tsx --test`):
  - `getChatHistoryPaginationKey`: page0 키, nextCursor를 URL-인코딩한 후속 키,
    `hasMore===false` 및 `nextCursor==null` 종료 조건.
  - 회귀 방지: `ending_before`가 더 이상 생성되지 않고 `offset=0`이 재등장하지 않는지.

## 범위 밖 (명시적 제외)

- **offset 파라미터 완전 제거**: 하위호환으로 남긴다. 커서가 우선한다.
- **날짜 그룹/정렬 통일**: FE는 `created_at`으로 Today/Yesterday/… 그룹을 나누는데
  BE는 `last_message_at`으로 정렬한다. 따라서 "더 보기"가 이미 렌더된 날짜 그룹 중간에
  항목을 삽입할 수 있다. 이는 기존 동작이며 버그가 아니고, 정렬 기준 통일은 별도 제품
  결정이다. `docs/FE_AUDIT_260717.md` §3.4에 별도 이슈로 기록만 한다.

## 문서 갱신

- `docs/FE_AUDIT_260717.md`:
  - §1 요약 표 #5 상태를 ✅ 해결됨으로.
  - §3.4에 해결 노트(커서 방식, 코덱 위치, 회귀 테스트) + 그룹 불일치 잔여 이슈 기록.
  - §7 #7 행을 ✅ 완료로.
