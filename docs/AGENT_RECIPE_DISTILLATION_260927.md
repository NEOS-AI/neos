# 에이전트 레시피(Agent Recipe) 증류 연구 — 2026-09-27

**명제:** *System distillation is the moat.* 루프가 곧 프로덕트이고, 에이전트의 성패는
신호(signal)와 검증기(verifier)의 품질이 가른다. 루프에서 얻은 교훈(평가, 판단 기준, 인간의
판단)은 특정 모델에 묶이지 않고 독립적으로 버전 관리되는 **에이전트 레시피**로 남겨 자산으로
쌓아야 한다.

| 관측 | → 레시피 자산 |
| --- | --- |
| Failure patterns | judges, evals, experiments |
| Repeated behaviour | prompts, skills |
| User frustration | memories, extensions |
| Agent struggles | tooling, documentation |
| Frontier performance | golden trajectories |
| High costs | routing, orchestration |

**질문:** 지금의 Neos 코드베이스는 이 여섯 경로 각각에서 어디까지 와 있고, 무엇을 더 만들면
레시피 자산화가 되는가?

**검증 원칙:** [`DIRECTION_260717.md`](DIRECTION_260717.md), [`MICROSERVICE_REVIEW_260927.md`](MICROSERVICE_REVIEW_260927.md)와
같다. 사실 주장에는 `파일:줄` 근거를 달고, 확인하지 못한 것은 **미확인**으로 적는다. 조사는
서브에이전트 7개(여섯 경로 + 공통 인프라)로 나눠 병렬로 했고, 핵심 주장은 직접 다시 확인했다.

**판정 기준:** `DIRECTION_260717.md` §1.2를 따른다. 기준은 **품질/정확도와 유지보수성/복잡도**다.
여기서 두 가지 제약이 나온다. (1) 패러다임이 공존하면 그 자체를 비용으로 계상한다. 레시피 체계가
lessons·GEPA overlay·skills와 **나란히 네 번째 생명주기**가 되면 안 된다. (2) 운영 단위(서비스·DB·브로커)는
늘리지 않는다. 기존 Postgres와 git 안에서 해결한다.

---

## 0. 결론

**Neos에는 신호원이 이미 많다. 부족한 것은 세 가지 연결 고리다.**

1. **결과 라벨(outcome label)이 없다.** 코딩 태스크에는 품질 컬럼이 없다. verify `VERDICT`는
   자기 보고 문자열이고 태스크 상태를 바꾸지 않는다(`neos/coding/phases.py:74-96`,
   `neos/coding/loop/_durable/model_turn.py:521-522`). 👍/👎에는 모델 id가 없다. 텍스트 피드백
   엔드포인트는 프론트엔드가 호출하지 않는다(§3.3). 무엇이 "좋은 실행"이었는지를 데이터로 말할 수
   없으니 golden trajectory도, 비용 대비 품질 라우팅도 만들 수 없다.
2. **승인자(approver)가 없다.** `learned_lessons`는 기본값(`learn.write_approval=true`)에서 전부
   `staged`로 들어간다(`neos/learn/lessons.py:51-54`). 그런데 staged를 approved로 올리는 경로가
   코드 어디에도 없다. `APPROVED`를 쓰는 곳은 write_approval이 꺼졌을 때의 `/learn` 명령
   (`neos/api/channels/gateway.py:631`)과 테스트뿐이다. 신호는 쌓이다가 curator가 90일 뒤 보관한다.
   **증류 파이프라인 끝이 막혀 있다.**
3. **레시피라는 단위가 없다.** 증류된 지식은 지금 세 가지 서로 다른 모양으로 흩어져 있다. lessons
   (DB, 400자 clip, 5개 cap), skills(파일, frontmatter `version`은 관례일 뿐 검증하지 않음), DA 프롬프트
   (`<!-- version: N -->` + golden gate). 공통 식별자, 출처(provenance), 검증기 연결, **"어느 모델에서
   검증됐는가"** 기록이 없다.

**권고:** 새 서브시스템을 세우지 않는다. **레시피 = 버전 + 출처 + 검증기 + 검증된 모델 목록이
붙은 텍스트 자산**으로 정의한다. 저장은 2계층으로 나눈다.

- **전역 레시피**(모든 테넌트 공통: judge rubric, eval case, skill, tool description, routing policy)는
  **git**에 둔다. 승인자는 PR 리뷰이고, 검증기는 CI golden gate다. 이미 DA가 쓰는 방식
  (`tests/workflow/deep_analysis/test_golden_gate.py` + D19)을 일반화하는 것이다. **새 테이블이 필요 없다.**
- **테넌트 레시피**(owner 네임스페이스의 memory, prompt overlay)는 **Postgres 한 테이블**
  (`recipe_versions`)에 둔다. 이 테이블은 GEPA 초안의 `gepa_opt_overlays`를 일반화한 것이다. 초안은
  아직 구현 전이므로 **overlay 전용 테이블을 먼저 만들지 말고** 이 테이블로 합치라고 권한다(§8.2).

선행 작업(Phase 0)은 전부 작은 PR이다. 코딩 run에 모델 출처 기록, 피드백 UI 연결, lesson 승인 API,
tool 실패 사유 코드의 메트릭 라벨화. 이 넷이 없으면 뒤 단계는 모두 빈 데이터 위에 서게 된다.

**해자는 프롬프트가 아니라 검증기 묶음이다.** 새 모델이 `models.yaml`에 들어오면 레시피 eval
스위트를 한 번 돌려 `validated_on`을 갱신하고, 통과한 레시피만 그 모델에 켠다. 이 "모델 교체 비용
= eval 1회"라는 성질이 모델 비종속성의 운영적 정의다(§7).

---

## 1. 레시피의 정의

### 1.1 최소 스키마

