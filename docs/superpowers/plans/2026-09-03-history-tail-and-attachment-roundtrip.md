# 대화 히스토리 tail 의미론 + 첨부 왕복 복원

FE↔BE 통신 감사(2026-09-03)의 5번·4번 항목을 닫는다. 1·2번은 이미 커밋됐다
(`0bef0c4b`, `3e1c816a`).

## 배경 — 무엇이 깨져 있나

### A. `limit`이 "최근 N개"가 아니라 "최초 N개"다

`ChatRepository.get_conversation_messages`는 `ORDER BY sequence_number ASC
LIMIT $n`이다. 커서 없이 부르면 **가장 오래된 N개**가 나온다. 호출부 대부분은
정반대를 의도한다:

| 호출부 | limit | 의도 |
|---|---|---|
| `chat_stream_pipeline.py:197` | 20 | LLM 히스토리 — **최근** |
| `chat_handlers.py:442` | 20 | 주석이 *"최근 20개 메시지"*라고 명시 |
| `chat_handlers.py:622` | 20 + `before_sequence` | regenerate 히스토리 — **최근** |
| `rag_chat_handlers.py:79,183` | 20 | RAG 히스토리 — **최근** |
| `chat_message_processor.py:365` | 인자 | 히스토리 — **최근** |
| `chat_handlers.py:527` (`GET /messages`) | FE가 100 | 챗 화면 초기 로드 — **최근** |
| `chat_handlers.py:185` (`/full`) | 100 | 초기 로드 — **최근** |
| `similarity_chat_handlers.py:389` | 1000 | "대화의 모든 메시지" |

증상 둘:
- 20턴이 넘는 대화에서 **LLM이 최근 맥락을 영영 못 본다.** 대화 초반만 붙들고 답한다.
- 100턴이 넘는 대화를 새로고침하면 **최신 대화가 사라지고** 맨 처음 100개만 보인다.

### B. 첨부가 새로고침하면 사라진다

BE는 `MessageResponse.attachments`를 정상적으로 돌려준다
(`chat_models.py:168`). 그런데 `convertBackendMessagesToUI`(`web/lib/utils.ts`)는
`text` 파트 하나만 만들고 `msg.attachments`를 버린다. `message.tsx`는
`part.type === "file"`을 찾으므로 첨부 미리보기가 전부 증발한다.

### C. 첨부 파일명이 한 번도 표시된 적이 없다

작성기 `multimodal-input.tsx:145`는 `name`을 만들고, 렌더러 `message.tsx:304`는
`attachment.filename`을 읽는다. 항상 `undefined` → 모든 첨부가 `"file"`로 뜬다.
새로고침 전에도 그렇다. B를 고쳐 이름을 복원해도 C가 그것을 다시 버리므로
같은 작업 단위에서 닫는다.

## 범위 밖 (의도적)

- **첨부를 LLM 입력에 싣는 것.** `neos/services/chat_llm_service.py`와
  `neos/providers/` 어디에도 이미지·멀티모달 처리가 **없다**. 배선 연결이 아니라
  프로바이더별 멀티모달 입력 지원을 새로 만드는 일이고, 모델별 vision 지원 여부·
  이미지 대 문서 분기·URL 대 base64 결정이 함께 따라온다. 별도 작업으로 남긴다.
- `message-converter.ts` — 임포터가 없는 죽은 모듈로 보이나 이번 범위 밖.

## Global Constraints

1. **반환 순서는 항상 `sequence_number` 오름차순(ASC)이다.** tail은 *어느* N개를
   고르느냐를 바꿀 뿐, 돌려주는 배열의 정렬을 바꾸지 않는다. 호출부 전부가
   ASC 배열을 가정한다.
2. **`after_sequence`가 주어지면 기존 동작(앞에서부터 ASC)을 유지한다.** 그것은
   "커서 다음부터 전방으로 따라잡기"라 tail이면 중간을 건너뛴다.
