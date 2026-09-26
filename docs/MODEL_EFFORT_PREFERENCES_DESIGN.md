# 모델별 사고량(effort) 기본값과 사용자 설정 — 설계

> **구현 전 산출물이다 (2026-09-24).** 구현이 끝나면 운영 정본은
> `docs/CONFIGURATION.md` 의 Model Routing 절이 된다. 둘이 어긋나면 그쪽이 이긴다.

## 1. 목표

1. **운영자**가 모델마다 effort 기본값을 설정 파일로 정한다.
2. **사용자**가 프론트엔드에서 모델마다 effort 를 고른다.
3. 사용자의 선택은 **백엔드 DB** 에 저장되고, 웹·채널·API 어느 경로로 들어온 대화에도 같이 걸린다.

"effort" 는 프로바이더 API 의 사고량 파라미터다 — Anthropic `output_config.effort`,
OpenAI `reasoning_effort`. 심층분석의 `Effort`(scout/dig/synth, 조사 깊이)와는 **다른 축**이다.

### 성공 기준

- 설정 파일에 `claude-opus-5-5: high` 를 적으면, 사용자 설정이 없는 모든 Opus 5.5 채팅 턴이
  `output_config: {effort: "high"}` 를 보낸다.
- 사용자가 피커 옆에서 `xhigh` 를 고르면 그 사용자의 그 모델 턴은 `xhigh` 로 간다.
  새로고침·다른 기기·채널에서도 유지된다.
- 아무도 정하지 않은 모델은 **지금과 똑같이** 아무 키도 보내지 않는다.
- 잘못된 사용자 설정은 적용되지 않을 수 있어도 채팅 턴을 실패시키지 않는다.

### 범위 밖 (YAGNI)

- 대화별 effort UI (사슬에 자리는 있다 — `conversation_effort`)
- 모델별 기본값을 고치는 관리자 UI
- effort 외의 모델별 설정(temperature 등)

## 2. 지금 상태 (2026-09-24 확인)

- `resolve_effort()` (`neos/config/model_routing.py`) 가 user → conversation → feature
  override → role default 사슬을 구현한다. 쓰는 곳은 심층분석과 코딩 루프뿐이다.
- 카탈로그의 `effort_levels` 를 선언한 모델이 **하나도 없다.** 게이트가 전부
  `model_declares_no_effort` 로 거절하므로 지금은 어디서도 effort 가 나가지 않는다.
- 채팅 경로는 effort 를 보내지 않는다. OpenAI 경로도 reasoning 파라미터를 보내지 않는다.
- 피커의 모델 선택은 `chat-model` **쿠키**에만 저장된다. 사용자 선호를 저장하는 테이블은 없다.
- 채팅 진입점은 넷이고 호출 방식은 둘이다.

| 진입점 (`neos/services/chat_llm_service.py`) | 호출 방식 | 프로바이더 |
|---|---|---|
| `generate_response` | `create_llm()` → LangChain | Anthropic, OpenAI |
| `generate_response_stream` | `create_llm()` → LangChain | Anthropic, OpenAI |
| `generate_response_stream_with_tools` | Anthropic SDK `messages.stream` | Anthropic (그 외는 위로 위임) |
| `generate_response_stream_with_tool_search` | Anthropic SDK `messages.stream` | Anthropic (그 외는 위로 위임) |

## 3. 선택한 접근: 백엔드 DB 저장 + 백엔드 해석

프론트는 설정을 읽고 쓰기만 한다. 채팅 요청에 effort 를 싣지 않는다. 백엔드가 턴마다
(사용자, 모델)로 DB 를 조회해 `resolve_effort` 의 `user_effort` 칸에 넣는다.

기각한 대안:
- **프론트 DB(Drizzle) 저장 + 요청마다 전송** — 설정이 웹에만 있어 채널이 모르고,
  백엔드가 요청 값을 믿어야 한다.
- **양쪽 저장** — 진실의 원천이 둘이고, 어긋날 때 누가 이기는지 정해야 한다.

## 4. 설정과 데이터 모델

### 4.1 어휘 — 프로바이더별로 나눈다

지금의 전역 `EFFORT_LEVELS` 를 프로바이더별 어휘로 나눈다. 목록은 손으로 쓰지 않고
SDK 의 Literal 과 같아야 한다 (테스트가 잠근다).