```yaml
# recipe manifest (전역: 파일 frontmatter / 테넌트: recipe_versions 행)
recipe_id: tool-desc/edit_file          # kind/key, 안정적
kind: tool_description                  # judge | eval_case | prompt | skill | memory
                                        # | extension | tool_description | trajectory | routing_policy
version: 4                              # 단조 증가 정수 (manifest_version 관례, manifest.py:24)
content_sha256: "…"                     # 본문 해시 (prompt_hashes 패턴, manifest.py:44-58)
scope: global                           # global | owner:{id} (policy.namespace, policy.py:75-79)
status: approved                        # staged | approved | archived (LessonStatus, lessons.py:17-20)
provenance:                             # 어떤 신호에서 증류됐나
  signals: [coding_event:…, da_event:…, vote:…]
  distiller: tool-struggle-weekly@2
verifier:                               # 무엇으로 검증하나
  eval_set: datasets/recipes/edit_file_struggles.jsonl@<sha>
  metric: stall_deny_rate
  threshold: "<= baseline - 20%"
validated_on:                           # 어느 모델에서 통과했나
  - {model: sonnet-5, provider: anthropic, score: 0.91, at: 2026-09-27}
  - {model: gpt-…,   provider: openai,    score: 0.88, at: 2026-09-27}
approved_by: …                          # coding_approvals.decided_by 관례
```

필드는 모두 이미 있는 관례에서 가져왔다. 새로운 것은 `provenance`, `verifier`, `validated_on` 세 필드다.
**이 셋이 레시피를 "그냥 텍스트"와 구분한다.**

### 1.2 모델 비종속성의 실행 기준

레시피 본문은 **공급자 중립 형식**으로만 쓴다.

- 대화·도구 궤적은 `CanonicalMessage` / `ToolDefinition` / `ModelRequest`로 쓴다
  (`neos/coding/model/base.py:155-297`). 네 공급자(anthropic/openai/gemini/ollama)가 모두
  `create_coding_model`로 이 형식을 구현한다(`neos/providers/base.py:85-105`).
- LangChain 채팅 계층(`ModelProviderBase.create_llm`, `base.py:41-66`)을 레시피 형식으로 쓰지 않는다.
  DA도 usage 신뢰성 문제로 이 계층을 거부했다(D5, `DECISIONS.md:217-227`).
- 벤더 원문 고정 텍스트(`COMPACTION_SUMMARY_INSTRUCTION`, `neos/coding/prompts/official.py:19-38`)는
  레시피 후보에서 뺀다. 벤더 텍스트와 NEOS 텍스트를 섞지 않는다는 기존 원칙(`official.py:7-10`)을 따른다.

"모델 비종속"의 판정은 `validated_on`에 **공급자 2개 이상**이 있는지로 한다. 하나뿐인 레시피는
`model_bound`로 표시하고 라우팅이 그 모델에서만 켜도록 한다.

---

## 2. 현황 총괄

| 경로 | 신호원 (있음) | 증류기 | 레시피 자산 | 검증기 | 소비처 | 막힌 곳 |
| --- | --- | --- | --- | --- | --- | --- |
| Failure → judges/evals | DA `Verdict.code` + `deep_analysis_events`, Jev ledger, coding `VERDICT`, `policy_*` reason_code | L5 analytics(비율만) | judge.md(버전 헤더), Jev rubric(digest) | golden gate, harness 캘리브레이션 | CI | 실패 **사례**가 eval case로 저장되지 않음 |
| Repeated → prompts/skills | coding_events 도구 시퀀스, `load_skill.v1` 호출 | 없음 (autoskill은 화면 캡처 대상) | SKILL.md | skill-creator `run_eval.py` (단건) | markdown_catalog | 내부 궤적 마이너 없음, procedure lesson은 소비처 없음 |
| Frustration → memories/extensions | 👍/👎, `/learn`, 코딩 실패 | `memory_gate`, `extract_coding_lesson` | lessons | 없음 | `## Lessons` 주입(기본 off) | **승인자 없음**, 피드백 UI 없음, 취소/재생성 미기록 |
| Struggles → tools/docs | stall 시그니처, `policy_*` 코드, 연속 오류 예산 | 없음 (description은 수작업) | tool description 문자열 | 없음 | 매 턴 tools[] | 도구×사유 집계 없음 |
| Frontier → golden trajectories | checkpoint transcript(Canonical), `LLMCallRecord` | 없음 | 없음 ("golden"은 DA 회귀 cassette 뜻) | DA cassette replay | 없음 | 모델 출처 미기록, 우수 표시 없음, 대량 export 없음 |
| Costs → routing | `message_costs`, DA token budget, cache status | 없음 | `models.yaml`, `HARNESS_ROLES`, effort 기본값 | 없음 | `resolve_model` | 비용↔품질 조인 불가, 라우팅은 정적 설정 |

**읽는 법:** 왼쪽 두 칸(신호)은 대체로 있다. 오른쪽 세 칸(검증기·소비처·승인)이 비어 있거나
끊겨 있다. 그러니 우선순위는 새 신호를 늘리는 쪽이 아니라 **있는 신호를 라벨·승인·검증에
잇는 쪽**이다.

---

## 3. 경로별 분석

### 3.1 Failure patterns → judges, evals, experiments

**있는 것 — Neos에서 가장 성숙한 경로다.**

- **실패 분류 체계:** DA grader가 구조화된 코드를 낸다. `E_NO_EVIDENCE`, `E_SOURCE_DEAD`,
  `E_QUOTE_MISMATCH`, `E_CONFIDENCE_INFLATED`(`graders/deterministic.py`)가 있고, agentic judge는
  SUPPORTS/PARTIAL/UNRELATED/CONTRADICTS를(`graders/agentic.py`), report grader는
  `E_REPORT_*`를(`graders/report.py`) 낸다. 이 코드는 append-only `deep_analysis_events`에 남고
  (D8, DB 트리거로 UPDATE/DELETE 차단), claim별 수선 큐는 `DAFeedback`에 남는다
  (`neos/database/deep_analysis_models.py:186-207`).