3. BE 와이어 계약(`MessageAttachment`: `type`/`url`/`name`/`size`/`metadata`)은
   **바꾸지 않는다.** C의 통일은 FE 내부 파트 필드명에 한정한다.
4. 새 테스트는 반드시 **고치기 전에 빨갛게** 만들고 그것을 보고서에 적는다.
   실패 출력(기대값 대 실제값)을 보고서에 붙인다.
5. 기존 테스트를 통과시키려고 프로덕션 코드의 의미를 바꾸지 않는다. 반대도 같다.

---

## Task 1 — 리포지토리 기본값을 tail로

**파일:** `neos/database/repositories/chat_repository.py`

`get_conversation_messages`(679행)를 고친다. 시그니처는 그대로 둔다
(`conversation_id`, `limit=100`, `before_sequence=None`, `after_sequence=None`).

**의미론:**

| 입력 | 돌려줄 것 |
|---|---|
| 커서 없음 | 마지막 N개 (ASC 정렬) |
| `before_sequence=S` | S 미만 중 **마지막** N개 (ASC) — 뒤로 페이지네이션 |
| `after_sequence=S` | S 초과 중 **처음** N개 (ASC) — 전방 따라잡기, 기존과 동일 |

**구현 지침:** `after_sequence`가 `None`일 때만 tail 경로를 쓴다. tail은 DESC로
N개를 고른 뒤 바깥에서 ASC로 되돌린다:

```sql
SELECT * FROM (
    SELECT <기존 24개 컬럼 그대로>
    FROM messages WHERE {where_sql}
    ORDER BY sequence_number DESC
    LIMIT $n
) recent
ORDER BY sequence_number ASC
```

바깥 `SELECT *`가 안쪽 컬럼 순서를 보존하므로 `Message(...)` 생성의 `row[N]`
인덱스는 손대지 않는다. `after_sequence` 경로는 기존 쿼리를 그대로 쓴다.
`where_sql`/파라미터 바인딩 구성 로직은 재사용한다 — `$n` 순번이 어긋나지 않게
주의할 것.

**테스트:** `tests/database/repositories/test_chat_repository_message_window.py` (신규)

⚠️ **`FakeDB`로 SQL 문자열을 검사하지 말 것.** 같은 디렉터리의
`test_chat_repository_pagination.py`가 그 방식을 쓰지만, 이번 버그는
`ORDER BY sequence_number ASC`가 **있어서** 생긴 버그다 — 문자열 검사는 원래
버그를 통과시킨다. 실제 DB에 행을 넣고 **무엇이 돌아오는지**로 검증한다.

DB는 도달 가능하다(확인함). `conftest.py`의 자동 정리 픽스처는
`email LIKE '%@example.com'`인 사용자에 딸린 conversation·message를 지우므로,
**테스트 사용자 이메일을 `...@example.com`으로** 만들어야 뒷정리가 된다.

고정할 것 (각각 별도 테스트):
- 메시지 25개 → `limit=20`, 커서 없음 → `sequence_number` 6..25가 **오름차순**으로
- 같은 데이터 → `limit=20, before_sequence=10` → 1..9 (9개, ASC)
- 같은 데이터 → `limit=5, before_sequence=20` → 15..19 (ASC)
- 같은 데이터 → `limit=5, after_sequence=10` → 11..15 (ASC, 기존 동작 불변)
- `limit`이 전체 개수보다 크면 전부 ASC로

**주의:** 첫 번째 테스트는 고치기 전엔 1..20을 받아 실패해야 한다. 그 실패를
보고서에 적는다.

**회귀:** `python -m pytest tests/ -q -p no:randomly` 전체를 돌린다. 이 함수는
호출부가 11곳이라 회귀 표면이 넓다. 현재 기준선은 **3518 passed, 63 skipped**다.

---

## Task 2 — 새로고침 후 첨부 복원 (FE)

**파일:** `web/lib/utils.ts`의 `convertBackendMessagesToUI`

