# 코딩 루프 조사 계약 — 트랙 J0

> **상태:** 계약 초안 (2026-09-15). 코드 없음. 로드맵 [§4](DEEP_ANALYSIS_HARNESS_ROADMAP.md)의 J0이다.
> **이 문서가 정하는 것:** J1~J4가 구현할 스펙·도구·증거·채점·이벤트·설정의 모양.
> **정하지 않는 것:** 프롬프트 본문, 표본 설계(사전 등록이 따로 한다), 기본값을 켜는 시점.
>
> 구현이 착지하면 이 문서의 해당 절을 "착지(커밋)"로 바꾼다. 문서와 코드가 어긋나면 **코드가 이긴다** —
> 그리고 어긋남을 이 문서에 적는다.

---

## 0. 한 문장

심층분석 워커를 **샌드박스에서 코드를 짜고 돌리는 서브에이전트**로 바꾸되, 워커가 원장에 쓰지 않고,
샌드박스에는 네트워크가 없고, **계산한 사실은 채점기가 다시 돌려 같은 값을 얻을 때만 verified**가 된다.

## 1. 불변식 — 구현 전에 테스트로 먼저 고정한다

| # | 불변식 | 고정하는 테스트(J1·J2) |
|---|---|---|
| I1 | `deep_analysis.code_research_enabled = False`이면 워커 프롬프트·도구 목록·이벤트 어휘가 **바이트 단위로** 이전과 같다 (S9) | 플래그 off 스냅샷 비교 |
| I2 | 코딩 워커는 원장 쓰기 경로를 갖지 않는다. `submit.v1`의 결과는 오케스트레이터가 쓴다 (P2) | 워커 의존성에 `Ledger` 가 주입되지 않음을 import·주입 양쪽으로 검사 |
| I3 | 샌드박스 프로파일 `research-offline-v1`은 `network=none`이다. 네트워크를 요구하는 요청은 **거절**한다 | 프로파일 로더 거절 테스트 |
| I4 | 샌드박스 안의 바이트는 `fetch.py`가 받은 blob뿐이다. 워커가 쓴 파일은 증거가 될 수 없다 | `ComputedEvidence.inputs` 가 원장 blob 이 아니면 `E_COMPUTE_INPUT_UNFETCHED` |
| I5 | 재현되지 않는 계산은 verified가 아니다 (S7) | 재실행 digest 불일치 → 거절 |
| I6 | 자식의 모든 모델 호출이 질문 예산 `TokenBudget.reserve()`를 거친다 | fold 사용량 ≠ 예산 청구를 따로 단언 |
| I7 | development 밖에서 플래그를 켜려면 B2 게이트가 필요하다 — 설정 검증이 거부한다 (S10, 결정 2026-09-15) | `AppConfig` 검증 테스트 |

> **I7 의 "B2 게이트"를 무엇으로 읽는가 (2026-09-20, 구현 주석).**
> 설정에 `b2` 라는 값은 **없다**(확인함). 그래서 J1 은 게이트를 **관리형 평면**으로 읽는다 —
> `sandbox.provider == "managed"` 이고 `sandbox.managed.enabled` 일 때만 development 밖에서 켤 수 있다.
> 근거는 §4.5 의 "Docker 를 production 경계로 쓰지 않는다" 와, 이미 있는 "production + docker 거절"
> 검증(`schema.py`)이다. **이것은 계약이 적어 준 술어가 아니라 구현의 해석이다** — B2 가 자기 플래그를
> 갖게 되면 이 줄과 검증을 함께 고친다.

## 2. 서브에이전트 스펙 셋

`neos/subagent/catalog.py`의 fail-closed 카탈로그에 **셋을 더한다.** 모델이 런타임에 타입을 만들지 않는다.