- **재현성:** Jev는 모든 판정에 `rubric_digest`(sha256)와 해석된 모델 id를 붙인다
  (`neos/jev/rubric.py:42-48`, `gate.py:44-47`). DA `run_manifest`는 역할별 모델·effort와 프롬프트
  해시를 고정한다(`manifest.py:24,44-58`, D84). `judge_equals_scout` 같은 자기 편향 표시도 있다.
- **회귀 게이트:** 프롬프트 버전 헤더와 `EXPECTED_PROMPT_VERSIONS`가 맞지 않으면 CI가 깨진다. 그러면
  golden을 다시 녹화하고 사람이 신호를 검토해야 한다(`test_golden_gate.py`, D19 `DECISIONS.md:483-491`).
- **실험 방법론:** 사전 등록 → 1회 실행 → 산출물 보존의 선례가 있다
  (`docs/graph_design_passrate_preregistration.md`, `artifacts/graph-design-passrate/20260824T101448Z/`).
- **캘리브레이션:** `scripts/harness_calibration.py`가 있고, 오프라인↔런타임 판정 일치 라벨을
  정의한다(`docs/HARNESS_EVAL_CALIBRATION.md`). 다만 문서의 "Latest Run" 칸이 비어 있어 정기적으로
  돌리지 않는 것으로 보인다(**미확인**).

**막힌 곳.**

1. **실패 "사례"가 eval case로 굳지 않는다.** L5는 `reject_rate_by_code` 같은 *비율*만 집계한다
   (`analytics.py`). "이 12건은 같은 원인"이라는 군집도, 그 사례를 입력·기대 코드 쌍으로 저장하는 곳도
   없다. golden 이력은 사람이 주석으로 적는다("표본 #16").
2. **실패 어휘가 네 벌이다.** coding `VERDICT`, DA `Verdict.code`, Jev band, `policy_*` reason_code가
   서로 연결되지 않는다.
3. **코딩 루프 실패는 분석 데이터가 되지 않는다.** `VERDICT: FAIL`은 durable state에만 남는다.
4. **judge 자체의 검증(meta-eval)이 없다.** judge가 인간 라벨과 얼마나 일치하는지 저장소에 기록된
   수치가 없다. **검증기 품질이 해자라면 가장 먼저 채울 칸이 여기다.**

**레시피화 방안.**

- **Failure Case Capture (오프라인, 사람 검토).** DA ledger의 `_degradation_kind()`(`ledger.py:81-111`)가
  이미 품질 저하 이벤트를 분류한다. 여기서 사례 후보를 뽑아 `datasets/recipes/cases/*.jsonl`로
  내보낸다. 필드는 입력, run_manifest 참조, 관측 코드, 기대 판정이다. 사람이 채택한 사례만 git에
  들어가며 본문은 content hash로 주소를 붙인다. D19와 충돌하지 않는다. 이 단계는 *관측 → 사람 결정*이다.
- **공통 실패 분류(taxonomy) 한 장.** 네 어휘를 상위 범주(evidence / tool-policy / loop-stall /
  self-report / budget)로 묶는 매핑 표를 둔다. 기존 코드는 바꾸지 않고, 집계할 때만 쓴다.
- **Judge = 레시피.** judge.md, report_judge.md, Jev rubric YAML에 §1.1 manifest를 붙인다. 특히
  `validated_on`과 **인간 라벨 일치율**을 붙인다. `harness_calibration.py`를 정기 CI(주 1회)로 올리고
  결과를 레시피의 `verifier` 칸에 기록한다.
- **실험 레시피.** preregistration 문서 형식을 템플릿으로 굳힌다. 가설, 표본, 고정 모델, 판정 규칙,
  재실행 금지를 담는다. graph-design 실험이 모델을 고정하지 않은 것을 스스로 편향으로 적었다
  (preregistration §66-75). 템플릿에서는 `models` 필드를 필수로 만든다.

### 3.2 Repeated behaviour → prompts, skills

**있는 것.**

- 프롬프트는 Python 섹션 빌더로 조립한다(`neos/coding/prompts/builder.py:39-60`).
  `SYSTEM_PROMPT_DYNAMIC_BOUNDARY`(`builder.py:14`)가 캐시되는 정적부와 세션 동적부를 나눈다.
  프롬프트 문자열 자체에는 버전·해시가 없다.
- 스킬은 두 층이다. markdown catalog(`neos/skills/markdown_catalog.py`, frontmatter 검증
  `_coding_sections_valid` 149-183)와 실행형 `BaseSkill`(`neos/skills/base/skill.py`, `version="1.0.0"`
  필드가 있지만 아무도 비교하지 않음)이다. 코딩 에이전트에는 이름 인덱스만 들어가고, 본문은
  `load_skill.v1`로 필요할 때 읽는다(`builder.py:156-170`).
- **가장 가까운 선례: `skills/autoskill/`.** 관측 → 군집(`cluster.py`) → 기존 스킬 대조
  (`match_skills.py`) → 합성(`synthesize.py`) → 사람 검토 후 승격(`promote.py`)의 구조가 레시피 증류기
  모양 그대로다. 다만 입력이 외부 screenpipe의 **화면 활동**이고, Neos 자신의 궤적이 아니다.
- `skills/skill-creator/`가 단일 스킬의 eval·비교·반복 도구를 갖고 있다(`scripts/run_eval.py`,
  `run_loop.py`, `agents/grader.md`).

**막힌 곳.**