| 프로바이더 | 어휘 | 출처 |
|---|---|---|
| `anthropic` | `low, medium, high, xhigh, max` | `anthropic.types.OutputConfigParam.effort` |
| `openai` | `none, minimal, low, medium, high, xhigh, max` | `openai.types.shared.ReasoningEffort` |

### 4.2 카탈로그 (사실) — `neos/config/models.yaml`

각 모델의 `effort_levels` 를 채운다. 그 모델 프로바이더 어휘의 부분집합이어야 하고,
아니면 로더가 거부한다.

- **Anthropic:** models API 의 `capabilities.effort` 로 확인한 값만 적는다. 키가 동작한다
  (2026-09-23 실호출 확인).
- **OpenAI (Sol/Luna):** OpenAI 공식 models 문서의 `none, low, medium, high, xhigh, max`.
- 확인하지 못한 모델(Gemini, Ollama, 레거시)은 비워 둔다 = "모른다" = 보내지 않는다.

### 4.3 설정 (정책) — `config/neos.*.yaml`

```yaml
model_routing:
  effort:
    everyday: null        # 기존 역할 기본값
    powerful: null
    models:               # 신규: 모델별 기본값
      claude-opus-5-5: high
      gpt-6-sol: medium
```

- 키는 카탈로그 핀이다. 로드 시 (핀이 카탈로그에 있다) + (레벨이 그 모델의
  `effort_levels` 안이다) 를 둘 다 검사한다. 오타는 **부팅 실패**다.
- 항목이 없으면 지금 동작 그대로 아무것도 보내지 않는다 — 모델의 서버 기본값을 쓴다
  (Opus 5.5 의 서버 기본값은 `medium`, Opus 5 보다 한 단계 낮다).
- 이 블록의 값을 바꾸는 것은 심층분석 표본 경계다 (로드맵 §경계 10). `RoleEffortConfig`
  독스트링의 규칙이 그대로 적용된다.

### 4.4 DB (사용자 설정) — 백엔드 마이그레이션 `063`

```sql
CREATE TABLE IF NOT EXISTS user_model_preferences (
    user_id    VARCHAR(255) NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    model_pin  VARCHAR(100) NOT NULL,
    effort     VARCHAR(20)  NOT NULL,
    updated_at TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, model_pin)
);
```

- `model_pin` 은 정규화한 카탈로그 핀이다. 저장 전에 `canonicalize` (remaps · `retired:`
  포함)를 거친다. gateway id 나 은퇴한 핀으로 저장되지 않는다.
- `effort` 에는 DB 제약을 걸지 않는다. 모델이 나중에 레벨을 잃으면 해석기의 게이트가
  그 값을 거절하고 사유를 남긴다 (`_gate_effort` 가 옛 DB 행에 이미 하는 일). 저장할 때는 검증한다.
- 설정별로 컬럼을 두는 형태다. 모델별 설정이 늘면 컬럼을 더한다.
- 새 마이그레이션 파일은 번호순으로 자동 포함된다. `scripts/verify_schema_bootstrap.py
  --check-list-only` 로 확인한다.

### 4.5 우선순위

user×모델 (DB) → 대화 → 기능 오버라이드 → **모델별 기본값 (신규)** → 역할 기본값 → 안 보냄

모델별 기본값은 역할 기본값보다 구체적이므로 그 위에 둔다.

## 5. 백엔드

### 5.1 해석기 하나 — `neos/services/chat_effort.py`

`resolve_chat_effort(model, conversation_id) -> EffortResolution`

1. `conversations` 와 `user_model_preferences` 를 `conversation_id` 로 조인해 한 번에 읽는다 →
   `user_effort`. 소유자 조회(`ChatRepository.get_conversation`)를 따로 하지 않는다 — 첨부 없는
   턴이 conversations 를 읽지 않는다는 기존 보장(Fix round 2 Item 2, `tests/services/
   test_chat_llm_owner_lazy_resolution.py`)을 지키기 위해서다. 모델이 `effort_levels` 를
   선언하지 않았으면 조회하지 않는다.
