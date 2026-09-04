# LLM 입력 정확성 (중복 턴 · 모델 선택) + 편집 시 첨부 보존

FE↔BE 감사의 6번과, 감사 작업 중 발견된 두 건을 닫는다. 1·2·3·5·4a·7·8은 완료됐다.
멀티모달(#4b)은 이 계획에 없다 — 설계부터 잡아야 해서 별도로 간다.

## Global Constraints

1. **LLM에 들어가는 메시지 배열이 바뀐다.** 세 태스크 중 둘이 그렇다. 각 변경은
   "무엇이 모델에 도달하는가"를 고정하는 테스트로 증명해야 한다 — 함수가
   호출됐다가 아니라 **전달된 메시지 목록의 내용**을 본다.
2. **새 테스트는 고치기 전에 빨갛게 만들고** 실패 출력(기대 대 실제)을 보고서에
   그대로 붙인다. "모듈이 없다" 류의 실패는 증거가 아니다 — 그것은 새 파일이라는
   증명일 뿐이다(지난 배치에서 이 함정에 빠졌다).
3. 프로덕션 의미를 테스트에 맞추지 않는다. 반대도 같다.
4. 커밋에 `Co-Authored-By` 트레일러 금지.
5. 자기 태스크가 소유한 파일 밖을 수정하지 않는다.

---

## Task 1 — 사용자 턴이 LLM에 두 번 들어간다

**소유 파일:** `neos/api/services/chat_stream_pipeline.py`,
`neos/api/handlers/chat_handlers.py`, `neos/api/handlers/rag_chat_handlers.py`,
`neos/api/services/chat_message_processor.py`

### 무엇이 깨져 있나

다섯 호출부가 전부 같은 구조다 — **① 사용자 메시지 저장 → ② 히스토리 조회 →
③ `history + [{"role":"user","content": ...}]`**. 히스토리 조회가 tail이 된 뒤
(2026-09-03 `6db93c8a`) ②가 방금 저장한 그 메시지를 **항상 포함**하므로 ③이 그것을
한 번 더 붙인다.

| 위치 | append 라인 |
|---|---|
| `chat_stream_pipeline.py` | 250 |
| `chat_handlers.py` | 454 |
| `rag_chat_handlers.py` | 88 |
| `chat_message_processor.py` | 413 (`generate_llm_response`) |
| `chat_message_processor.py` | 438 (`generate_llm_response_stream`) |

다섯 곳 모두 ①이 ② 앞에서 `await`된다 — 확인했다. `chat_message_processor`의
히스토리는 인자로 들어오지만, 그것을 만드는 `process_message`(`:55-75`)가 같은
순서를 지킨다.

**이것은 tail 변경이 만든 결함이 아니라 드러낸 결함이다.** 전에도 20턴 이하
대화(흔한 경우)에서는 똑같이 중복됐고, 긴 대화는 *완전히 틀린 맥락*을 보내서
중복을 면했을 뿐이다. 그래도 지금은 모든 챗 턴에서 무조건 발생한다.

### 고칠 것

수동 append를 제거한다. 히스토리가 이미 그 유저 턴으로 끝난다.

⚠️ **`limit`을 하나 늘리지 말 것.** "유저 메시지가 자리를 하나 먹으니 21개를
읽자"는 유혹이 있는데, 그러면 컨텍스트 예산이 조용히 늘어난다. 20은 20이다.

⚠️ **`chat_message_processor`의 두 메서드는 `user_content` 파라미터를 계속
받는다** — 시그니처는 서브클래스(`standard_chat_processor`·
`similarity_chat_processor`)가 오버라이드하는 계약이다. 파라미터를 지우지 말고,
메시지 배열을 만들 때 쓰지 않기만 한다. 서브클래스가 오버라이드하고 있는지
확인하고, 하고 있다면 거기도 같은 처리가 필요한지 보고서에 적을 것.

### 테스트

각 경로에서 **LLM에 전달된 `conversation_messages`(또는 `messages`)를 포착**해
그 내용을 검증한다. 최소한:

- 히스토리 마지막이 유저 메시지일 때, 전달 배열에 그 내용이 **한 번만** 있다
- 배열의 마지막 원소가 그 유저 턴이다 (순서 보존)
- 히스토리가 비어 있을 때도 유저 턴이 유실되지 않는다

`chat_stream_pipeline`은 `tests/api/services/test_chat_stream_pipeline_autonomy.py`가
페이크로 파이프라인을 돌리는 방식을 이미 갖고 있다 — 참고할 것.
`chat_message_processor`의 두 메서드는 순수하게 가까우니 직접 부를 수 있다.

---

## Task 2 — 모델 선택이 대화 생성 시점에 고정된다 (#6)

**소유 파일:** `web/app/(chat)/api/chat/route.ts`,
`neos/api/services/chat_stream_pipeline.py`

⚠️ Task 1도 `chat_stream_pipeline.py`를 만진다. **Task 1이 먼저 끝난 뒤 시작한다.**

### 무엇이 깨져 있나

FE는 매 메시지 `metadata.model`을 보내지만 BE에서 읽는 곳이 **없다**. 모델은
`conversation.get("model_name")`(`chat_stream_pipeline.py:259`)으로만 정해지고,
그 값은 대화 생성 시 한 번 박힌다. 기존 대화에서 셀렉터를 바꿔도 무시된다.

게다가 형식도 어긋나 있다 — 대화 생성 시엔 `mapToBackendModelName(...)`을 보내는데
(`route.ts:88`), 매 메시지엔 **매핑 안 된 게이트웨이 ID**를 보낸다(`:138`).
BE가 읽었더라도 백엔드 모델명이 아니라 동작하지 않았을 것이다.

### 고칠 것 — FE

`route.ts:138`이 `mapToBackendModelName(selectedChatModel)`을 보내도록 한다.
`:88`과 같은 함수를 쓴다(은퇴 모델 매핑 `RETIRED_MODEL_MAP`이 거기 들어 있다).

### 고칠 것 — BE

`chat_stream_pipeline`이 이 턴의 모델을 고를 때 `request_metadata.get("model")`을
우선 쓰고, 없으면 기존대로 `conversation["model_name"]`으로 떨어진다.

🔴 **반드시 검증할 것.** 이것은 사용자가 통제하는 문자열이 모델 라우팅에 도달하는
경로다. 카탈로그에 없는 이름이면 **받아들이지 말고** `conversation["model_name"]`으로
떨어진다. 모델 사실의 단일 원천은 `neos/config/models.yaml`이고 조회 경로는
`neos/config/model_routing.py`다 — 거기 이미 있는 것을 쓰고 새 검증기를 만들지 말 것.
검증에 실패하면 조용히 넘어가지 말고 `logger.warning`을 남긴다.

**설계 결정 (이 계획의 판단, 되돌리기 쉬움):** 이 오버라이드는 **그 턴에만**
적용하고 `conversation.model_name`에 **쓰지 않는다.** 이유 — FE 셀렉터는
`chat-model` 쿠키 기반의 **전역 기본값**이라(`actions.ts:10`,
`chat/[id]/page.tsx:66`) 대화별 상태가 아니다. 매 메시지에 현재 셀렉터 값이
그대로 실려 오므로 "바뀔 때만 저장"은 "항상 저장"과 같아지고, 그러면
`conversation.model_name`이 쿠키를 따라다니는 의미 없는 필드가 된다. 생성 시
모델은 그 대화가 무엇으로 시작됐는지의 기록으로 남긴다.

### 테스트

- `metadata.model`이 카탈로그의 유효한 모델이면 LLM 호출이 그것을 받는다
- `metadata.model`이 없으면 `conversation.model_name`을 받는다
- 🔴 **`metadata.model`이 카탈로그에 없는 값이면 무시되고 대화 모델로 떨어진다** —
  임의 문자열이 프로바이더에 도달하지 않는 것이 이 태스크의 보안 경계다
- FE: `route.ts`가 보내는 `metadata.model`이 매핑된 백엔드 모델명이다
  (`web/tests/source/`에, 은퇴 모델 하나를 포함해서)

---

## Task 3 — 편집하면 첨부가 사라진다 + 잔여 부채

**소유 파일:** `web/components/message-editor.tsx`, `web/components/message.tsx`,
`web/app/(auth)/auth.ts`, `web/tests/source/approval-stream-proxy.test.ts`

### 3a. 편집 시 첨부 유실 (본체)

`message-editor.tsx:93`이 `parts`를 텍스트 파트 하나로 갈아치워 file 파트를
버린다. 4a(`b8094698`)로 새로고침 후 첨부가 복원되기 시작하면서 **도달 가능해진**
경로다 — 첨부 있는 메시지를 편집하면 미리보기가 사라진다.

고칠 것: 편집이 텍스트만 바꾸고 **file 파트는 보존**하게 한다. 텍스트 파트가
먼저, 첨부가 뒤 — 복원 경로(`lib/utils.ts`)가 만드는 순서와 같게 맞춘다.

테스트: `web/tests/source/`에. 첨부 있는 메시지를 편집해도 file 파트가 살아남고,
첨부 없는 메시지의 기존 동작은 그대로인 것.

### 3b. 승인 실패 메시지가 화면에 도달하지 않는다

`message.tsx`의 catch가 `outcome.message`를 버려서 백엔드의
`"워크플로우 응답 대기 타임아웃"` 대신 정적 문구 `"Approval response failed"`만
뜬다. 3번 수정으로 타임아웃이 **실패로는** 보이게 됐으나 **왜인지**는 여전히
안 보인다. 있는 메시지를 표시한다.

### 3c. 죽은 린트 억제 5개

`approval-stream-proxy.test.ts`의 `// biome-ignore lint/suspicious/noExplicitAny`
다섯 개는 무력하다 — `noExplicitAny`가 프로젝트 전역 `off`라
(`web/biome.jsonc:16`) biome가 `suppressions/unused`로 잡는다. 지난 수정 웨이브가
`auth.ts`에서 같은 것을 지우면서 이 파일에 새로 만들었다. 지운다.

### 3d. 안 읽는 파라미터

`auth.ts:81-92`의 `computeAccessTokenExpiry`가 `trigger`를 받고 쓰지 않는다.
분기는 `params.user`의 truthiness가 정한다. 파라미터를 지우거나, 실제로 분기에
쓰거나 — 둘 중 하나로 정리한다. 지금 동작은 옳으므로 **동작을 바꾸지 말 것.**

---

## 완료 기준

- `python -m pytest tests/ -q -p no:randomly` → 3526+ passed, 회귀 0
- `cd web && pnpm test:source` → 268+ passed, 회귀 0
- `cd web && pnpm exec tsc --noEmit` · `tsc -p tsconfig.test.json` clean
- `cd web && pnpm exec biome check app/\(auth\)/auth.ts tests/source/approval-stream-proxy.test.ts`
  에 `suppressions/unused` 없음
- 사용자 턴이 LLM 입력에 정확히 한 번 들어간다
- 기존 대화에서 모델을 바꾸면 그 턴부터 반영된다. 카탈로그 밖 이름은 무시된다
- 첨부 있는 메시지를 편집해도 첨부가 남는다