1. Neos 내부 궤적(`coding_events`, 도구 호출 시퀀스)을 채굴하는 마이너가 없다.
2. `kind="procedure"` lesson은 추출은 되지만(`neos/learn/extract.py:57-89`) 아무도 읽지 않는다.
   `learn.research_procedures`는 기본 off다. **죽은 경로다.** 여기에 새 기능을 붙이지 않는다.
3. 스킬 사용은 *선택* 로그만 있고(`skill_based_tool_selector.py:102-127`), *결과*(그 스킬을 쓴 실행이
   성공했나)와 이어지지 않는다.

**레시피화 방안.**

- **autoskill 파이프라인을 내부 이벤트 소스로 재사용한다.** `fetch_window.py` 자리에 coding_events
  리더를 끼운다. 기존 `redact.py` 대신 `neos/coding/redact.py`를 쓴다. 군집 단위는 도구 호출 시퀀스
  n-gram과 사용자 요청 임베딩이다. 산출물은 `skills/<name>/SKILL.md` **PR**이다. 승인자는 PR 리뷰다.
- **스킬 frontmatter에 manifest 필드를 추가한다.** `metadata.version`을 관례가 아닌 규칙으로 만든다.
  `markdown_catalog`가 `version`, `provenance`, `verifier` 존재 여부를 경고 수준으로 검사하게 한다.
  검증기는 skill-creator의 `run_eval.py` 결과 파일을 가리킨다.
- **스킬 사용 → 결과 조인.** `load_skill.v1` 호출을 coding event로 남기면(**미확인**: 현재 별도 이벤트
  종류인지) run 결과 라벨(§6 Phase 0)과 조인해 스킬별 성공률을 낼 수 있다. 이것이 스킬 레시피의
  온라인 검증 지표다.
- **프롬프트 섹션에 해시를 붙인다.** `build_coding_system_prompt`의 정적 섹션 해시를 run 메타데이터에
  기록한다. DA `prompt_hashes`처럼 읽기 전용이다. 그러면 "어느 프롬프트 버전이 이 궤적을 만들었나"를
  답할 수 있다.

### 3.3 User frustration → memories, extensions

**있는 것.**

- 👍/👎: `web/components/message-actions.tsx` → `web/app/(chat)/api/vote/route.ts` →
  `neos/api/services/vote_service.py`로 이어지고 `Vote`(chat_id, message_id, is_upvoted)에 저장된다.
  **모델·턴·트레이스 id는 없다.**
- 텍스트 피드백 → 기억: `submit_feedback`이 `is_imperative`로 거른 뒤 `maybe_learn_ltm`을 부른다
  (`vote_service.py:203-214`). **그런데 `web/` 어디에서도 이 엔드포인트를 호출하지 않는다**(직접 grep으로
  확인). 신호원이 코드로만 존재한다.
- `/learn <text>` 채널 명령(`gateway.py:594-633`), 코딩 실패 → `stage_coding_lesson`
  (`neos/coding/application/run_service.py:104-153` → `neos/learn/extract.py:25-54`).
- 확장 지점: `CodingHookPort`(pre/post_tool, stop, compact, pre/post_generate — `neos/coding/hooks.py:12-78`)가
  있지만 구현은 `NullCodingHooks`뿐이다. `mcp/`는 비어 있다. 워크스페이스 `AGENTS.md`/`CLAUDE.md`는
  읽기 전용 user context다(`neos/coding/instructions.py:21-24`).

**막힌 곳.**

1. **승인자 부재**(§0). staged lesson은 승격되지 않고 보관된다.
2. 암묵 신호가 기록되지 않는다. 재생성, 편집 후 재전송(`message-editor.tsx`의 `regenerate()`), 스트림
   중단, 코딩 태스크 `cancelled`, stall-deny가 해당한다. "재시도 / 좌절 / 재진술"을 검출하는 코드는 없다.
3. lessons에 버전 이력이 없고(update가 덮어씀), 출처(어느 턴의 어떤 피드백) 링크도 없다
   (`db/migrations/049_add_learned_lessons.sql`, `052`).

**레시피화 방안.**

- **Phase 0:** 👎 옆에 사유 입력 UI를 붙여 `/votes/feedback`을 연결한다. `Vote`에 `model`, `provider`,
  `turn_id`(또는 trace id) 컬럼을 추가한다. 가장 싼 고신호 데이터다.
- **Phase 0:** lesson **승인 API + 관리 화면**을 만든다. `PATCH /learn/lessons/{id}` staged→approved/archived,
  `approved_by` 기록, owner 네임스페이스 강제. 이것이 기억 레시피의 승인자다.
- **암묵 신호 기록:** 재생성·중단·취소를 이벤트 한 종류(`user.friction`)로 남긴다. 새 테이블 없이 기존
  이벤트 로그를 쓴다. D84가 "새 컬럼 대신 새 이벤트 kind"를 고른 논리를 따른다. 좌절 점수는 만들지
  않는다. 집계는 오프라인 리포트로만 한다. 사람이 읽을 신호이지 자동 조정기 입력이 아니다(D19 정신).
- **Frustration → extension 제안:** 같은 사용자가 같은 교정을 반복하면("테스트 먼저 돌려", "한국어로")
  기억보다 **확장**이 맞다. 워크스페이스 `.claude/rules/*.md` 추가 제안이나 hook 설정 제안이 해당한다.
  이 경우 레시피는 사용자에게 보여 주는 *제안 diff*이고, 적용은 사용자가 한다.
- **기억 레시피 제약:** `is_imperative` 차단(`policy.py:60-61`)과 400자 clip은 유지한다. 기억은 사실이지
  지시가 아니다. 지시는 prompt/extension 레시피로 보낸다. 이렇게 경계를 그으면 lessons 체계와 레시피
  체계가 겹치지 않는다.

### 3.4 Agent struggles → tooling, documentation

**있는 것 — 계측은 좋은데 집계가 없다.**

