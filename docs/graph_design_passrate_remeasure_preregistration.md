# 설계자 통과율 재측정 (M-0) — 사전 등록

**작성일:** 2026-09-14 (사전 등록, **실행 전**)
**대상:** 오늘 코드의 `LlmGraphDesigner` + `validate_topology` 가 템플릿 없는 카탈로그(31개)에서 내는 L-1 통과율
**트랙:** 로드맵 G(설계자 통과율 재측정) · I(GS0, M-0) — [GRAPH_SUBAGENT_INTEGRATION_DESIGN.md](GRAPH_SUBAGENT_INTEGRATION_DESIGN.md) §9
**선행 표본:** [graph_design_passrate_preregistration.md](graph_design_passrate_preregistration.md) (`20260824T101448Z`, 15/20 = 75%)
**규율:** 로드맵 §6.1 — 표본 1회 · 사전 등록이 표본보다 먼저 · 한 표본에 한 변경

> 🔴 **이 문서는 표본 실행 *전에* 커밋된다.** 실행 후 기대를 고치면 판정이 아니라
> 합리화다. 커밋 해시가 그 순서의 증거이며, 측정 스크립트가 실행 시점에 이 파일의
> 마지막 커밋 해시를 `manifest.json` 에 적는다.
>
> 이 커밋은 **표본을 돌리지 않는다.** 키도 비용도 쓰지 않았다.

---

## 1. 왜 다시 재는가

트랙 I의 M-1(템플릿 포함 카탈로그의 통과율)은 **비교 상대**가 필요하다. 75%는 그 상대가 될 수
없다 — 08-24 이후 **검증 규칙 자체**가 바뀌었기 때문이다.

| # | 08-24 이후 바뀐 것 | 커밋 | L-1에 미칠 방향 |
|---|---|---|---|
| C-1 | I1 요구가 노드 이름(`mandatory=(response_generator,)`)에서 **키**(`must_write={"final_response"}`)로 | 08-24 판정 직후 | ↑ — 08-24 거부 5건이 전부 `missing_mandatory` 였다 |
| C-2 | 조건부 요구 `requires_unless` 와 경로별 검사 | `a3375f8c` | ↑ 쪽이 유력 — `response_generator` 의 결과 셋 요구가 `final_response` 경로에서 면제된다 |
| C-3 | writes 추출이 반환 위치 위임을 따라간다(계약 `writes` 재산정) | `6cd49a79` | **양방향** — 과대 선언이 지워졌으면 `unsatisfied_requires` 가 늘 수 있다 |

