# 모델 경계 일원화 · RAG 라우터 인증 · 워크플로우 히스토리 중복

세 건 모두 앞선 작업이 드러낸 것이다. 멀티모달(#4b)은 이 계획에 없다 — 설계를
먼저 잡고 별도 계획으로 간다.

## Global Constraints

1. **새 검증기를 만들지 않는다.** 모델 접근 판정은 이미 있다
   (`chat_stream_pipeline._is_user_selectable_model`). 규칙이 둘이 되는 순간
   이번에 고치는 문제가 재발한다.
2. **새 테스트는 고치기 전에 빨갛게 만들고** 실패 출력(기대 대 실제)을 보고서에
   그대로 붙인다. "임포트 실패"는 증거가 아니다 — 새 파일이라는 증명일 뿐이다.
3. 프로덕션 의미를 테스트에 맞추지 않는다. 반대도 같다.
4. 자기 태스크가 소유한 파일 밖을 수정하지 않는다.
5. 커밋에 `Co-Authored-By` 트레일러 금지.

---

## Task 1 — 모델 경계를 세 문에 하나의 규칙으로

**소유 파일:** `neos/config/model_config.py`,
`neos/api/services/chat_stream_pipeline.py`, `neos/api/handlers/chat_handlers.py`

### 무엇이 깨져 있나

턴 오버라이드는 `selectable` 게이트를 통과해야 하지만
(`chat_stream_pipeline.py:140`), 같은 모델 문자열을 받는 **다른 두 경로는 검증이
전혀 없다**:

- `POST /api/v1/chat/conversations` → `CreateConversationRequest.model_name`
  (`chat_models.py:55` → `chat_handlers.py:135`)
- `POST /api/v1/chat/messages/{id}/regenerate` → `RegenerateMessageRequest.model_name`
  (`chat_models.py:105` → `chat_handlers.py:646`)

둘 다 임의 문자열을 그대로 `LLMFactory`에 넘긴다. 즉 인증된 사용자가 대화를
`claude-opus-4-8`(심층분석 판정자 전용, 가격 미검증)로 만들면 그 모델에 닿고,
그 값이 이후 턴의 **폴백**이 되므로 오버라이드 게이트를 우회한다.

### 고칠 것

**① 게이트를 공유 위치로 옮긴다.** `_is_user_selectable_model`은 지금
`chat_stream_pipeline.py`의 private 함수다. 이것을 `neos/config/model_config.py`로
옮겨 공개 함수로 만든다 — 카탈로그 사실을 판정하는 함수이므로
`models_for_provider()` 옆이 제자리다. `chat_stream_pipeline`은 그것을 임포트해
쓰고, **동작은 그대로**여야 한다(기존 테스트가 그것을 고정하고 있다).

**② 두 핸들러에 같은 게이트를 건다.**

- `create_conversation`: `model_name`이 **명시적으로 주어졌을 때만** 검증한다.
  생략되면 기존대로 서비스 기본값이 정한다 — 요청에 없는 값을 거부하면 안 된다.
  `CreateConversationRequest.model_name`의 기본값이 무엇인지 먼저 확인할 것.
- `regenerate_message`: `request.model_name`이 주어졌을 때만 검증한다.

**거부 방식:** 이 둘은 스트림이 아니라 일반 요청이므로 조용히 폴백하지 말고
**400으로 거부**하고 이유를 담는다. 스트리밍 경로가 폴백하는 것은 턴을 죽이지
않기 위해서였다 — 여기는 그 제약이 없고, 요청이 틀렸다고 말해주는 편이 낫다.
단 **어떤 모델이 존재하는지 흘리지 말 것** — "선택할 수 없는 모델"과 "없는
모델"을 같은 메시지로 응답한다.

### 테스트

`tests/api/handlers/`에. 고정할 것:
- `selectable: false` 실제 카탈로그 id(`claude-opus-4-8`)로 대화 생성 → 400
- 없는 모델 이름으로 대화 생성 → 400, **같은 메시지**
- `model_name` 생략 → 기존대로 성공
- 정상 모델(`claude-sonnet-5`) → 성공
- regenerate도 같은 네 가지
- 게이트 이동 후에도 파이프라인의 기존 오버라이드 테스트가 그대로 통과

---

## Task 2 — RAG 라우터에 인증을 붙인다

**소유 파일:** `neos/api/handlers/rag_chat_handlers.py`

### 무엇이 깨져 있나

이 파일의 **7개 라우트 전부 인증 의존성이 없다.** 형제인
`similarity_chat_handlers.py`는 모든 대화 라우트에
`Depends(get_owned_conversation)` + `Depends(get_current_active_user)`를 걸고
있다 — 즉 누락이지 설계가 아니다.

⚠️ **지금 악용 가능한 취약점은 아니다.** `neos/api/rag_chat_routes.py`가 라우터를
재수출하지만 아무도 그것을 임포트하지 않아, 실행 중인 앱에 `/rag` 경로가 0개다
(앱을 띄워 `openapi()`를 열거해 확인함). 이것은 **지뢰**다 — `include_router` 한
줄이면 인증 없는 엔드포인트 7개가 살아난다.

### 고칠 것

형제 라우터와 **같은 의존성**을 건다. 라우트별 매핑:

| 라우트 | 의존성 |
|---|---|
| `POST /conversations/{id}/messages/rag` | `get_owned_conversation` |
| `POST /conversations/{id}/messages/rag/stream` | `get_owned_conversation` |
| `POST /conversations/{id}/search` | `get_owned_conversation` |
| `POST /users/{user_id}/search` | `require_same_user_id` |
| `POST /messages/{message_id}/embedding` | `get_owned_message` |
| `GET /users/{user_id}/embeddings/stats` | `require_same_user_id` |
| `DELETE /messages/{message_id}/embedding` | `get_owned_message` |

의존성은 `neos/api/dependencies/resource_access.py`에 이미 있다 — 새로 만들지 말
것. 핸들러가 이미 `conversation`을 다시 조회하고 있다면, 의존성이 돌려주는
authorized 객체를 쓰도록 정리해 **조회가 두 번 일어나지 않게** 한다.

**라우터를 마운트하지 말 것.** 이 태스크는 인증을 붙이는 것까지다. 마운트는
그 기능을 실제로 켤 때의 결정이다.

### 테스트

`tests/api/handlers/`에. 이 저장소에는 이미 인증 행렬을 고정하는 본이 있다 —
`tests/api/handlers/test_chat_authorization.py`가 라우트별 의존성 이름을
대조한다. 그 방식을 따라 **7개 라우트 전부**가 기대한 의존성을 갖는지 고정한다.
"몇 개"가 아니라 **경로 이름으로** 검증할 것 — 개수는 누가 빠졌는지 말해주지
않는다.

---

## Task 3 — 워크플로우에 현재 턴이 두 번 들어간다

**소유 파일:** `neos/api/services/chat_stream_pipeline.py`

### 무엇이 깨져 있나

`_run_workflow`가 워크플로우에 넘기는 입력에서, 현재 사용자 질문이 두 자리에
동시에 들어간다 — `query=user_content`이고, `chat_history`의 마지막 원소도 그
메시지다(히스토리가 tail이라 방금 저장한 턴을 포함한다).

Task 1(`ce12b080`)이 LLM 입력에서 고친 것과 **같은 모양이 다른 자리에 남아
있는 것**이다. 그 계획은 이 지점을 열거하지 않았다.

두 번째 문제: 슬라이스가 `history_messages[: MAX_HISTORY_MESSAGES]`라 **tail의
앞에서** 자른다. 즉 "최근 N개"를 의도한 자리에서 가장 오래된 N개를 준다 —
2026-09-03에 리포지토리에서 고친 것과 같은 방향 오류다.

### 고칠 것

- `chat_history`에서 **현재 턴을 제외한다.** 그것은 `query`가 나른다.
- 슬라이스를 **뒤에서** 취해 정말 최근 N개가 가게 한다. 반환 순서는 지금처럼
  오름차순을 유지한다(소비자가 시간순을 가정한다).

⚠️ `MAX_HISTORY_MESSAGES`를 바꾸지 말 것. 자르는 **방향**만 고친다.

### 테스트

`tests/api/services/test_chat_stream_pipeline_autonomy.py`가 이미 `_run_workflow`를
페이크로 돌린다. 워크플로우에 전달된 `user_input`을 포착해 고정할 것:
- `chat_history`에 현재 질문이 **없다**
- 히스토리가 `MAX_HISTORY_MESSAGES`보다 길면 **최근** N개가 간다 (오름차순)
- `query`는 그대로 현재 질문이다

---

## 완료 기준

- `python -m pytest tests/ -q -p no:randomly` → 3542+ passed, 회귀 0
- `cd web && pnpm test:source` → 276 passed (이 계획은 FE를 건드리지 않는다)
- 세 문이 같은 규칙 하나를 공유한다 — 게이트 함수가 하나뿐이다
- RAG 라우터 7개 전부 인증 의존성을 갖는다 (마운트는 하지 않는다)
- 워크플로우가 받는 `chat_history`에 현재 턴이 없고, 최근 N개다