- **doom-loop 가드:** 호출을 `sha256(name + canonical_json(input))`로 지문화한다. 같은 오류 *또는* 같은
  성공이 3회 반복되면 실행 없이 `policy_stall_denied`를 낸다(`neos/coding/loop/_durable/signatures.py:38-50`,
  `STALL_DENY_AFTER=3`, `state.py:16`). 연속 오류 5회에서는 run을 종료한다(`tool_error_budget_exceeded`).
- **실패 사유 분류표가 이미 있다:** `_POLICY_FIX_NOTES`(`neos/coding/tools/registry.py:75-93`)는
  `policy_*` 코드 → 고치는 방법 문장의 작은 enum이다. `_DEDICATED_TOOL_FOR`(`registry.py:50-74`)는
  grep/find/sed를 전용 도구로 유도한다.
- **description에 사람이 과거 사고를 녹여 둔 흔적:** `search_text.v1` 설명의 "Do not use execute.v1 with
  rg/grep/find. On policy_* denial, do not retry the same query."(`registry.py:601-613`). **이것이 수작업으로
  한 "struggle → tooling" 증류다.** 반복 가능한 공정으로 만들면 된다.

**막힌 곳.**

1. 메트릭 `coding_tool_execution_total{tool,outcome}`(`neos/observability/metrics.py:155`)의 outcome은
   `ok/error/denied` 셋뿐이다. 어떤 `policy_*` 사유인지는 run별 이벤트에만 남는다.
2. lesson 추출은 **run이 실패했을 때만** 동작한다(`extract.py:15-22`). stall-deny를 세 번 겪고 결국 성공한
   run은 증거로 남지 않는다. 그런데 도구 개선에 가장 좋은 증거가 바로 이런 run이다.
3. 채팅 쪽 tool registry(`neos/tools/tool_search/`, DB upsert, 버전 없음)와 코딩 쪽
   registry(`neos/coding/tools/registry.py`, 문자열 리터럴)가 따로 있다.
4. description 변경이 struggle을 줄였는지 재는 eval이 없다. 테스트는 정책 코드가 *발생하는지*만 본다.
5. **숨은 결합:** `_guard_thinking_prefix`(`model_turn.py:238-267`)는 system+tools 지문이 바뀌면 thinking을
   strip한다. description을 라이브로(테넌트별, 세션 중) 바꾸면 모든 세션의 캐시와 thinking이 무효화된다.

**레시피화 방안.**

- **Phase 0:** 메트릭에 `reason_bucket` 라벨을 추가한다. 카디널리티는 `_POLICY_FIX_NOTES` 키 수로 한정된다.
- **Tool Struggle 주간 리포트(오프라인):** coding_events에서 (tool, reason_code, stall 여부, run 최종 결과)를
  집계한다. **성공한 run 안의 struggle까지 포함한다.** 상위 항목마다 실패 사례 입력을 뽑아 eval case(§3.1)로
  남긴다.
- **Tool description = 전역 레시피.** `_RegisteredTool.description`을 레시피 대상으로 삼는다. 후보 생성은
  사람이 하거나 GEPA reflector가 한다(candidate component = `tool:<name>`). 검증은 struggle 사례 replay에서
  stall/deny율이 줄어드는지로 한다. 반영은 **배포 단위(PR)**로만 한다. 테넌트별 라이브 overlay로 하지 않는다.
  캐시와 thinking 무효화(위 5번) 때문이다.
- **Docs 레시피:** 반복 struggle 중 도구 문제가 아닌 것(예: 레포 구조 오해)은 skill 문서나 AGENTS.md 템플릿으로
  보낸다. 경계 규칙: *한 도구에 국한되면 tool description, 여러 도구·절차에 걸치면 skill*.

### 3.5 Frontier performance → golden trajectories

**있는 것.**

- **공급자 중립 궤적 형식이 이미 있다.** checkpoint의 `transcript: tuple[CanonicalMessage]`와 턴별
  토큰/캐시/비용(`neos/coding/loop/_durable/state.py:157-206`, `usage.py:16-72`), `coding_tool_executions.result_json`
  (`db/migrations/039`), append-only `coding_events`(`038`)가 있다.
- **SFT 포맷 exporter가 이미 있다.** `LLMCallRecord`는 provider·model을 기록하고
  `to_training_format`/`to_anthropic_format`을 제공한다(`neos/dataset/models.py:12-105`,
  `neos/dataset/storage.py:136-`). 다만 **LangGraph 검색·워크플로의 단일 LLM 호출**용(`@track_llm_call`)이고,
  코딩 루프의 다턴 궤적과는 이어지지 않는다.
- 리댁션 원시함수: `redact_sensitive`, `strip_binary_payloads`(`neos/coding/redact.py:43-109`).
- 결정적 replay 선례: DA cassette(`neos/workflow/deep_analysis/cassette.py`).

**막힌 곳.**

1. **모델 출처가 데이터에 없다.** 모델·provider는 `CodingLoopConfig`에만 있고, `coding_runs`·checkpoint 컬럼으로는
   남지 않는다(`038`/`039` 마이그레이션에 model 컬럼 없음, 직접 확인). "프런티어 모델이 푼 궤적만" 거를 수 없다.
2. 성공 라벨이 없다(§0-1).
3. export는 `/export` 단건뿐이다. 200개 메시지와 800자에서 잘리고 tool result는 미리보기만 남는, 손실형이다
   (`neos/coding/commands/export.py:14-67`).
4. 과거 궤적을 few-shot으로 검색하거나 더 싼 모델로 증류하는 경로가 없다.
5. 이 코드베이스에서 "golden"은 *DA 회귀 cassette*를 뜻한다. 우수 실행 큐레이션이라는 개념은 없다.

**레시피화 방안.**

- **Phase 0:** `coding_runs`에 `model`, `provider`, `effort`, `prompt_hash` 컬럼을 추가한다. 이 레시피의
  모든 후속 단계가 여기에 달려 있다.
