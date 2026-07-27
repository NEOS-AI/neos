# 모델 카탈로그 config화 설계

**작성일:** 2026-07-26
**상태:** ✅ **구현 완료** (2026-07-27, `783fe864..88dea3ab`)
**목표:** Claude·GPT 등 모델에 관한 사실(지원 목록, 추천 티어, 요청 계약, 가격)을
`neos/config/models.yaml` 한 곳에서 관리한다. 새 모델 추가가 **config 변경만으로** 끝나야 한다.

> **이 문서는 구현 전 설계다.** 현재 동작의 정본은
> [CONFIGURATION.md](../../CONFIGURATION.md)의 **Model Catalog** 절이다.
> 구현하며 아래 세 가지가 이 설계와 달라졌다.
>
> | 이 문서 | 실제 구현 | 이유 |
> |---|---|---|
> | §3 `tier: <스칼라>` | **`tiers: [<티어>, ...]` 리스트** | 현행 `get_recommended_models()`가 한 모델을 두 티어에 매핑한다 (gemini `balanced`==`powerful`, ollama `fast`==`balanced`). 스칼라로는 전사 불가. 부수 이득으로 "(provider, tier)당 모델 1개" 검증기가 가능해졌다 |
> | §6 `model_routing` **및 기능 오버라이드** 기동 검사 | **`model_routing` 4개 역할 기본값만** | `schema.py`의 모델 이름 필드 20여 개 중 `token_counter_model`(`"gpt-4"`, 토크나이저 식별자), `embedding.model`, `reranker.model`은 의도적으로 카탈로그 밖이라 매 부팅 거짓 경고가 난다. 기능 오버라이드는 값이 `create_llm(model=...)`로 흘러가 거기서 모델별 1회 경고를 받는다 |
> | §1·§11 "선택 가능하지만 가격 없는 모델 6개"를 그대로 둠 | **6개 전부 은퇴** (2026-07-27) | 그 비용이 조용히 0으로 집계됐다. `claude-sonnet-5` / `claude-opus-5` / `gpt-5.6-terra` / `gpt-5.6-sol`로 대체하고, "선택 가능한 모델은 전부 가격을 가진다"를 불변식으로 고정했다 |
>
> §4의 `thinking` 계약 설계는 그대로 구현됐다 — `is_claude_5`는 shim 없이 삭제됐다.

---

## 1. 문제

모델 관련 지식이 파이썬 4곳에 하드코딩돼 있다.

| 위치 | 내용 |
|---|---|
| `neos/providers/anthropic.py`, `openai.py` — `list_models()` | 선택 가능한 모델 목록 (각 6개) |
| `neos/utils/llm_factory.py` — `get_recommended_models()` | provider × `fast`/`balanced`/`powerful` |
| `neos/config/model_routing.py` — `is_claude_5()` | Claude 5 요청 계약 판별 (frozenset 2개) |
| `neos/utils/cost_calculator.py` — `DEFAULT_PRICING` | 모델별 가격 (openai 6, anthropic 6) |

2026-07 Claude 5 / GPT-5.6 도입 작업이 이 4개 파일을 모두 고쳐야 했다. 모델은 계속 나오므로
이 비용이 반복된다.

부수적으로 드러난 문제도 있다. `list_models()`와 `DEFAULT_PRICING`의 모델 집합이 어긋나
**선택 가능하지만 가격이 없는 모델**이 존재하고, 그 비용은 조용히 0으로 집계된다:

- 선택 가능·가격 없음: `claude-sonnet-4-6`, `claude-opus-4-6`,
  `gpt-5-mini-2025-08-07`, `gpt-5-2025-08-07`, `o3`, `o3-mini`
- 가격만 있음: `gpt-4o`, `gpt-4o-mini`, `gpt-4-turbo`, `gpt-3.5-turbo`,
  `claude-3-5-sonnet-20240620`, `claude-opus-4-5-20251101`

카탈로그를 단일 원천으로 만들면 이 어긋남이 한눈에 보인다.

## 2. 범위 밖 (Non-goals)

- **배포 정책 이전 금지.** `model_routing`(provider × role)과 기능 오버라이드
  (`coding_model.model`, `deep_analysis.models.*` 등)는 `config/neos.*.yaml`에 그대로 둔다.
  모델 *사실*과 배포 *정책*을 분리한다.
