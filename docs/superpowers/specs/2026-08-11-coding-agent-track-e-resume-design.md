# 트랙 E 재개 — 언블록 + Managed Sandbox Task 5

**작성일:** 2026-08-11
**작업 브랜치:** `feature/managed-sandbox-control-plane` (워크트리 `.worktrees/managed-sandbox-control-plane`)
**범위:** 로드맵 트랙 E의 재개 차단 요인(CA2·CA3·CA4·CA5)을 해소하고 플랜 14의 Task 5를 구현한다
**범위 밖:** 플랜 14의 Task 6–10(CA1 잔여) · CA6(caching-advisor 브랜치 판정)

**근거 문서:**

| 문서 | 역할 |
|---|---|
| [DEEP_ANALYSIS_HARNESS_ROADMAP.md](../../DEEP_ANALYSIS_HARNESS_ROADMAP.md) §12 | 트랙 E 정본 — 출하 기준 E-S1~E-S4, 인벤토리 CA1~CA7 |
| [coding_agent_task_resume.md](../../coding_agent_task_resume.md) | 재개 절차와 Task 1–4 범위 결정 |
| `docs/superpowers/plans/2026-07-25-managed-sandbox-control-plane.md` | 플랜 14 — Task 5는 `:553` |
| `.worktrees/managed-sandbox-control-plane/.superpowers/sdd/2026-07-25-managed-sandbox-control-plane/progress.md` | SDD 원장 (⚠️ 이중 기록 + Task 4 누락) |

---

## 1. 이 스펙이 기존 문서를 정정하는 곳

계획을 세우기 전에 저장소 상태를 실측했다. **네 곳에서 문서가 틀렸거나 불완전하다.**
아래는 이 스펙의 전제이며, 로드맵·재개 문서에도 반영해야 한다.

### 1.1 CA2는 "출처 불명"이 아니라 CA5-b의 구현이다

재개 문서 §4는 미커밋 diff를 *"`CLAIM_TOKEN_LABEL` 신설, `_replayed_allocation()` 추출 …
Task 5의 선행 작업으로 보이나"* 로 서술한다. 실제 diff는 그보다 크다:

```
_claim_volume_name()        _ownership_volume_name()      _wait_for_claim_owner()
_verify_resource_metadata() _expected_destroy_metadata()  _resource_labels()
_label_args()               _inspect_volume_optional()    _remove_volume_if_present()
```

Docker 볼륨을 **클레임 락으로 쓰는 크로스 프로세스 원자적 create**다. 즉 Task 5 선행
작업이 아니라 **CA5의 둘째 우려**(§12.2 "크로스 프로세스 원자적 create 미노출")를 푸는 코드다.

판정 근거 넷:

1. 내용이 CA5-b와 정확히 일치한다
2. Task 4 커밋 `89196755`(2026-07-25 18:09:13) 12분 뒤 mtime(18:21) — **동일 세션**
3. `pytest tests/coding/managed/adapters` **30 passed** (Task 4 커밋 시점 17 → +13)
4. 신규 테스트가 클레임 경로를 직접 겨냥한다
   (`test_partial_destroy_can_be_confirmed_on_retry[claim]`,
   `test_inspect_rejects_disagreement_with_docker_owner_label`)

> 전례 2회와 절차는 같다 — *"의존 작업 전에 소유권을 판정하라"* 를 지켰고, 이번 판정
> 결과가 "채택"일 뿐이다. 보존 → 판정 → 처리 순서는 유지했다.

### 1.2 `runtime.py`가 §12.3이 세지 않은 4번째 충돌 파일이다

§12.3의 충돌면 표는 **브랜치가 이미 건드린 파일** 기준이라 3개(`schema.py`·
`neos.default.yaml`·`metrics.py`)를 센다. 그러나 플랜 Task 5 Step 4는
`neos/coding/runtime.py`를 **앞으로 수정**하도록 되어 있고, dev는 merge-base
(`c5f881a4`) 이후 그 파일을 2커밋 +18/−3으로 바꿨다:

```
7f4beca1  feat(coding): wrap the production model so its calls are collected too   ← D1c
b0fd574e  feat: route backend workloads by model role
```

낡은 워크트리에서 Task 5를 하면 `TrackedCodingModel` 배선도 역할 라우팅도 없는
`runtime.py` 위에 어댑터 레지스트리를 얹게 된다. Task 5 Step 5의 검증 커맨드에 있는
`tests/coding/sandbox/test_runtime_ownership.py`도 dev에서 +28줄 늘었다.

**교훈:** 충돌면을 "이미 바꾼 파일"로만 재면 과소평가된다. **앞으로 바꿀 파일**까지
포함해야 병합 시점 판단이 나온다.

### 1.3 dev와 브랜치는 충돌 없이 합쳐진다 (실측)