- **Golden Trajectory = 레시피.** 승격 조건은 (a) 결과 검증 통과와 (b) 사람 확인이다. (a)는 태스크 테스트
  통과, 👍, 또는 판사 점수이고, self-report `VERDICT`만으로는 안 된다(GEPA 초안의 Goodhart 경고와 같은 이유).
  저장 형식은 **Canonical transcript + 태스크 입력 + 결과 검증 증거 + 생성 모델**이다. 공급자 형식으로
  변환하지 않고 저장한다. 변환은 소비 시점에 adapter가 한다.
- **쓰임새 세 가지, 도입 순서대로.**
  1. *회귀:* golden 궤적의 태스크 입력을 새 모델·새 프롬프트로 재실행해 결과 검증을 다시 통과하는지 본다.
     모델 교체 판정의 핵심 eval이 된다.
  2. *few-shot 검색:* pgvector(기존 인프라)에 태스크 요약 임베딩을 두고, 유사 태스크의 **요약된** 계획만
     주입한다. 전체 transcript는 주입하지 않는다. 컨텍스트 비용과 캐시 경계(`SYSTEM_PROMPT_DYNAMIC_BOUNDARY`
     아래 배치)를 고려한 선택이다.
  3. *증류:* `neos/dataset/storage.py`의 training format writer에 Canonical → SFT adapter를 추가해 더 싼 모델
     (everyday tier·로컬 ollama) 미세조정 데이터를 만든다. **테넌트 동의와 리댁션이 선행 조건이다.**
- 생성 모델 교체와 무관하게 쓸 수 있도록, golden에는 *모델이 한 말*이 아니라 *태스크와 검증*을 핵심으로
  남긴다. 궤적 본문은 참고 증거다.

### 3.6 High costs → routing, orchestration

**있는 것.**

- 모델 해석 우선순위: user → conversation → feature_override → role_default
  (`neos/config/model_routing.py:55-100`). 역할은 `everyday`/`powerful` 둘뿐이다(`schema.py:166-177`).
- DA 역할 매핑은 한 곳에 모여 있다: `HARNESS_ROLES = {scout: everyday, dig: powerful, synth: powerful, judge: everyday}`
  (`neos/workflow/deep_analysis/model_roles.py:31-36`).
- effort 해석 체인에 `model_default` 슬롯, catalog 게이트, 거부 사유 로깅이 있다(`model_routing.py:121-193`).
  **가장 성숙한 정책 표면이다.**
- 비용 기록: `message_costs`/`user_cost_summary`(`neos/utils/cost_calculator.py`), Anthropic 캐시 상태 분류
  (`neos/providers/anthropic_usage.py:33-80`), DA 계층형 토큰 예산(`token_budget.py`).
- 유일한 cascade: `cost_router.DOWNGRADE_CHAIN`은 *검색 전략*을 강등하고 모델을 바꾸지 않으며, 기본 off다
  (`CostAwareRoutingConfig.enabled=False`, `schema.py:721-722`).

**막힌 곳.**

1. **비용과 품질이 조인되지 않는다.** `message_costs`와 DA grader·Jev·verdict 사이에 공통 태스크 클래스 키가 없다.
2. 라우팅은 정적 설정이고 "정책 버전"이라는 개념이 없다. shadow·A/B 평가 경로도 없다.
3. "싼 모델 먼저, 검증 실패 시 상향"하는 cascade가 모델 차원에는 없다.
4. subagent는 부모 모델을 그대로 물려받는다(`neos/coding/nested_spawn.py:54-56`). explore 자식을 싼 tier로 돌릴 수 없다.
5. DA dig/synth는 난이도와 무관하게 늘 `powerful`이다.

**레시피화 방안.**

- **Phase 0:** `message_costs.metadata`(jsonb)에 `task_class`, `run_id`, 결과 라벨을 넣는다. 스키마를 바꾸지 않고
  조인 키를 만드는 방법이다.
- **Routing Policy = 전역 레시피(YAML).**
  ```yaml
  recipe_id: routing/da-harness
  kind: routing_policy
  version: 3
  rules:
    - when: {task_class: da.dig, complexity: "<0.4"}
      use: {role: everyday, effort: medium}
      escalate_on: [verifier_fail, E_QUOTE_MISMATCH]   # → powerful
    - when: {task_class: coding.explore_child}
      use: {role: everyday}
  verifier: {eval_set: golden/da-regression@<sha>, metric: pass_rate, max_drop: 0.02, cost_target: "-30%"}
  ```
  역할(everyday/powerful)만 참조하고 모델 이름은 쓰지 않는다. 모델은 `models.yaml`이 해석한다. **그래서 레시피가
  모델 교체를 견딘다.** 두 역할 제한(`test_policy_stays_at_two_roles`)과도 충돌하지 않는다.
- **시험 무대는 `model_roles.py`다.** 설계상 DA의 유일한 `resolve_model` 호출 지점이다. `HARNESS_ROLES` 조회를
  정책 조회로 바꿔도 호출부는 그대로다. `run_manifest`에 `routing_policy@version`을 추가해 기록한다.
- **평가 방식:** 정책 변경은 golden 회귀 세트에서 **오프라인 shadow**로 먼저 돈다. 품질 하락이 한계 이하이고
  비용이 목표를 달성하면 PR로 승격한다. 판정 기준상 비용 단독은 근거가 될 수 없고 품질 유지가 전제다
  (DIRECTION §1.2).
- subagent 모델 선택: `SubagentTicket`/spawn 경로에 `role` 필드를 추가한다. 기본값은 부모 상속이고, 정책이
  지정하면 그 값을 쓴다.

---

## 4. 공통 기반 (레지스트리를 무엇 위에 세우나)