2. 모델별 기본값은 `config.model_routing.effort.models[model]`, 역할 기본값은 기존 설정에서 읽는다.
3. 둘을 기존 `resolve_effort()` 에 넣는다. 같은 사슬, 같은 `_gate_effort` 가 모르는·미지원
   레벨을 처리한다. **두 번째 사슬을 만들지 않는다.**
   - `resolve_effort` 에 모델별 기본값 칸을 더한다. 기능 오버라이드와 역할 기본값 사이다.
     `ResolutionSource` 에 `MODEL_DEFAULT` 를 더한다.
4. DB 조회가 실패하면 (DB 다운) 경고를 남기고 사용자 설정이 없는 것으로 진행한다.

### 5.2 요청 번역 하나 — `effort_request_fields(provider, effort) -> dict`

| provider | 결과 |
|---|---|
| `anthropic` | `{"output_config": {"effort": e}}` |
| `openai` | `{"reasoning_effort": e}` |
| `effort is None` | `{}` — 키를 아예 넣지 않는다. `null` 도 보내지 않는다 |

적용하는 곳:
- `AnthropicProvider.create_llm` / `OpenAIProvider.create_llm` 이 kwargs 로 `effort=` 를 받아
  번역 결과를 합친다 → `generate_response`, `generate_response_stream`.
- Anthropic SDK 경로 둘은 `stream_kwargs` 에 합친다.

### 5.3 진입점을 한 경로로

네 진입점이 각자 `resolve_conversation_chat_model` + `_extract_provider_from_model` 을 부른다.
그 둘에 effort 해석을 더한 `_resolve_turn(model_name, conversation_id) -> TurnModel(model,
provider, effort)` 을 하나 두고 넷이 모두 그것을 쓰게 한다. tool 경로가 비-Anthropic 모델을
`generate_response_stream` 으로 위임할 때는 해석된 값을 넘겨 두 번 해석하지 않는다.

### 5.4 thinking 과의 관계

- Anthropic 에서 effort 는 `thinking: adaptive` 와 함께 간다. 충돌하지 않는다.
- `_translate_thinking_off()` (`neos/providers/anthropic.py`) 의 TODO 에 답한다:
  `thinking_always_on` 모델에서 "끄기" 는 **그 모델의 `effort_levels` 가 `low` 를 포함할 때만**
  `effort: low` 로 번역한다. 포함하지 않으면 지금처럼 adaptive 만 보낸다.
- 해석된 effort 가 이미 있으면 (사용자·설정이 정했으면) "끄기" 번역이 그것을 덮어쓰지 않는다.
  명시적 설정이 이긴다.

### 5.5 관측

턴마다 effort 의 출처(user / conversation / feature_override / model_default /
role_default / none)와 거절 사유를 로그로 남긴다. 메트릭 `neos_chat_effort_resolved_total`
의 라벨은 출처만 쓴다.

## 6. API

새 라우터 `neos/api/handlers/model_preference_handlers.py` (기존 `autonomy_handlers.py` 와 같은 자리). 인증은 `get_current_user`.

| 메서드 · 경로 | 동작 |
|---|---|
| `GET /api/v1/users/me/model-preferences` | `[{model, effort, updated_at}]` |
| `PUT /api/v1/users/me/model-preferences/{model}` body `{effort}` | 정규화 → 검증 → upsert |
| `DELETE /api/v1/users/me/model-preferences/{model}` | 행 삭제 = 기본값으로 |

- `{model}` 은 gateway id(`anthropic/claude-opus-5.5`)도 받는다. 경로에 `/` 가 있으므로
  경로 파라미터는 `{model:path}` 로 선언한다.
- 모르는 모델 → 404. 그 모델이 받지 않는 레벨 → 422, 본문에 허용 레벨 목록.

### 피커 페이로드 (`GET /models`, `PickerModel`)

행마다 다음을 더한다.
- `effort_levels: string[]` — 카탈로그
- `effort_default: string | null` — 설정의 모델별 기본값

프론트는 어떤 모델이 어떤 레벨을 받는지 하드코딩하지 않는다. 커밋된 폴백
(`web/lib/ai/catalog.generated.ts`)은 `scripts/generate_catalog_fallback.py` 로 재생성한다
(CI 가 신선도를 검사한다).

## 7. 프론트엔드

- **Next 라우트 핸들러** `web/app/(chat)/api/model-preferences/route.ts` — GET/PUT/DELETE 를
  `session.backendAccessToken` 으로 백엔드에 프록시한다 (`api/files/upload` 와 같은 패턴).
  브라우저가 백엔드를 직접 부르지 않는다.