```bash
git merge-tree --write-tree --name-only dev feature/managed-sandbox-control-plane
# exit=0, 트리 OID만 출력 → 충돌 0건
```

§12.3이 `schema.py`를 "🟡 인접줄 충돌 가능"으로 남겨둔 것은 추정이었고, 실제로는
충돌하지 않는다. 이 명령은 아무것도 체크아웃하지 않으므로 안전하며, §12.3의 재현
절차에 추가할 가치가 있다.

**따라서 CA3의 비용은 사실상 0이다.** §12.3은 병합 비용의 지배 요인을 드리프트가
아니라 CA2라고 판단했는데, §1.1이 CA2를 판정 가능한 것으로 확정했으므로 **둘 다 더는
지배 요인이 아니다.** 남은 실질 제약은 §1.2의 `runtime.py` 순서 문제 하나다.

### 1.4 CA4는 "이중 기록"이 아니라 "이중 기록 + Task 4 누락"이다

`progress.md`는 24줄이고 **두 블록 모두 Task 3에서 끝난다. Task 4 항목이 없다.**
즉 §12.2의 "Task 4 ✅"와 CA5의 "Task 4가 남긴 우려"는 **원장 근거가 없고**
커밋 존재 + 재개 문서 산문에만 기댄다. §1 상단의 "플랜 체크박스를 믿지 말 것" 규칙이
한 단계 더 나쁘게 적용된다.

### 1.5 E-S4에 회귀 가드가 없다

§12.6은 E-S4를 유일한 ✅로 적고 측정법을 *"`TrackedCodingModel` 배선 유지"* 라고 한다.
그러나 그 배선을 검증하는 테스트가 저장소에 **없다.** `TrackedCodingModel`을 언급하는
테스트는 `tests/dataset/test_adapters.py` 하나뿐이며 래퍼 자체의 단위 테스트다.
`_prepare_real_coding_loop`이 실제로 감싸는지는 아무도 보지 않는다 — 그리고
**Task 5가 정확히 그 함수를 편집한다.**

---

## 2. 결정 사항

| # | 결정 | 근거 |
|---|---|---|
| **E-D1** | CA2를 **CA5-b 경화 작업으로 채택**하고 리뷰 후 별도 커밋으로 확정한다 | §1.1 |
| **E-D2** | 합류는 **리베이스가 아니라 `dev` → 워크트리 방향 merge** | 리베이스는 11커밋 해시를 재작성하는데, `progress.md` 원장이 그 해시로 계보를 기록한다. **CA4를 푸는 데 쓸 근거가 먼저 사라진다** |
| **E-D3** | CA5를 **CA5-a / CA5-b로 분리**하고 둘 다 이번 범위에 넣는다 | §1.1이 CA5-b만 해소한다. CA5-a는 그대로 남아 있다 |
| **E-D4** | CA5-a는 **provider가 라벨을 소유하는 안**으로 구현한다 | §4 |
| **E-D5** | E-S4 회귀 가드를 **Task 5보다 먼저** 만든다 | §1.5 — 순서가 반대면 가드는 Task 5가 만든 상태를 고정할 뿐이다 |

---

## 3. 작업 단위와 순서

여섯 단위를 순차 실행한다. 각 단위는 커밋 경계이며, 완료 기준을 못 채우면 다음으로
넘어가지 않는다.

| # | 단위 | 산출 | 완료 기준 |
|---|---|---|---|
| **U1** | CA2 소유권 확정 | 커밋 1개 | `git status --short` 빈 출력 · `tests/coding/managed` 76 passed 유지 |
| **U2** | CA4 원장 정합 | `progress.md` 정정 블록 (**덧붙이기**) | Task 4 항목 존재 · 실제 계보 11해시 명시 |
| **U3** | dev 합류 (E-D2) | merge 커밋 1개 | 충돌 0건 · `tests/coding` 457 passed · `tests/coding/managed` 76 passed |
| **U4** | E-S4 회귀 가드 | 테스트 1개 | `_prepare_real_coding_loop`이 `TrackedCodingModel`을 반환함을 단언 |
| **U5** | CA5-a 확장점 | 커밋 1개 | `docker_shadow.py`에 `provider._` 접근 0건 |
| **U6** | Task 5 | 플랜 `:553`의 5스텝 | 플랜 Step 5 검증 커맨드 통과 |

**순서의 근거:**

- **U1 → U3**: 미커밋 상태로 머지하면 소유권 판정의 근거(어느 줄이 누구 것인지)가
  머지 결과에 섞인다. 먼저 커밋해 고정한다.
- **U2 → U3**: 원장이 커밋 해시로 계보를 적는다. 머지 커밋이 끼면 `git log` 선형성이
  깨져 판독이 어려워진다. 해시가 깨끗할 때 정리한다.