| 필요 | 기존 자산 | 판단 |
| --- | --- | --- |
| 저장소 | Postgres 단일 인스턴스, git | 새 DB·서비스 없음 (MICROSERVICE_REVIEW §0) |
| 생명주기 | `staged/approved/archived` (`lessons.py:17-20`) | 어휘 재사용, 테이블은 새로 |
| 버전 식별 | `manifest_version`, `prompt_hashes`, `rubric_digest` | 그대로 일반화 |
| 승인 | 전역 = PR 리뷰, 테넌트 = `approved_by` + 부분 유니크 인덱스(GEPA 초안 설계) | 두 계층 |
| 불변 감사 로그 | append-only `deep_analysis_events` + 트리거(D8), `coding_events` | 레시피 승격 이벤트도 여기에 |
| 테넌시 | `owner:{id}` 네임스페이스 (`policy.py:75-79`), id 단독 조회 금지 | 그대로 |
| 오프라인 작업 | `run_deep_analysis_job` 형태 (`neos/tasks/deep_analysis_job_task.py:204-237`), 전용 큐 | Celery on일 때만. in-process fallback 복제 금지 |
| 공급자 중립 형식 | `CanonicalMessage`/`ToolDefinition`/`ModelRequest` | 레시피 본문 형식 |

**하지 말아야 할 것** (저장소 결정 사항):

- 신호로부터 라이브 프롬프트·설정을 **자동 변경**하지 않는다(D19). 모든 증류기는 *후보를 만들고 멈춘다*.
- `judge.md`/`report_judge.md`를 mutator가 읽거나 쓰지 않는다(GEPA 초안 Non-goals). judge 레시피 개정은 사람이 한다.
- 죽은 경로(procedure lessons, Track F diagnostician-as-spawn — `docs/SUBAGENT_RUNTIME_DESIGN.md:55`)를 되살리지 않는다.
- run status나 self-report `VERDICT`를 단독 적합도(fitness)로 쓰지 않는다(Goodhart).

---

## 5. 목표 아키텍처

```
 ┌──────────── 신호 (대부분 있음) ────────────┐
 │ coding_events · deep_analysis_events ·     │
 │ Jev ledger · votes(+model) · user.friction │
 │ message_costs(+task_class) · coding_runs   │
 │ (+model/provider/prompt_hash)              │
 └───────────────┬────────────────────────────┘
                 │  오프라인 증류기 (Celery 전용 큐, 후보만 생성)
                 ▼
  failure-case capture │ tool-struggle weekly │ skill miner(autoskill 패턴)
  golden promoter      │ cost×quality report  │ GEPA optimizer
                 │
                 ▼  후보 = staged 레시피 (+provenance)
 ┌──────── 검증기 (해자) ────────┐
 │ eval cases (git, hash 주소)   │
 │ golden replay (cassette 패턴) │
 │ judge meta-eval (인간 라벨)   │
 │ validated_on 매트릭스         │
 └───────────┬───────────────────┘
             │  사람 승인
     ┌───────┴────────┐
     ▼                ▼
  전역: git PR      테넌트: recipe_versions
  + CI golden gate   (staged→approved, owner별 1개)
     │                │
     └──── 소비처 ────┘
  prompt builder · markdown_catalog · tool registry ·
  model_roles/resolve_model · learn_lessons 주입
```

---

## 6. 로드맵

각 Phase는 앞 Phase의 데이터에 의존한다. PR 크기는 기존 관례(작은 단위, 기능 플래그 기본 off)를 따른다.

### Phase 0 — 신호 위생 (새 개념 없음, 작은 PR 5개)

| # | 작업 | 근거 위치 | 해금되는 것 |
| --- | --- | --- | --- |
| 0-1 | `coding_runs`에 `model/provider/effort/prompt_hash` 컬럼 | `state.py:33-49`, `039` | golden 필터, 모델별 비교 |
| 0-2 | 👎 사유 UI → `/votes/feedback`, `Vote`에 model/turn 컬럼 | `vote_handlers.py:82-104`, `message-actions.tsx` | 인간 판단 라벨 |
| 0-3 | lesson 승인/보관 API + 관리 화면 | `lessons.py:51-54`, `gateway.py:631` | 기억 경로 개통 |
| 0-4 | `coding_tool_execution_total`에 `reason_bucket` 라벨 | `metrics.py:155`, `registry.py:75-93` | 도구별 struggle 집계 |
| 0-5 | `message_costs.metadata`에 `task_class`/`run_id` | `cost_calculator.py:213-214` | 비용↔품질 조인 |

부가: 재생성·중단·취소를 `user.friction` 이벤트로 남긴다. 코딩 태스크 결과 라벨은 테스트 통과, 사용자 확인, 👍 중
하나로 정한다(**결정 필요**, §9).

### Phase 1 — 레시피 기반

- §1.1 manifest 스키마를 확정한다. 전역 자산(judge.md, Jev rubric, coding skills, tool description, `HARNESS_ROLES`)에
  manifest를 붙인다. 처음에는 **기록만** 하고 검사는 경고 수준으로 둔다.
- `datasets/recipes/`: eval case JSONL 규약을 정한다. 해시 주소를 쓰고, 출처 필드를 필수로 둔다.
  `HARNESS_EVAL_CALIBRATION.md` 후보 세트 형식을 확장한다.
- `recipe_versions` 테이블 하나(테넌트 레시피)를 만든다. GEPA 초안의 overlay 테이블 설계(부분 유니크 인덱스,
  `FOR UPDATE` 승인 트랜잭션)를 **이 테이블로 일반화**한다.
- `validated_on` 매트릭스 CI: 주 1회, 그리고 `models.yaml` 변경 PR마다 돈다. 전역 레시피 eval을 공급자 2곳 이상에서
  실행한다.

### Phase 2 — 증류기 (오프라인, 후보만)

우선순위는 효과 대비 비용 순이다.