- **effort 선택기** — `multimodal-input.tsx` 의 모델 피커 옆.
  - 작은 드롭다운. 선택지는 "기본값 (high)" + 선택된 모델의 `effort_levels`.
  - `effort_levels` 가 비면 숨긴다.
  - 바꾸는 즉시 PUT (낙관적 업데이트, 실패하면 되돌리고 토스트). "기본값" 은 DELETE.
  - 채팅 화면 진입 시 GET 한 번으로 선호를 읽고, 모델을 바꾸면 그 모델의 저장값을 보여준다.
- **채팅 요청은 바뀌지 않는다.**
- **라벨**은 API 어휘를 그대로 보인다 (`low`, `xhigh`, …). 레벨 이름과 UI 사이 번역층은
  드리프트의 새 원천이라 만들지 않는다.
- 게스트 사용자도 백엔드 `users` 행이 있으므로 똑같이 동작한다.

## 8. 오류 처리

| 상황 | 동작 |
|---|---|
| 설정 `effort.models` 오타 (모르는 핀 · 미지원 레벨) | **부팅 실패** |
| DB 행의 레벨을 모델이 더는 받지 않는다 | 게이트가 거절(`level_not_supported`) → 다음 칸으로 → 출처와 함께 경고 |
| DB 조회 실패 | 사용자 설정 없음으로 진행 + 경고. 턴은 계속된다 |
| PUT 에 모르는 모델 · 레벨 | 404 / 422, 허용 목록과 함께. 저장하지 않는다 |
| 프론트 PUT 실패 | 낙관적 업데이트 롤백 + 토스트. 채팅은 영향 없음 |
| 프로바이더가 effort 를 400 으로 거절 | 숨기지 않는다. 평소 오류로 드러난다 — 조용히 빼고 재전송하면 설정과 실제가 달라진다 |

## 9. 테스트

- **어휘 잠금:** 프로바이더별 어휘 = 두 SDK 의 Literal (기존 `test_model_effort.py` 대체).
- **카탈로그 검증:** 어휘 밖 `effort_levels` 거부. 설정 `effort.models` 의 모르는 핀 ·
  미지원 레벨 거부.
- **해석기:** 사슬 각 칸의 우선순위, 낡은 DB 레벨 통과, DB 예외 통과, 아무 설정 없음 →
  `effort=None`.
- **배선 — 네 진입점 전부:** 파라미터화한 테스트로 각 진입점에서 effort 가 나가는 요청에
  도착하는지 확인한다 (Anthropic `output_config`, OpenAI `reasoning_effort`).
  `effort=None` 이면 키가 **없는지** 확인한다.
- **thinking 끄기 번역:** `low` 를 받는 always-on 모델은 `effort: low`, 받지 않으면 adaptive
  만, 명시적 effort 가 있으면 그것이 이긴다.
- **API:** GET/PUT/DELETE, 인증 없음 401, 404/422, upsert, gateway id 와 은퇴한 핀의 정규화 저장.
- **DB:** 부트스트랩 순서 포함, PK upsert. 로컬 통합 테스트는 부트스트랩된 DB 가 필요하다.
- **프론트 (`web/tests/source`):** 레벨이 없으면 선택기 숨김, "기본값" 은 DELETE, PUT 실패 롤백,
  생성된 폴백의 새 필드.
- **실호출:** Opus 5.5 · Sonnet 5 에 `output_config.effort` 가 받아지는지 Anthropic 실호출로 확인한다.

## 10. 열린 위험

1. **OpenAI 실호출 미검증.** `OPENAI_API_KEY` 가 401 이다 (DECISIONS 기록). reasoning 모델은
   effort 가 `none` 이 아닐 때 `temperature` 를 거부할 수 있다. OpenAI 경로는 SDK 타입 대비
   단위 테스트로만 검증되고, 키가 고쳐질 때까지 실호출 확인은 열려 있다.
2. **은퇴한 모델의 선호.** `claude-opus-5` 로 저장된 옛 행은 `claude-opus-5-5` 와 매칭되지 않는다.
   저장 시 정규화하므로 새 행은 문제없다. 옛 행은 매칭되지 않을 뿐이고 데이터 이관은 하지 않는다.