| 스펙 | 하는 일 | 도구 | `can_spawn` | 역할(모델 라우팅) |
|---|---|---|---|---|
| `research` | 질문 하나를 조사해 quote 클레임·서브질문·막다른 길을 제안 | `search.v1` `fetch.v1` `list_tree.v1` `read_file.v1` `search_text.v1` `write_file.v1` `execute.v1` `load_skill.v1` `check_claims.v1` `submit.v1` | ❌ | `dig` |
| `analyze` | **같은 질문의** verified 클레임만 입력으로 계산 클레임을 제안 (2026-09-17 결정) | `research`에서 `search.v1`·`fetch.v1` 제외 | ❌ | `dig` |
| `compose` | 클레임 파일을 읽어 리포트를 워크스페이스에 쓰고 제출 | `list_tree.v1` `read_file.v1` `search_text.v1` `write_file.v1` `edit_file.v1` `check_claims.v1` `submit.v1` | ❌ | `synth` |

- **judge는 스펙이 아니다.** 판정자는 지금처럼 오케스트레이터가 부르고, worker와 같은 인스턴스일 수 없다.
- **`sandbox_mode` 는 `NONE` 이다 (2026-09-20, 구현 주석).** 위 표는 도구·`can_spawn`·역할만 정하고
  `SubagentSpec.sandbox_mode` 를 **적어 주지 않았다.** 남은 셋 중 `WORKTREE` 는 git 워크트리를 만드는
  코딩 전용 모드라 저장소가 없는 DA 에 맞지 않고, `PARENT_RO` 는 부모 바인딩을 물려받는다는 뜻인데
  조사 자식에게는 물려받을 부모 워크스페이스가 없다. 그래서 `NONE` 이다 — 서브에이전트 런타임은
  워크스페이스를 붙이지 않고, `/evidence`·`/workspace` 는 **오케스트레이터가** `research-offline-v1`
  프로파일로 띄운 샌드박스가 갖는다. **계약이 적어 준 값이 아니라 구현의 해석이다.**
- 깊이는 0. 서브질문은 **제안**이고 분할은 오케스트레이터가 한다(설계 정본 §6.3과 같다).
- 걸음 상한·벽시계·토큰 상한은 전부 settings다. 매직넘버 금지.
- 자식 프롬프트는 **자율 모드**다. Anthropic 공식 Fable 5.1 가이드의 자율 완수 블록(P-01)과 범위 블록(P-02)을
  공식 문구 그대로 쓴다([로드맵 §10.5](DEEP_ANALYSIS_HARNESS_ROADMAP.md)). P-02의 "코드 변경 범위"는
  조사에서 **"질문을 넓히지 않는다"** 로 읽힌다 — `worker_brief.md`의 범위 규칙과 같은 자리다.

## 3. 도구 계약

### 3.1 `fetch.v1` — retrieval의 유일한 입구

```
input : {"url": str}
output: {"raw_ref": str(16), "status": int, "path": "/evidence/<raw_ref>.txt",
         "bytes": int, "truncated": bool}
```

- 구현은 `neos/workflow/deep_analysis/fetch.py` **하나**다. 도구는 얇은 어댑터다.
- 성공한 fetch는 오케스트레이터가 blob을 원장에 기록한 **뒤에** 샌드박스의 `/evidence/`에 읽기 전용으로 나타난다.
- 본문은 도구 결과에 싣지 않는다. 경로만 준다(점진 공개, CE ③). base64 본문은 절대 결과에 넣지 않는다(R-06).
  이 줄은 이제 **규칙이 아니라 강제된다** — `neos/coding/redact.py`의 `strip_binary_payloads`가
  도구 결과 매핑이 만들어지는 **두 자리**(`loop/durable.py`·`subagent_port.py`)에서 `data_b64`를 떼고
  `data_b64_omitted: true`만 남긴다(K6, 2026-09-19). 지키는지 확인하지 않는 규칙은 규칙이 아니다.
- 웹 원문은 적대적 입력이다 — 설계 부록 A4의 untrusted 경계를 그대로 쓴다.

### 3.2 `execute.v1` — `research-offline-v1` 프로파일