1. **Failure case capture** (DA ledger → 사례 후보). 이미 가장 풍부한 신호가 있다.
2. **Tool struggle 주간 리포트** + 상위 항목의 description PR 후보.
3. **Golden promoter** (0-1, 0-2 이후). 결과 검증 + 사람 확인 → golden 세트.
4. **Cost×quality 리포트** (0-5 이후). 태스크 클래스별 tier 대비 품질 표.
5. **Skill miner** (autoskill 파이프라인 + coding_events 소스).
6. **Judge meta-eval 정례화** (`harness_calibration.py`를 CI로).

### Phase 3 — 최적화기 (검증기가 갖춰진 뒤)

- GEPA 커널(`docs/GEPA_SELF_IMPROVEMENT_MIGRATION.md`)의 candidate component를 넓힌다. system overlay에 더해
  `tool:<name>` description, skill 본문을 포함한다. 평가기는 Phase 2의 eval case와 golden replay다. 결과는 staged
  레시피이고, 반영은 사람이 한다.
- Routing policy shadow 평가 → `model_roles.py` 정책 조회로 전환(플래그 기본 off).

### Phase 4 — 모델 증류

- Golden 궤적 → Canonical → SFT adapter → everyday/로컬 모델 미세조정. 조건은 테넌트 동의, 리댁션, 보관 기한 정책이다.
- few-shot 검색(pgvector)은 golden 세트가 수백 건 이상 쌓인 뒤에 한다. 그 전에는 효과를 잴 표본이 부족하다.

---

## 7. 해자 지표 — "증류가 되고 있는가"를 재는 법

| 지표 | 정의 | 지금 |
| --- | --- | --- |
| 레시피 검증 커버리지 | 전역 레시피 중 `verifier`가 연결된 비율 | DA 프롬프트 일부만 (golden gate) |
| 모델 교체 비용 | 새 모델을 `models.yaml`에 넣고 → 전 레시피 `validated_on` 갱신까지 걸리는 시간 | 측정 불가 (스위트 없음) |
| 신호 → 레시피 전환율 | 월간 staged 후보 중 approved 비율 | 0 (승인자 없음) |
| 판사 신뢰도 | judge와 인간 라벨의 일치율 | 기록 없음 |
| 실패 재발률 | 채택된 eval case와 같은 실패 코드가 이후 N주에 재발한 비율 | 측정 불가 |
| 비용당 품질 | 태스크 클래스별 golden pass rate / $ | 조인 불가 |

**"모델 교체 비용"이 핵심 지표다.** 레시피가 진짜 모델 비종속이면 이 값은 eval 1회분의 시간과 비용으로 수렴한다.

---

## 8. 기존 설계와의 관계

### 8.1 D19와 충돌하지 않는다

이 설계의 모든 증류기는 *후보 생성 + 사람 승인*이다. 전역 레시피는 PR 리뷰를, 테넌트 레시피는 `approved_by`를
거친다. D19가 금지한 것은 신호로부터의 **자동 변경**이고, 이 설계는 D19가 세운 "관측 + golden gate" 구조를
다른 다섯 경로로 복제하는 것이다.

### 8.2 GEPA 초안에 대한 제안

초안(`docs/GEPA_SELF_IMPROVEMENT_MIGRATION.md`, 미커밋)은 방향이 맞다. 두 가지를 조정하자고 권한다.

1. **`gepa_opt_overlays`를 전용 테이블로 만들지 말고 `recipe_versions`(kind=`prompt_overlay`)로 둔다.** 초안이
   `learned_lessons` 재사용을 거부한 근거(clip, cap, demotion)는 여전히 옳다. 다만 overlay 전용 테이블을 따로 만들면
   곧 tool description, routing policy에도 같은 테이블이 필요해져 생명주기가 늘어난다(DIRECTION §1.2의 패러다임 공존 비용).
   `gepa_opt_runs/examples/candidates/example_scores`는 최적화기 내부 상태이므로 그대로 둔다.
2. **초안이 비워 둔 "caller-supplied evaluator"를 채울 1순위는 Phase 2의 eval case와 golden replay다.** 초안의
   Goodhart 경고(run status·VERDICT 단독 적합도 금지)와 맞는다.

### 8.3 미확인 / 이번에 읽지 않은 것

- `docs/ROADMAP.md`, `docs/HARNESS_WHITEPAPER.md` 전문. 로드맵 순서가 여기와 충돌하는지 **미확인**.
- Phoenix(`neos/observability/phoenix_client.py`) 트레이스가 도구 호출 단위를 담는지 **미확인**. 담는다면 0-4의 일부를 대신할 수 있다.
- `load_skill.v1` 호출이 별도 coding event 종류로 남는지 **미확인**.
- `skills/skill-creator/scripts/run_loop.py`가 반복 간 버전을 관리하는지 **미확인**.

---

## 9. 결정이 필요한 것

1. **코딩 태스크의 결과 라벨을 무엇으로 정의하나?** 후보는 워크스페이스 테스트 통과, 사용자 명시 확인, 👍, 판사 점수다.
   Golden·라우팅·스킬 성공률 모두 이 정의에 달려 있다. *권고:* 테스트 통과 AND 사용자 비거부(취소·재요청 없음)를 1차로,
   판사 점수는 보조로 둔다.
2. **전역/테넌트 2계층을 받아들이나?** 받아들이면 전역 레시피는 새 테이블 없이 git+CI로 끝난다.
3. **GEPA 초안의 overlay 테이블을 `recipe_versions`로 합칠 것인가**(§8.2).
4. **궤적의 학습 사용 동의 정책.** Phase 4 이전에 법무·약관 판단이 필요하다.
5. **인간 라벨링 예산.** judge meta-eval과 golden 승격은 사람 시간이 든다. 주당 몇 건을 쓸지 정해야 Phase 2 속도가 정해진다.