**U2의 정리 방식 — 기존 24줄을 지우지 않는다.** 이중 기록된 두 블록을 그대로 두고
**아래에 정정 블록을 덧붙인다.** 어느 블록이 실제였는지, Task 4가 왜 누락됐는지,
CA2를 어떤 근거로 채택했는지를 그 블록에 적는다. 원장을 재작성하면 §1.4가 지적한
문제(원장이 자기 이력을 잃는 것)를 한 번 더 저지르게 된다. 실제 계보는
`591640ce → 29ab632d → 777fdd33 → 79645f2e → 8b6ef183 → d8f4e2e4 → d308443e →
9245d5d5 → 2d38f1a6 → 3e3935f1 → 89196755`이다.
- **U4 → U6**: E-D5.
- **U5 → U6**: U5가 `docker_shadow.py`를 바꾸고 U6은 그 어댑터를 레지스트리에 배선한다.
  반대 순서면 배선을 두 번 만진다.

---

## 4. U5 — CA5-a 설계

### 4.1 실제 결함은 셋이다

재개 문서는 *"커맨드 러너를 감싸고 private 속성으로 config를 읽는다"* 로 서술하나
코드를 읽으면 셋이다:

| | 위치 | 문제 |
|---|---|---|
| ① | `docker_shadow.py:95` | `provider._runner = self._runner` — **소유하지 않은 provider를 제자리에서 변형**한다. 이후 그 provider의 모든 호출이 래퍼를 통과한다. ContextVar 가드(라벨 없으면 통과)로 동작은 안전하나, 관리형 어댑터가 데이터 플레인 객체를 영구 교체하는 구조다 |
| ② | `docker_shadow.py:70` | `values.index("--user")` — docker argv에 **위치 기반 수술**을 한다. `docker.py`가 `--user`를 넘기지 않게 바뀌는 순간 런타임 `ValueError` |
| ③ | `docker_shadow.py:101,126` | `provider._config` 읽기 (network mode · image identity) |

### 4.2 채택안 — provider가 라벨을 소유한다

`DockerSandboxProvider`에 공개 라벨 확장점을 낸다:

- `resource_labels(labels: Mapping[str, str])` 컨텍스트 매니저를 공개한다
- provider가 argv를 조립할 때 **자기 자신이** `--label`을 붙인다
- `docker_shadow.py`는 `_ManagedLabelRunner`와 `provider._runner` 대입을 **삭제**하고
  이 컨텍스트 매니저를 쓴다
- ③은 좁은 read-only property 또는 capability 산출 메서드로 처리한다

**①·②가 동시에 해소된다** — 래핑도 변형도 없고, argv 지식이 argv를 만드는 쪽에 남는다.

변경 파일은 `neos/coding/sandbox/docker.py` + `neos/coding/managed/adapters/docker_shadow.py`
둘뿐이다. `docker.py`는 dev·브랜치 **양쪽 다 merge-base 이후 0커밋**이라 충돌 위험이 없다.

### 4.3 기각안

- **`.command_runner`/`.config`를 공개 property로 승격** — ③만 해소하고 ①·②가 남는다. 불충분.
- **`SandboxProvider` 기반 계약에 `labels=` 파라미터 추가** — 가장 깨끗하나 Memory provider까지
  계약이 번져 범위가 커진다. 이번 범위 밖.

---

## 5. U6 — Task 5에서 지킬 것

플랜 `:553`의 5스텝을 그대로 따르되 셋을 추가로 고정한다.

1. **Task 1 결정 #1 이행.** `transition_allocation`은 순수 함수로 두고 version/fence
   검사는 repository claim/commit에 넣는다. 원장 5번 줄이 *"version/fence checks are
   mandatory in Task 5 repository claim/commit"* 로 적은 약속의 만기일이 이 태스크다.