| 항목 | 값 |
|---|---|
| 네트워크 | 없음 |
| 마운트 | `/evidence` 읽기 전용 · `/workspace` 읽기-쓰기(질문별) — ⚠️ **development 에서는 읽기 전용이 아니다**, 아래 참조 |
| argv allowlist | `python3` 만. 셸 없음 |
| 이미지 | digest 고정. digest가 매니페스트 구성 지문에 들어간다 |
| 이미지 내용물 | 파이썬 + **분석 번들**: pandas · numpy · pypdf · beautifulsoup4 (2026-09-17 결정). 목록은 잠금 파일로 고정한다 — 버전이 움직이면 재실행이 재현되지 않는다 |
| 한도 | CPU 초·메모리·출력 바이트·프로세스 수 — 전부 settings |
| 등록 | B2와 **같은 named profile 체계**. DA 전용 경로를 만들지 않는다 |

> ⚠️ **development 경로의 두 가지 downgrade (2026-09-20, 구현 확인).** 위 표는 관리형 provider 를
> 전제로 적혀 있다. Docker provider 에서는 둘이 성립하지 않는다:
>
> 1. **읽기 전용 마운트가 없다.** Docker provider 에는 바인드 마운트 기능이 없다(볼륨 + tmpfs 뿐).
>    그래서 `open_question_sandbox` 는 증거를 **워크스페이스 안에 쓴다**(`evidence/<raw_ref>.txt`).
>    워커가 그 파일을 고쳐 쓰는 것을 막는 장치는 **없다.** 막는 것은 파일시스템이 아니라 채점기다 —
>    `ComputedEvidence.inputs` 가 원장 blob 이 아니면 `E_COMPUTE_INPUT_UNFETCHED`(I4)
> 2. **Docker provider 는 profile 을 읽지 않는다.** `docker.py` 에 `profile` 이라는 단어가 한 번도
>    나오지 않는다(확인함). `research-offline-v1` 이 `DENY_ALL` 인 것은 레지스트리의 사실일 뿐이고,
>    그 경로의 실제 격리는 `sandbox.docker.network_mode` 하나에서 온다. 그래서 **설정 검증이 둘을
>    묶는다** — code research 가 켜진 채 provider 가 docker 이면 `network_mode=none` 이 아니면 거절한다.
>    묶지 않으면 "네트워크 없음" 이라고 적힌 프로파일 아래에서 컨테이너에 네트워크가 붙는다
>
> 진짜 읽기 전용과 profile 강제는 관리형 provider 에만 있고, 그것은 **B2 게이트 뒤**다(§4.5).

### 3.3 `check_claims.v1` — 채점기를 읽기 전용으로

```
input : {"claims": [ProposedClaim, ...]}           # submit.v1 과 같은 모양
output: {"results": [{"index": int, "ok": bool, "codes": [str]}]}
```

- `DeterministicGrader`를 **원장에 쓰지 않고** 돌린다. 계산 클레임은 재실행까지 한다.
- 워커의 비용 절감 도구다. **판정은 여전히 오케스트레이터 쪽에서 다시 한다** — 워커가 초록을 봤다는 사실은 증거가 아니다.

### 3.4 `submit.v1` — 출력 계약

"JSON 외 출력 금지" 문장을 대체한다(CE ②). 스키마는 `worker_brief.md` v5의 JSON과 같은 필드를 갖고,
클레임에 `kind`가 붙는다.

```
{
  "status": "completed" | "partial",
  "claims": [QuoteClaim | ComputedClaim],
  "self_assessment": float,
  "proposed_subquestions": [{"text": str, "value_est": float}],
  "dead_ends": [str],
  "repairs": [...],                       # 기존과 같다
  "report_path": str | null               # compose 만
}
QuoteClaim    = {"kind": "quote", "text", "confidence", "evidence": [{"source_url", "excerpt", "raw_ref"}]}
ComputedClaim = {"kind": "computed", "text", "confidence", "computation": ComputedEvidence}
```