그리고 **측정 도구가 낡았다.** `scripts/graph_design_passrate.py` 는 이 사전 등록 전까지
`mandatory=(response_generator,)` 를 넘기고 있었다 — 프로덕션이 버린 규칙이다. 그대로
돌렸다면 C-1 을 되돌린 채 재서 **옛 거부 5건을 다시 관측**했을 것이다(로드맵 §10 "계측을 먼저
의심한다"). 이 커밋이 도구를 프로덕션 관문(`design_graph_or_fallback`)과 같은 인자로 고친다.

## 2. 지표와 기대

| # | 항목 | 값 |
|---|---|---|
| **L-1 (1차)** | `validate_topology` 위반 0건인 설계의 비율 | **기대: ≥ 90% (18/20 이상)** |
| **반증 조건** | 통과율 **< 75%** — 08-24보다 낮으면 C-2·C-3 이 새 거부를 만들었거나 모델이 달라진 것이다 | |
| 판정 보류 | 75% ≤ 통과율 < 90% | L-2 가 다음 수를 정한다 |
| L-2 | 거부 사유 분포 — 규칙 × 노드 × 키 | 방향만 |
| L-3 | 파싱 실패율 (`InvalidDesignPayload`) | 방향만 |
| L-4 | 타임아웃율 (`graph_design_timeout_sec`) | 방향만 |
| L-5 | 승인된 설계의 노드 수 분포 | 방향만 |

**기대의 근거 — 사후 합리화를 막기 위해 미리 적는다.**

- 08-24 거부 5건은 전부 `missing_mandatory` 하나였고, 설계는 `[direct_response]` 류였다.
  `direct_response` 는 `final_response` 를 쓰므로 C-1 아래에서는 통과한다.
- 08-24 통과 15건은 `mandatory` 를 만족했고 `unsatisfied_requires` 가 없었다. C-2 는 요구를
  **줄이는** 방향이라 그 15건을 떨어뜨리지 않는다.
- 유일한 하락 요인은 C-3 과 모델 변동이다. C-3 이 떨어뜨리는 설계가 있다면 L-2 에
  `unsatisfied_requires` 로 **이름을 달고** 나타난다.

## 3. 표본 설계

| 항목 | 값 |
|---|---|
| 질의 | 08-24 와 **같은 20개** (`scripts/graph_design_passrate.py` `QUERIES`, 이 커밋에서 무변경) |
| 프롬프트 | `neos/workflow/prompts/graph_design.md` v2, sha256 앞 16자 **`7af3ebdd3e0a6bc2`** (08-24 와 같음) — 다르면 실행하지 않는다 |
| 카탈로그 | `NODE_CONTRACTS` 전량. **31개가 아니면 실행하지 않는다** |
| 서브에이전트 템플릿 | **제외.** `workflow.subagent_nodes_enabled` 가 켜져 있으면 실행하지 않는다 |
| `must_write` | `{"final_response"}` — 프로덕션 기본값(`graph_design_ledger._DEFAULT_MUST_WRITE`) |
| `mandatory` | `()` — 프로덕션과 동일 |
| `budget`/`node_costs` | 둘 다 `None` — 프로덕션과 동일 |
| 모델 | `graph_design_model = None` → everyday 역할 기본값. **실제 모델 ID를 manifest 에 적는다.** `claude-sonnet-5` 가 아니면 판정에 "모델도 바뀌었다" 를 함께 적고 C-1~C-3 귀속을 주장하지 않는다 |
| 실행 횟수 | **정확히 1회.** 실패해도 재실행하지 않는다 |

**경계 확인.** 로드맵 §4 의 경계 1–7 은 전부 심층분석 경로(판정자·예산·fetch·DA 모델 호출)다.
설계자는 `LLMFactory.create_llm` 을 쓰고 DA 하네스를 거치지 않으므로 **이 표본은 그중 어느 것도
가로지르지 않는다.** 대신 08-24 표본과는 C-1~C-3 으로 **비교가 끊긴다** — 75% 와 나란히 놓을
때는 반드시 이 표를 함께 인용한다.

**알려진 편향(08-24 에서 그대로 승계).** 질의 20개는 사람이 만들었다. 통과율의 절대값은
"모델이 이 과제를 원리적으로 할 수 있는가" 의 근거이지 프로덕션 예측치가 아니다.

## 4. 표본보다 먼저 할 수 있는 백테스트 (B-0, LLM 호출 없음)

08-24 에 저장된 응답(`artifacts/graph-design-passrate/20260824T101448Z/responses/*.json`, 파싱에
성공한 20건)을 **오늘의 검증기**로 다시 판정한다. 모델을 부르지 않으므로 표본이 아니다.

- B-0 가 답하는 것: C-1~C-3 **규칙 변경만의** 효과. M-0 과의 차이가 곧 모델 변동이다.
- B-0 는 M-0 **이전에** 돌리고 결과를 따로 커밋한다. B-0 결과를 보고 이 문서의 기대를 고치지 않는다.
- 08-24 아티팩트는 저장소에 **커밋돼 있다**(`artifacts/graph-design-passrate/20260824T101448Z/`,
  심층분석 funnel 아티팩트와 달리 gitignore 대상이 아니다) — B-0 의 입력은 보존돼 있다.

## 5. 산출물

`artifacts/graph-design-passrate/<UTC타임스탬프>/`

- `queries.json` · `responses/` · `verdicts.json` — 08-24 와 같은 형식
- `manifest.json` — 실행 영수증(PID, UTC start/end, exit status) + 구성 지문(모델 ID, 프로바이더,
  카탈로그 크기, 타임아웃, 프롬프트 해시, `must_write`, `mandatory`, 서브에이전트 플래그) +
  **이 사전 등록 파일의 커밋 해시**

## 6. 하지 않는 것

- 실패한 호출의 재시도
- 프롬프트·모델·타임아웃·카탈로그를 실행 중 변경
- 이 표본으로 프롬프트를 고치고 다시 재기 — 재려면 새 사전 등록이다
- M-0 과 M-1 을 한 표본에 — 트랙 I 설계 §9
- 이 표본 하나로 인과 주장

---

## 7. 판정

*(표본 실행 후 이 절 아래에만 적는다. §1–§6 은 고치지 않는다.)*