BE `MessageResponse.attachments`(`{type, url, name, size, metadata}`)를 FE
file 파트로 되살린다. `parts` 배열은 지금 `text` 하나만 만든다 — 여기에 file
파트를 잇는다. 텍스트 파트가 먼저, 첨부가 뒤.

FE file 파트의 정본 모양은 **Task 3에서 정한 `filename`**을 쓴다:
`{ type: "file", url, filename, mediaType }`.

`mediaType`은 BE `attachment.metadata.mediaType`에 들어 있다
(`extractAttachments`가 그렇게 넣는다, `lib/message-parts.ts:97`). 없으면 생략.

**방어:** `attachments`가 없거나 배열이 아니거나 항목에 `url`이 없을 수 있다.
그런 항목은 조용히 건너뛴다 — 첨부 하나가 깨졌다고 메시지 렌더가 죽으면 안 된다
(이 저장소는 같은 이유로 `lib/harness/metadata.ts`에서 검증 실패 시 필드를
지운다).

**테스트:** `web/tests/source/` 에 신규 파일. 러너는
`pnpm test:source` (`tsx --test`). 같은 디렉터리의 기존 테스트 스타일을 따를 것.

고정할 것:
- 첨부 2개짜리 BE 메시지 → text 파트 1 + file 파트 2, 순서와 필드값
- `attachments: []` / 필드 없음 → file 파트 없음, 기존 동작 그대로
- `url` 없는 항목은 건너뛰되 나머지 첨부는 살아남는다
- `metadata.mediaType` 없으면 `mediaType`이 undefined여도 렌더가 죽지 않는다

---

## Task 3 — FE file 파트 필드명 통일 (`name` → `filename`)

**왜 `filename`인가:** `ChatMessage`는 AI SDK `UIMessage`이고 그 `FileUIPart`의
필드가 `filename`이다. 렌더러가 이미 `filename`을 읽고 있다. `name`을 쓰는 쪽이
소수이자 타입과 어긋나는 쪽이다.

**바꿀 곳 (FE 내부만):**
- `web/components/multimodal-input.tsx:145` — `name:` → `filename:`
- `web/app/(chat)/api/chat/schema.ts` — `filePartSchema`의 `name` → `filename`,
  `convertToOpenResponsesPart`/`convertToLegacyPart`의 대응 필드
- `web/lib/message-parts.ts` — `extractAttachments`의 legacy `file` 분기가
  `filePart.name`을 읽는 부분

**바꾸지 말 것:**
- BE로 나가는 `MessageAttachment`의 `name` 키 (Global Constraint 3)
- OpenResponses `input_file` 형식의 `file.name` — 그건 외부 스펙 필드다.
  `extractAttachments`의 `input_file` 분기는 그대로 둔다.

즉 경계는 이렇다: **FE 파트 = `filename`, 와이어(BE·OpenResponses) = `name`.**
`extractAttachments`가 그 변환 지점이다.

**테스트:** `web/tests/source/`에 기존 `message-parts` 테스트가 있으면 거기에,
없으면 신규. 고정할 것:
- legacy file 파트(`filename` 사용) → `BackendAttachment.name`으로 변환된다
- `input_file` 파트 → 여전히 `file.name`을 읽는다 (스펙 필드 불변)
- 작성기가 만든 파트가 `postRequestBodySchema.parse`를 통과한다

**주의:** 이 태스크는 Task 2가 쓰는 필드명을 정한다. Task 2와 Task 3은 같은
`filename` 결정을 공유하므로 어긋나면 안 된다.

---

## 완료 기준

- `python -m pytest tests/ -q -p no:randomly` → 3518+ passed, 회귀 0
- `pnpm test:source` → 231+ passed, 회귀 0
- 20턴 넘는 대화에서 LLM 히스토리가 최근 20개다
- 100턴 넘는 대화를 새로고침하면 최신 100개가 보인다
- 첨부가 새로고침 후에도 파일명과 함께 보인다