2. **`runtime.py` 편집 시 D1c 보존.** 어댑터 레지스트리는 *샌드박스 provider* 축이고
   `TrackedCodingModel`은 *모델* 축이라 `_prepare_real_coding_loop` 안에서 직교한다.
   실수는 U4의 가드가 잡는다 (§12.4의 *"`runtime.py`를 건드리는 작업은 D1c의 회귀
   가드를 함께 본다"* 가 요구하는 것이 바로 이 가드다).
3. **`managed.enabled=false`에서 기존 Memory/Docker 동작 불변.** 플랜 Step 4의 명시
   조건이며, `sandbox.enabled` · `coding_model.enabled`가 여전히 `False`인 현 상태와
   일치한다.

`ProviderReferenceCipher`는 플랜대로 AES-GCM + 버전 키 + `allocation_id:provider:generation`
AAD로 구현한다. 키는 기존 시크릿 설정 경유이고, 복호화/인증 실패는
`MANUAL_RECOVERY_REQUIRED` + `provider_auth_error`로 매핑하며, 평문 참조는 저장·로깅하지 않는다.

---

## 6. 검증 게이트

각 단위 종료 시 실행한다.

```bash
cd /Users/ywsung/Desktop/neos/.worktrees/managed-sandbox-control-plane

# 테스트
GOOGLE_API_KEY=test-key /Users/ywsung/Desktop/neos/.venv/bin/pytest -q tests/coding
GOOGLE_API_KEY=test-key /Users/ywsung/Desktop/neos/.venv/bin/pytest -q tests/coding/managed

# 린트
/Users/ywsung/Desktop/neos/.venv/bin/ruff check neos/coding tests/coding
/Users/ywsung/Desktop/neos/.venv/bin/ruff format --check neos/coding tests/coding

# U3 직전 충돌면 재확인 (비파괴)
git merge-tree --write-tree --name-only dev feature/managed-sandbox-control-plane
```

**기준선 (2026-08-11 실측):**

| 스위트 | 값 | 비고 |
|---|---|---|
| `tests/coding` (dev) | 457 passed / 16 skipped | 로드맵 §12.0. ⚠️ **U3 이후에만 워크트리에 적용된다** — 그 전 워크트리의 `tests/coding`은 merge-base 시점 사본이다 |
| `tests/coding/managed` (워크트리) | 76 passed / 2 skipped | **CA2 미커밋 변경 포함 상태**. E-D1로 채택하므로 이 값이 U1 이후의 기준선이 된다 |
| `tests/coding/managed/adapters` | 30 passed | Task 4 커밋 시점 17 → CA2가 +13 |

---

## 7. 이 작업이 출하 기준에 미치는 영향

| 기준 | 현재 | 이 계획 이후 |
|---|---|---|
| **E-S1** 플랜 14가 dev에 병합돼 있다 | ❌ | ❌ **여전히 아니다** — U3는 dev→워크트리 방향이다. 반대 방향 머지는 Task 5–10 완료 후 (CA1) |
| **E-S2** 실 루프가 정책 검증을 통과한다 | ❌ | ❌ 두 플래그 모두 `False` 유지 (범위 밖) |
| **E-S3** fail-closed가 실제로 지켜진다 | ❌ | 🟡 **부분** — Task 5의 펜스된 할당·모호한 결과 복구가 그 절반이다. 나머지는 Task 6–7 |
| **E-S4** 코딩 루프의 LLM 호출이 전부 원장에 남는다 | ✅ (가드 없음) | ✅ **가드 포함** — U4가 §1.5의 구멍을 메운다 |

인벤토리 기준: **CA2·CA4·CA5 종결**, CA3는 E-D2로 방식 확정(최종 머지 시점은 CA1에
종속), CA1은 6개 중 1개 소진(Task 5), CA6·CA7 미해결.

---

## 8. 위험과 대응

| 위험 | 대응 |
|---|---|
| U3 머지 후 `tests/coding` 457이 깨진다 | 머지 직전 `git merge-tree`로 재확인하고, 깨지면 dev 쪽 변경(role routing · D1c)과의 상호작용부터 본다. 워크트리 브랜치이므로 머지 커밋 되돌리기가 안전하다 |
| U5가 `docker.py`를 바꾸는데 데이터 플레인 회귀 | `docker.py`는 양쪽 0커밋이라 병합 위험은 없다. 회귀는 `tests/coding/sandbox` 스위트가 잡는다. 라벨 미지정 시 argv가 종전과 **바이트 단위로 동일**해야 한다는 것을 테스트로 고정한다 |
| CA2 채택이 잘못된 판정이었을 경우 | 별도 커밋이므로 `git revert` 한 번으로 되돌아간다. 원장(U2)에 판정 근거 넷을 남겨 재판정이 가능하게 한다 |
| 트랙 A 라이브 표본과의 간섭 | §12.4가 트랙 E를 §10.2 예외로 둔다. U1–U6은 전부 워크트리 안에서 일어나고 dev를 건드리지 않으므로 표본 #14와 병행 가능하다 |

---

## 9. 완료의 정의

1. 워크트리 `git status --short`가 비어 있다
2. `progress.md`에 Task 4·CA2 판정·CA5-a/b 처리가 기록돼 있고 계보가 단일하다
3. 워크트리가 dev를 포함한다 (`git merge-base --is-ancestor dev HEAD`)
4. `_prepare_real_coding_loop`의 `TrackedCodingModel` 배선에 회귀 가드가 있다
5. `docker_shadow.py`에 `provider._` 접근이 0건이다
6. 플랜 Task 5의 Step 1–5가 완료되고 검증 커맨드가 통과한다
7. 로드맵 §12와 재개 문서에 §1의 정정 다섯 건이 반영돼 있다