- **가격 DB 계층 변경 금지.** `llm_model_pricing` 테이블은 계속 최우선이다.
- **allowlist화 금지.** 카탈로그는 기본값의 원천이지 허용 목록이 아니다.
- Gemini·Ollama 모델의 능력·가격 정교화는 이번 범위가 아니다. `get_recommended_models()`의
  기존 `tier` 값만 그대로 옮기고, 목록 노출 파생은 적용하지 않는다 (§5 참조).

---

## 3. 카탈로그 스키마

`neos/config/models.yaml`. Pydantic으로 검증하며 알 수 없는 필드는 거부한다.

```yaml
models:
  claude-sonnet-5:
    provider: anthropic
    tier: balanced             # fast | balanced | powerful | null
    thinking: adaptive         # adaptive | budgeted | none
    selectable: true           # list_models()에 노출되는가 (기본 true)
    max_tokens: 8192
    pricing:
      input: 3.00              # USD / 1M tokens
      output: 15.00
      cache_creation: 3.75
      cache_read: 0.30

  claude-sonnet-4-5-20250929:
    provider: anthropic
    thinking: budgeted
    pricing: {input: 3.00, output: 15.00, cache_creation: 3.75, cache_read: 0.30}

  claude-sonnet-4-6:
    provider: anthropic
    thinking: budgeted
    # pricing 없음 — 현행과 동일. 비용 집계 시 경고한다.

  gpt-4o:
    provider: openai
    thinking: none
    selectable: false          # 가격만 알고 목록엔 노출하지 않음
    pricing: {input: 2.50, output: 10.00}

aliases:                       # 레거시 get_*_model_id() 호환
  llm:
    claude_sonnet: claude-sonnet-5
    claude_haiku: claude-haiku-4-5-20251001
  vision:
    claude: claude-sonnet-5
    gpt4o: gpt-4o
  embedding:
    openai_small: text-embedding-3-small

defaults:
  vision: gpt4o
  llm: claude_sonnet
  embedding: openai_small
```

### 필드 근거

- **`tier`** — `get_recommended_models()`를 대체한다. `null`이면 추천에 등장하지 않는다
  (수동 선택 전용 레거시 모델).
- **`thinking`** — `is_claude_5()`를 대체한다. §4 참조.
- **`selectable`** — `list_models()` 노출 여부. 가격만 아는 모델을 목록에 끼워넣지 않기 위해
  필요하다(§1의 비대칭). 기본 `true`.
- **`pricing`** — 없으면 "가격 미상". 비용 집계 시 경고하고 0으로 처리한다(현행 동작).
- **`capabilities` 같은 범용 리스트는 넣지 않는다.** 오늘 소비자가 없는 추측성 필드다.
  vision·caching 같은 축이 실제로 필요해지면 그때 정확한 필드로 추가한다.

---

## 4. `thinking` 계약 — `is_claude_5` 대체

### 왜 boolean이 아니라 열거형인가

`is_claude_5`는 모델 **정체성**과 **요청 계약**을 뒤섞은 이름이다. 실제 판별 대상은
"Claude 5인가"가 아니라 "adaptive thinking 계약을 쓰는가"다. 이름에 버전이 박히면
5.5 / 6이 나올 때마다 함수가 늘어난다.

더 중요한 문제는 현재 구조가 `if is_claude_5: adaptive else: 레거시`라는 점이다.
**이 암묵적 else가 썩는다** — Anthropic이 manual thinking을 폐기하면 새 모델이 잘못된
분기로 간다. 계약을 명시적으로 선언하면 각 모델이 자기 계약을 스스로 말한다.

### 값

| 값 | 의미 |
|---|---|
| `adaptive` | `thinking={"type": "adaptive"}` 전송. `temperature`·`top_p`·`top_k` 제거. 호출자가 수동 `budget_tokens`를 넘기면 `ValueError` |
| `budgeted` | 레거시 경로. `THINKING_BLOCKS_ENABLED`/`MAX_THINKING_LENGTH`에 따라 `thinking={"type":"enabled","budget_tokens":N}`, temperature 1.0 강제 |
| `none` | thinking 미지원. 페이로드 변형 없음 |

**미등록 모델의 기본값은 `budgeted`** 다. 현행 동작(알 수 없는 Anthropic 모델이 레거시
분기로 가는 것)을 그대로 보존한다.

### 미래 변화 대응

| 상황 | 대응 |
|---|---|
| Claude 5.5 / 6 출시 (같은 계약) | YAML에 `thinking: adaptive` 한 줄 |
| 새 thinking 계약 등장 | YAML에 새 값 + 정규화기에 분기 1개 |
| 기존 모델 계약 변경 | YAML 값만 수정 |