- Fable 5.1은 강제 `tool_choice`를 400으로 거절한다. 제출은 `auto` + 지시 + `strict: true` 스키마로 받는다.
- `submit.v1`을 부르지 않고 턴이 끝나면 `partial`로 처리하고 원장에 이유를 남긴다 — 조용한 degrade 금지.

## 4. 계산 증거 `ComputedEvidence`

```
script_ref       blob 저장소의 스크립트 바이트 (sha256)
inputs           [raw_ref, ...]            — 전부 원장 fetch blob
premises         [claim_id, ...]           — 입력 수치 각각의 verified quote 클레임
runtime          {"profile": "research-offline-v1", "image_digest": str}
output_digest    sha256(정규화된 stdout)
claimed_value    클레임 본문이 인용하는 값(문자열 그대로)
```

**stdout 정규화:** 줄 끝 `\r\n`→`\n`, 끝 공백 제거. **그 외는 건드리지 않는다** — 숫자 반올림을 정규화에 넣으면
채점기가 "비슷하면 같다"를 판정하게 된다.

## 5. 채점 규칙

기존 `E_NO_EVIDENCE` · `E_SOURCE_DEAD` · `E_QUOTE_MISMATCH` · `E_CONFIDENCE_INFLATED`는 quote 클레임에 그대로 적용한다.
계산 클레임에는 아래가 **추가로** 걸린다. 순서대로 평가하고 첫 실패에서 멈춘다.

| 코드 | 조건 |
|---|---|
| `E_COMPUTE_INPUT_UNFETCHED` | `inputs` 중 원장 blob이 아닌 것이 있다 |
| `E_COMPUTE_PREMISE_UNVERIFIED` | `premises` 중 verified quote 클레임이 아닌 것이 있다 |
| `E_COMPUTE_NONDETERMINISTIC` | 같은 입력으로 **두 번** 돌려 digest가 다르다 |
| `E_COMPUTE_NOT_REPRODUCED` | 재실행 digest가 `output_digest`와 다르다 |
| `E_COMPUTE_VALUE_MISMATCH` | `claimed_value`가 정규화된 stdout에 문자 그대로 없다 |
| confidence 상한 | `premises` 클레임 상한의 **최소값** |

- **재실행은 커밋 경로 밖에서 한다**(설계 부록 A2와 같은 이유). 채점 단계의 사전 작업이고 결과만 원장에 온다.
- 재실행 한도 초과는 `E_COMPUTE_NOT_REPRODUCED`가 아니라 **별도 이벤트**로 남긴다 — 비용 문제와 재현성 문제를 섞지 않는다.
- 판정자(AgenticGrader)는 계산 클레임에서 **"이 계산이 이 질문에 대한 답인가"** 만 본다. 산술은 결정론 채점기의 몫이다.

## 6. 이벤트 kind

모두 `tests/fixtures/deep_analysis_event_kinds.json`에 먼저 들어가고, FE 라벨 짝을 양방향 테스트로 건다.

| kind | 쓰는 곳 | payload 핵심 |
|---|---|---|
| `code_worker_started` | 오케스트레이터 | question_id · spec · subagent run_id · profile · image_digest |
| `code_worker_submitted` | 오케스트레이터 | claim 수(kind별) · report_path 여부 |
| `code_worker_unsubmitted` | 오케스트레이터 | 이유(turn cap · refusal · stall) |
| `evidence_fetched_for_sandbox` | 오케스트레이터 | raw_ref · path |
| `compute_reexecuted` | 채점 사전 작업 | claim_id · digest 일치 여부 · 소요 |
| `compute_reexecution_capped` | 채점 사전 작업 | claim_id · 넘은 한도 |

`claim_rejected`의 `code`에 §5의 코드가 새로 흐른다. 새 kind를 만들지 않는다.

## 7. 설정 키 (전부 기본 off·보수값)

```yaml
deep_analysis:
  code_research_enabled: false
  code_research:
    specs_enabled: [research]          # analyze·compose 는 표본 경계마다 하나씩 연다
    sandbox_profile: research-offline-v1
    max_steps: ...                     # 2·max_turns + 1 법칙을 따른다
    wall_clock_sec: ...
    reexecution:
      cpu_sec: ...
      memory_mb: ...
      stdout_bytes: ...
```