어느 경우도 함수 이름에 버전이 박히지 않는다.

### 코드 변경

`is_claude_5`는 **삭제한다** (하위 호환 shim을 남기지 않는다 — 나쁜 이름을 영속시킨다).
사용처는 전부 내부 코드다: 정의 1곳(`model_routing.py`), 호출 3곳
(`providers/anthropic.py`), 테스트 1곳.

대체 API는 로더에 둔다:

```python
# neos/config/model_config.py
def thinking_contract(model: str) -> ThinkingContract:
    """모델의 thinking 요청 계약. 미등록 모델은 BUDGETED."""
```

`neos/workflow/deep_analysis/llm.py`는 이미 `providers/anthropic.py`의
`normalize_anthropic_request`를 재사용하므로 별도 변경이 없다.

**부수 효과:** `model_routing.py`가 Claude 5를 알 필요가 없어져 순수 리졸버로 되돌아간다.
`model_config`(파일 I/O)를 참조하지 않으므로 순환 import도 발생하지 않는다.

---

## 5. 파생 뷰

하드코딩 4곳이 모두 카탈로그의 뷰가 된다.

| 소비자 | 파생 규칙 |
|---|---|
| `AnthropicProvider.list_models()` | `provider == "anthropic" and selectable` |
| `OpenAIProvider.list_models()` | `provider == "openai" and selectable` |
| `get_recommended_models(provider)` | 해당 provider 모델의 `tier` → `{tier: model}` (4개 provider 전부) |
| `normalize_anthropic_request()` | `thinking_contract(model)` |
| `CostCalculator._get_default_pricing()` | 카탈로그 `pricing` |

### provider별 적용 범위

`list_models()` 파생은 **Anthropic·OpenAI에만** 적용한다.

- **Gemini** — 정적 목록을 유지한다. 이 정책 범위 밖(§2)이고, 카탈로그에는 `tier` 값만
  옮겨 `get_recommended_models("gemini")`가 동작하게 한다.
- **Ollama** — `list_models()`가 라이브 서버(`/api/tags`)를 조회하고 실패 시 내장 목록으로
  폴백한다. **순수 파생이 불가능**하므로 현행 구조를 유지한다. `tier`만 카탈로그로 옮긴다.

즉 카탈로그는 4개 provider의 `tier`를 모두 담지만, 목록 노출 파생은 Anthropic·OpenAI에
국한된다. Gemini·Ollama 모델 항목은 `selectable: false`로 선언해 이 구분을 명시한다.

### 선언 순서

`list_models()`의 순서는 **카탈로그 선언 순서를 따른다.** 현재 목록이 최신 → 레거시 순으로
정렬돼 있어 UI·문서에서 의미가 있다. 따라서 `models:` 맵은 **provider별로 묶어, 각 provider
안에서 현재 `list_models()` 순서대로** 선언한다. dict가 삽입 순서를 보존하므로 필터링 후에도
순서가 유지된다.

---

## 6. 동작 규칙

### 미등록 모델 — 통과 + 경고

카탈로그는 allowlist가 아니다. 경고는 두 곳에서만 낸다.

- `create_llm(model=...)` — 카탈로그에 없으면 `logger.warning`. **모델 이름별 1회만**
  경고한다(로그 폭주 방지).
- 비용 집계 — 가격을 모르면 경고 후 0으로 집계.

신종 모델을 카탈로그 갱신 전에 사용자가 직접 지정할 수 있어야 하므로 통과시킨다.

### 가격 우선순위 — 3계층

```
llm_model_pricing DB (시간 유효)  →  models.yaml pricing  →  경고 + 0
```

DB가 계속 최우선이다. config는 현재 하드코딩 폴백의 자리를 대체할 뿐이므로 운영 중
가격 변경 경로(DB)는 영향받지 않는다.

### `model_routing` 검증 — 경고만

`model_routing`이나 기능 오버라이드가 카탈로그에 없는 이름을 가리키면 기동 시
`logger.warning`을 낸다. **예외는 던지지 않는다** — "통과 + 경고" 결정과 일관되게,
카탈로그 갱신 전에도 배포에서 신종 모델을 지정할 수 있어야 한다. 오타는 로그로 드러난다.

---

## 7. 하위 호환

### 레거시 별칭 API

`get_vision_model_id('claude')`, `get_llm_model_id('claude_sonnet')`,
`get_embedding_model_id()`는 `aliases` 섹션을 통해 그대로 동작한다.

### 옛 형태 `models.yaml`

`NEOS_MODEL_CONFIG_PATH`로 커스텀 파일을 쓰는 사용자가 있을 수 있다. 로더는 `models:` 키가
없으면 **옛 형태(`vision_models` / `llm_models` / `embedding_models`)를 자동 변환**해 읽고,
`logger.info`로 마이그레이션을 안내한다. 옛 형태에는 `tier`·`pricing`·`thinking`이 없으므로
그 모델들은 tier 없음·가격 미상·`thinking: budgeted`로 취급된다.

### 로더 배치

기존 `neos/config/model_config.py`를 진화시킨다. 새 모듈을 만들지 않아 모델 설정 진입점이
하나로 유지된다. 노출 API:

- 레거시: `get_vision_model_id`, `get_llm_model_id`, `get_embedding_model_id`
- 신규: `get_model_spec`, `models_for_provider`, `tiers_for_provider`,
  `thinking_contract`, `pricing_for`

로더는 파일만 읽으므로 DB를 요구하지 않는다 (`no_db` 테스트에서 동작해야 한다).

---

## 8. 테스트 전략

| 층 | 검증 내용 |
|---|---|
| 카탈로그 스키마 | 알 수 없는 필드 거부, `thinking`/`tier` 열거값 검증, `pricing` 키 검증 |
| **이관 정합성** | 카탈로그 값이 **이관 전 하드코딩 값과 일치**. 옛 dict를 테스트 상수로 박아 대조 |
| 파생 뷰 | `list_models()` / `get_recommended_models()` / `pricing_for()`가 카탈로그와 일치, 순서 포함 |
| thinking 계약 | `adaptive` → adaptive + 샘플링 파라미터 제거, `budgeted` → 레거시, **미등록 → budgeted** |
| 미등록 모델 | `create_llm` 통과 + 경고 1회, 비용 경고 + 0 |
| 하위 호환 | 옛 형태 파일 자동 변환, 레거시 별칭 API 동작 |
| DB 무의존 | 로더가 `no_db`에서 동작 |
| 회귀 | 기존 2112 passed 유지 — 특히 `tests/providers`, `tests/test_cost_calculator.py`, `tests/config` |

**이관 정합성 테스트가 이 작업의 안전망이다.** 가장 큰 위험이 전사(transcription) 오류이므로
파생 뷰를 바꾸기 **전에** 대조 테스트를 먼저 넣는다.

---

## 9. 적용 순서

각 단계가 독립적으로 green이어야 한다.

1. **카탈로그 스키마 + 로더** — Pydantic 모델, 옛 형태 변환. 소비자 변경 없음
2. **`models.yaml` 작성** — 현재 하드코딩 값을 그대로 옮긴다. 동작 변화 0
3. **thinking 계약 이관** — `is_claude_5` 삭제, `providers/anthropic.py`가 카탈로그 조회
4. **카탈로그·티어 이관** — `list_models()`, `get_recommended_models()`
5. **가격 이관** — `DEFAULT_PRICING` → 카탈로그 (DB 우선순위 유지)
6. **`model_routing` 미등록 경고 + 문서화** — `docs/CONFIGURATION.md`에 카탈로그 절 추가

2단계가 "값을 그대로 옮기는" 단계이므로 3~5단계는 파생 뷰가 같은 값을 내는지만 확인하면 된다.

---

## 10. 위험과 완화

| 위험 | 완화 |
|---|---|
| **2단계 전사 오류** — 가격·모델 ID 오타가 조용히 잘못된 비용 집계로 이어진다 | 3~5단계 각각에서 이관 전 하드코딩 값과 대조하는 테스트를 **먼저** 넣는다 |
| `list_models()` 순서 변경이 UI·문서에 영향 | 카탈로그 선언 순서를 현재 목록 순서와 동일하게 작성하고 순서까지 단언한다 |
| 옛 형태 커스텀 파일 사용자 | 자동 변환 + `logger.info` 안내 |
| 카탈로그 로딩이 DB를 요구하게 되는 실수 | `no_db` 테스트로 고정 |

---

## 11. 성공 기준

- 새 Claude/GPT 모델 추가가 `neos/config/models.yaml` **한 파일 편집**으로 끝난다
  (목록 노출, 추천 티어, thinking 계약, 가격 전부).
- `is_claude_5`처럼 버전이 박힌 식별자가 코드에 남지 않는다.
- 기존 2112개 테스트가 계속 통과한다.
- `llm_model_pricing` DB 우선순위와 `model_routing` 정책 위치가 변하지 않는다.