값은 J1에서 기존 `worker` 한도와 같은 크기로 시작하고, **바꾸는 커밋은 표본 경계**다.

## 8. 표본 계보

- 플래그를 켜는 커밋부터 **C-계열**이다. #1~#23과 어떤 수치도 나란히 놓지 않는다.
- `specs_enabled`에 스펙을 하나 더하는 커밋마다 경계다. 한 표본에 스펙 둘을 새로 넣지 않는다.
- J3 섀도는 표본이 아니다 — 저장된 blob·카세트만 쓰고 원장에 쓰지 않는다.

## 9. 결정과 남은 질문

**결정 (2026-09-17, 사용자):**

1. **분석 번들을 이미지에 넣는다** — pandas · numpy · pypdf · beautifulsoup4. 계산 클레임의 주 사용처(표 추출, 수치 비교)가 바로 돌아간다.
   대가는 명시한다: **패키지를 더하는 커밋은 새 image digest이고 곧 새 표본 경계다.** 버전은 잠금 파일로 고정한다
2. **compose는 기존 `final_compose` 계약을 그대로 파일로 쓴다** — 마크다운 + `[C:claimid]`.
   게이트·채점기·프론트가 이미 그 형식을 읽으므로, §7 인용 생산 사슬의 계보가 끊기지 않는다
3. **analyze는 같은 질문의 verified 클레임만 본다** — 귀속이 분명한 가장 좁은 범위.
   질문 경계를 넘는 비교가 필요하면 **부모가 그 질문을 만든다**(서브질문 제안 경로). 형제·루트 범위는 열지 않는다

**결정 (2026-09-20, 사용자):**

4. **`/evidence` 크기 상한은 거절이다** — 질문별 blob 합계가 한도에 닿으면 **새 fetch 를 거절하고**
   이벤트를 남긴다. 이미 있는 blob 은 빼지 않는다.
   - 축출을 고르지 않은 이유: 사라진 blob 을 `inputs` 로 가진 계산 클레임이 채점 때
     `E_COMPUTE_INPUT_UNFETCHED` 로 죽는다. 제출될 때는 멀쩡했던 증거가 **나중에 조용히** 무효가 되는
     모양이고, 이는 §13 "조용히 바뀌는 것이 시끄럽게 깨지는 것보다 위험하다" 에 정면으로 걸린다
   - 대가도 적는다: **조사가 그 지점에서 멈춘다.** 대신 멈춘 자리가 이벤트로 남아 눈에 보인다
   - I4 와 같은 방향이다 — 샌드박스 안의 바이트는 원장 blob 뿐이고, 그 집합은 **줄지 않는다**

5. **코드 경로의 blob 커밋은 건별이다** — `fetch.v1` 이 성공하면 오케스트레이터가 **그 자리에서**
   원장에 쓰고, 그 뒤에 `/evidence/<raw_ref>.txt` 가 샌드박스에 나타난다.
   - 기존 경로는 워커가 끝난 뒤 `commit_blobs(result.blobs)` 로 **배치** 커밋한다. 그대로 두면
     워커가 **방금 가져온 것을 읽을 수 없어** "조사하고 그 자리에서 계산한다"는 J 의 핵심이 사라진다
   - 단일 기록자(P2)는 그대로다. 워커는 여전히 원장을 갖지 않고, 커밋은 오케스트레이터가 한다 —
     바뀌는 것은 **시점**뿐이다(배치 → 건별). 플래그가 꺼져 있으면 기존 배치 경로는 바이트 단위로 같다(I1)
   - 대가: 코드 경로에서 한 질문의 blob 커밋 횟수가 fetch 수만큼 늘어난다. `commit_blobs` 는 이미
     락을 잡고 blob 단위로 저장하므로 새 진입점은 필요 없다

**남은 질문:** 없다. J1 은 착수 가능하다.
