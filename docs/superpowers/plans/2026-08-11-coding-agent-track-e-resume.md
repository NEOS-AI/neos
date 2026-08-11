# 트랙 E 재개 — 언블록 + Managed Sandbox Task 5 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 트랙 E의 재개 차단 요인(CA2·CA3·CA4·CA5)을 해소하고 플랜 14의 Task 5(펜스된 할당·모호한 결과 복구·바인딩)를 구현한다.

**Architecture:** 워크트리 `feature/managed-sandbox-control-plane`에서 작업한다. 먼저 미커밋 변경을 CA5-b 구현으로 확정하고 원장을 정합시킨 뒤, `dev`를 워크트리로 머지해 D1c(`TrackedCodingModel`)가 배선된 최신 `runtime.py` 위에서 나머지를 쓴다. CA5-a는 Docker provider에 공개 라벨 확장점을 내어 shadow 어댑터가 provider를 변형하지 않게 만든다. 플랜 14 Task 5는 리뷰 단위로 셋(repository 펜싱 → 할당 서비스 → cipher·배선)으로 쪼갠다.

**Tech Stack:** Python 3.12+ · SQLAlchemy 2.0 async (raw `text()` SQL) · PostgreSQL 16 · pytest / pytest-asyncio · ruff · `cryptography` (AES-GCM)

**스펙:** [2026-08-11-coding-agent-track-e-resume-design.md](../specs/2026-08-11-coding-agent-track-e-resume-design.md)
**상위 플랜:** `docs/superpowers/plans/2026-07-25-managed-sandbox-control-plane.md` (Task 5는 `:553`)

## Global Constraints

- **작업 위치:** 모든 태스크는 `/Users/ywsung/Desktop/neos/.worktrees/managed-sandbox-control-plane`에서 실행한다. `dev` 워킹트리를 건드리지 않는다.
- **Python:** `/Users/ywsung/Desktop/neos/.venv/bin/python3` · `pytest` · `ruff` (워크트리에 별도 venv 없음)
- **테스트 환경변수:** `GOOGLE_API_KEY=test-key`를 붙여 실행한다.
- **커밋 메시지에 `Co-Authored-By` 트레일러를 넣지 않는다.** (사용자 지침 — 기본 하네스 지침보다 우선)
- **문서·주석은 한국어로 쓴다.** 코드 식별자는 영어.
- **매직넘버 금지** — 임계값·TTL·상한은 전부 `neos/config/schema.py`의 설정으로 낸다.
- **원장은 append-only** — `progress.md`의 기존 줄을 수정·삭제하지 않고 덧붙이기만 한다.
- **`managed.enabled=false`에서 기존 Memory/Docker 동작이 바이트 단위로 불변**이어야 한다.
- **fail-closed** — 자동 크로스 프로바이더 failover를 만들지 않는다. 기존 태스크는 동일 provider에서만 재접속한다.
- **평문 `provider_ref`를 저장하거나 로깅하지 않는다.**
- **테스트는 `no_db` 마킹**, 외부 네트워크·실제 Docker 데몬을 쓰지 않는다 (Task 4가 세운 관례).
- **두 제품 플래그는 계속 `False`로 둔다** — `sandbox.enabled` · `coding_model.enabled`. 이 계획은 활성화를 포함하지 않는다.

## 태스크 ↔ 스펙 단위 대응

| 플랜 태스크 | 스펙 단위 | 원장(`progress.md`) 기록 |
|---|---|---|
| Task 1 | U1 | `Task 4: CA2 채택` |
| Task 2 | U2 | 정정 블록 |
| Task 3 | U3 | `merge dev` |
| Task 4 | U4 | — |
| Task 5–6 | U5 | `CA5-a: 해소` |
| Task 7–9 | U6 (플랜14 Task 5) | `Task 5: complete` (Task 9에서 한 번) |
| Task 10 | 스펙 §9-7 | — |

---

### Task 1: CA2 소유권 확정 — CA5-b를 커밋한다

**Files:**
- Commit (수정 없음): `neos/coding/managed/adapters/docker_shadow.py`
- Commit (수정 없음): `tests/coding/managed/adapters/test_docker_shadow.py`

**Interfaces:**
- Consumes: 없음 (워크트리의 기존 미커밋 변경)
- Produces: 깨끗한 워킹트리. 이후 모든 태스크가 이를 전제한다.

> **판정 근거 (스펙 §1.1).** 이 diff는 Docker 볼륨을 클레임 락으로 쓰는 크로스 프로세스 원자적 create이며, CA5의 둘째 우려를 푼다. Task 4 커밋 `89196755`(18:09:13) 12분 뒤 mtime(18:21)이라 동일 세션 산물이고, 테스트 30개가 통과한다. **지우지 않고 채택한다.**

- [ ] **Step 1: 워킹트리 상태가 예상과 같은지 확인**

```bash
cd /Users/ywsung/Desktop/neos/.worktrees/managed-sandbox-control-plane
git status --short
git diff --stat
```

Expected:
```
 M neos/coding/managed/adapters/docker_shadow.py
 M tests/coding/managed/adapters/test_docker_shadow.py
 2 files changed, 478 insertions(+), 33 deletions(-)
```

두 파일 외의 것이 나오면 **멈추고 보고한다.** 이 계획은 정확히 이 두 파일을 전제한다.

- [ ] **Step 2: 변경이 CA5-b인지 코드로 확인**

```bash
git diff neos/coding/managed/adapters/docker_shadow.py | grep -E "^\+.*(def |CLAIM)"
```

Expected: `_claim_volume_name`, `_ownership_volume_name`, `_wait_for_claim_owner`,
`_verify_resource_metadata`, `_resource_labels`, `_label_args`가 보인다.
보이지 않으면 판정 근거가 무너진 것이므로 **멈추고 보고한다.**

- [ ] **Step 3: 테스트가 통과하는지 확인**

```bash
GOOGLE_API_KEY=test-key /Users/ywsung/Desktop/neos/.venv/bin/pytest -q \
  tests/coding/managed
```

Expected: `76 passed, 2 skipped`

- [ ] **Step 4: 린트 통과 확인**

```bash
/Users/ywsung/Desktop/neos/.venv/bin/ruff check neos/coding/managed tests/coding/managed
/Users/ywsung/Desktop/neos/.venv/bin/ruff format --check neos/coding/managed tests/coding/managed
```

Expected: 둘 다 통과. 실패하면 포맷만 고치고 다시 실행한다.

- [ ] **Step 5: 커밋**

```bash
git add neos/coding/managed/adapters/docker_shadow.py \
  tests/coding/managed/adapters/test_docker_shadow.py
git commit -m "feat(coding): claim docker resources across processes

Task 4가 남긴 우려 중 크로스 프로세스 원자적 create(CA5-b)를 해소한다.
Docker 볼륨을 클레임 락으로 써서 단일 어댑터 프로세스 밖에서도 create 멱등성이
유지되게 하고, 리소스 메타데이터를 검증한 뒤에만 inspect·destroy 한다.

2026-07-25 Task 4 커밋 직후 작성됐으나 리뷰·커밋되지 않은 채 남아 있던 변경이며,
2026-08-11 소유권 판정으로 채택했다."
git status --short
```

Expected: `git status --short` 출력이 비어 있다.

---

### Task 2: CA4 원장 정합 — 덧붙여 정정한다

**Files:**
- Modify (**로컬 전용, 커밋하지 않음**): `.superpowers/sdd/2026-07-25-managed-sandbox-control-plane/progress.md` (끝에 덧붙이기)
- Modify (**커밋 대상**): `docs/coding_agent_task_resume.md` §4「원장 무결성 문제」

**Interfaces:**
- Consumes: Task 1의 커밋 해시
- Produces: 정정된 계보와 Task 4 항목. Task 9가 로컬 원장에 `Task 5: complete`를 덧붙인다.

> **기존 24줄을 수정·삭제하지 않는다.** 이중 기록된 두 블록을 그대로 두고 아래에 정정 블록을 덧붙인다. 원장을 재작성하면 스펙 §1.4가 지적한 문제(원장이 자기 이력을 잃는 것)를 한 번 더 저지르게 된다.
>
> 🔴 **`.superpowers/`는 `.gitignore:42`로 무시된다 (PF1 판정, 2026-08-11).** 그래서 원장
> 파일 자체는 **커밋하지 않는다** — `git add`가 조용히 아무것도 스테이징하지 않는다.
> 대신 **정정 내용을 `docs/coding_agent_task_resume.md`에 옮겨 담아 커밋한다.** 그 문서가
> CA4의 영속 기록이다. 원장 파일은 구현자의 작업 연속성을 위한 로컬 사본으로만 남는다.

- [ ] **Step 1: Task 1의 커밋 해시를 확보**

```bash
cd /Users/ywsung/Desktop/neos/.worktrees/managed-sandbox-control-plane
git log --oneline -1
```

아래 Step 2의 `<CA2_COMMIT>`을 이 해시로 바꿔 쓴다.

- [ ] **Step 2: 정정 블록을 파일 끝에 덧붙인다**

`.superpowers/sdd/2026-07-25-managed-sandbox-control-plane/progress.md` 끝에 추가:

```markdown

--- 정정 (2026-08-11) — 위 두 블록은 보존한다 ---

Ledger integrity: 위 17번째 줄 이후의 둘째 블록은 첫째 블록과 같은 태스크를 다른
커밋 해시로 다시 적은 중복 기록이다. 실제 계보는 git 이력으로 확정했다:
591640ce -> 29ab632d -> 777fdd33 -> 79645f2e -> 8b6ef183 -> d8f4e2e4 -> d308443e
-> 9245d5d5 -> 2d38f1a6 -> 3e3935f1 -> 89196755. 첫째 블록의 해시가 이 계보와
일치하므로 첫째 블록을 실제로 본다.

Ledger integrity: 두 블록 모두 Task 3에서 끝나 Task 4 항목이 누락돼 있었다.
아래가 그 누락분이다.

Task 4: complete (commit 89196755, 2026-07-25) — capability 인식 어댑터 포트,
결정론적 fake, 공유 conformance 스위트, Docker shadow 어댑터. 프로덕션 팩토리
배선은 의도적으로 미변경.
Task 4: concern (CA5-a): Docker provider에 공개 관리형 라벨 확장점이 없어 shadow가
커맨드 러너를 감싸고 private 속성을 읽는다. -> 2026-08-11 계획의 Task 5-6에서 해소.
Task 4: concern (CA5-b): Docker 멱등성이 단일 어댑터 프로세스 안에서만 보호된다.
-> commit <CA2_COMMIT>에서 해소 (클레임 볼륨 락).
Task 4: CA2 소유권 판정 (2026-08-11) — docker_shadow.py(+305/-33)와
test_docker_shadow.py(+206)의 미커밋 변경을 CA5-b 구현으로 판정하고 채택했다.
근거: (1) 내용이 CA5-b와 일치, (2) Task 4 커밋 12분 뒤 mtime으로 동일 세션,
(3) tests/coding/managed/adapters 30 passed (Task 4 시점 17 -> +13),
(4) 신규 테스트가 클레임 경로를 직접 겨냥. 커밋 <CA2_COMMIT>.
```

- [ ] **Step 3: 기존 24줄이 그대로인지 확인**

`.superpowers/`는 gitignore이라 `git diff`가 보여주지 않는다. 줄 수로 확인한다:

```bash
head -24 .superpowers/sdd/2026-07-25-managed-sandbox-control-plane/progress.md | md5
```

Expected: `1d0dd1a5b0dd3d0b1f79f1b5e2a4f6c8` — 값이 다르면 앞 24줄을 건드린 것이므로
되돌리고 덧붙이기만 다시 한다. (구현자는 편집 **전에** 이 명령을 한 번 돌려 기준값을
먼저 기록하고, 편집 후 같은지 비교하면 된다. 위 해시는 예시가 아니라 **직접 잰 값을
쓴다** — 편집 전 출력을 그대로 옮겨 적을 것.)

- [ ] **Step 4: 정정 내용을 추적되는 문서로 옮긴다**

`docs/coding_agent_task_resume.md`의 §4「원장 무결성 문제」를 아래로 **교체**한다.
이것이 CA4의 영속 기록이다 — 원장 파일은 gitignore이라 커밋되지 않는다.

```markdown
### 원장 무결성 문제 — 정정 완료 (2026-08-11)

`progress.md`는 **이중 기록 + Task 4 누락** 두 문제를 함께 갖고 있었다.

1. **이중 기록.** 17번째 줄 빈 줄 이후 Task 1–3이 다른 커밋 해시로 다시 나온다.
   git 이력으로 확정한 실제 계보는
   `591640ce → 29ab632d → 777fdd33 → 79645f2e → 8b6ef183 → d8f4e2e4 → d308443e →
   9245d5d5 → 2d38f1a6 → 3e3935f1 → 89196755`이며, **첫째 블록**의 해시가 이와
   일치하므로 첫째 블록이 실제다.
2. **Task 4 누락.** 두 블록 모두 Task 3에서 끝나 Task 4 항목이 아예 없었다.
   즉 로드맵 §12.2의 "Task 4 ✅"는 **원장 근거 없이** 커밋 존재에만 기대고 있었다.

**CA2 소유권 판정 (해소).** `docker_shadow.py`(+305/−33)·`test_docker_shadow.py`(+206)의
미커밋 변경을 **CA5-b(크로스 프로세스 원자적 create) 구현으로 판정하고 채택**했다.
근거 넷: (1) 내용이 CA5-b와 일치(클레임 볼륨 락), (2) Task 4 커밋 12분 뒤 mtime으로
동일 세션, (3) `tests/coding/managed/adapters` 30 passed(Task 4 시점 17 → +13),
(4) 신규 테스트가 클레임 경로를 직접 겨냥.

> ⚠️ **원장 파일은 git에 없다.** `.superpowers/`가 `.gitignore:42`로 무시되므로
> `progress.md`는 워크트리 로컬 사본일 뿐이고 `git clean -fdx`로 사라진다.
> **이 절이 그 원장의 영속 기록이다.**
```

- [ ] **Step 5: 커밋**

```bash
git add docs/coding_agent_task_resume.md
git commit -m "docs(coding): reconcile the managed sandbox ledger

원장은 이중 기록 + Task 4 누락 두 문제를 함께 갖고 있었다. git 이력으로 실제 계보를
확정하고 CA2 소유권 판정을 기록한다.

.superpowers/ 가 gitignore 이므로 원장 파일 자체는 커밋되지 않는다 -- 이 문서가
그 원장의 영속 기록이다."
```

---

### Task 3: dev 합류 — 워크트리로 머지한다

**Files:**
- Modify: 머지 결과 전체 (수동 편집 없음)

**Interfaces:**
- Consumes: Task 1·2의 커밋
- Produces: `neos/dataset/adapters.py`(`TrackedCodingModel`) · 역할 라우팅이 적용된 `neos/coding/runtime.py` · dev의 `tests/coding` 전체. **Task 4는 이것 없이는 물리적으로 작성 불가하다** — 워크트리에 `neos/dataset/adapters.py`가 존재하지 않는다.

> **리베이스가 아니라 머지다.** 리베이스는 11커밋 해시를 재작성하는데 Task 2가 방금 그 해시로 계보를 기록했다.

- [ ] **Step 1: 충돌면을 비파괴로 재확인**

```bash
cd /Users/ywsung/Desktop/neos
git merge-tree --write-tree --name-only dev feature/managed-sandbox-control-plane
echo "exit=$?"
```

Expected: `exit=0`이고 출력이 트리 OID 한 줄뿐이다.
파일 목록이 나오면 그것이 충돌 파일이므로 **멈추고 보고한다** (2026-08-11 실측은 충돌 0건이었다).

- [ ] **Step 2: 머지 전 기준선 기록**

```bash
cd /Users/ywsung/Desktop/neos/.worktrees/managed-sandbox-control-plane
GOOGLE_API_KEY=test-key /Users/ywsung/Desktop/neos/.venv/bin/pytest -q tests/coding/managed
```

Expected: `76 passed, 2 skipped`

- [ ] **Step 3: 머지**

```bash
git merge dev -m "merge: bring dev into the managed sandbox branch

Task 5가 neos/coding/runtime.py를 수정하는데 dev가 그 파일을 D1c(TrackedCodingModel)와
역할 라우팅으로 이미 바꿨다. 낡은 사본 위에 어댑터 레지스트리를 얹지 않기 위해
Task 5 착수 전에 합류한다. 충돌면은 git merge-tree로 사전 측정했고 0건이었다."
```

Expected: 충돌 없이 머지 커밋 생성.
충돌이 나면 **되돌리고**(`git merge --abort`) 보고한다.

- [ ] **Step 4: dev의 파일이 도착했는지 확인**

```bash
ls -l neos/dataset/adapters.py
grep -c "TrackedCodingModel" neos/coding/runtime.py
```

Expected: 파일이 존재하고 grep 결과가 `2` 이상.

- [ ] **Step 5: 두 스위트 전부 통과 확인**

```bash
GOOGLE_API_KEY=test-key /Users/ywsung/Desktop/neos/.venv/bin/pytest -q tests/coding
```

Expected: `457 passed` 이상 · `0 failed` (managed 76건이 더해져 총계는 533 근처가 된다).
실패가 나면 dev 쪽 변경(역할 라우팅·D1c)과의 상호작용부터 본다. 되돌리려면
`git reset --hard HEAD~1`.

- [ ] **Step 6: 린트**

```bash
/Users/ywsung/Desktop/neos/.venv/bin/ruff check neos/coding tests/coding
```

Expected: 통과.

---

### Task 4: E-S4 회귀 가드 — 배선이 풀리면 빨개진다

**Files:**
- Modify: `tests/coding/sandbox/test_runtime_ownership.py`

**Interfaces:**
- Consumes: `runtime_module._prepare_real_coding_loop(config=...)` → `finish(sandboxes)` → `AnthropicCodingLoop`. 루프는 모델을 `loop._model`에 둔다. `TrackedCodingModel`은 `_inner`·`_workflow_step`을 갖는다.
- Produces: Task 9가 `runtime.py`를 편집할 때 D1c 배선을 지키는 가드.

> **왜 지금인가.** §12.6이 E-S4를 유일한 ✅로 적었는데 그 배선을 검증하는 테스트가 없다. `TrackedCodingModel`을 언급하는 테스트는 `tests/dataset/test_adapters.py`의 래퍼 단위 테스트뿐이다. Task 9가 정확히 그 함수를 편집하므로 **먼저** 잠근다.

- [ ] **Step 1: 가드 테스트를 쓴다**

`tests/coding/sandbox/test_runtime_ownership.py`의 import 절에 추가:

```python
from neos.coding.model.anthropic import AnthropicCodingModel
from neos.dataset.adapters import TrackedCodingModel
```

파일 끝에 추가:

```python
def test_real_loop_wraps_the_production_model_for_collection(monkeypatch) -> None:
    """E-S4 회귀 가드.

    이 단언이 깨지면 코딩 루프의 LLM 호출이 데이터셋 원장에서 조용히 샌다.
    D1c(`7f4beca1`)가 계측을 전송 계층 **밖에서** 감싼 이유가 여기 있다 --
    래퍼가 벗겨져도 루프는 정상 동작하므로 테스트 없이는 아무도 모른다.
    """
    config = AppConfig.model_validate({
        "coding_model": {
            "enabled": True,
            "input_cost_micros_per_million": 1,
            "output_cost_micros_per_million": 1,
        },
        "sandbox": {"enabled": True},
        "secrets": {"anthropic_api_key": "test"},
    })
    monkeypatch.setattr(runtime_module, "AsyncAnthropic", lambda **kwargs: object())

    finish = runtime_module._prepare_real_coding_loop(config=config)
    loop = finish(object())

    assert isinstance(loop._model, TrackedCodingModel)
    assert isinstance(loop._model._inner, AnthropicCodingModel)
    assert loop._model._workflow_step == "coding_loop"
```

- [ ] **Step 2: 통과하는지 확인 (기존 동작을 고정하는 테스트다)**

```bash
GOOGLE_API_KEY=test-key /Users/ywsung/Desktop/neos/.venv/bin/pytest -q \
  tests/coding/sandbox/test_runtime_ownership.py::test_real_loop_wraps_the_production_model_for_collection
```

Expected: PASS. 이 테스트는 기존 배선을 기술하는 characterization test이므로 처음부터 통과한다.

- [ ] **Step 3: 테스트가 실제로 실패할 수 있는지 검증한다**

통과만 확인하면 아무것도 단언하지 않는 테스트와 구별되지 않는다. **일시적으로** `neos/coding/runtime.py`의 배선을 풀어 빨개지는지 본다:

```python
    # 임시: TrackedCodingModel 래핑을 벗긴다 (되돌릴 것)
    model = AnthropicCodingModel(
        AsyncAnthropic(api_key=config.secrets.anthropic_api_key)
    )
```

```bash
GOOGLE_API_KEY=test-key /Users/ywsung/Desktop/neos/.venv/bin/pytest -q \
  tests/coding/sandbox/test_runtime_ownership.py::test_real_loop_wraps_the_production_model_for_collection
```

Expected: FAIL — `assert isinstance(loop._model, TrackedCodingModel)`

- [ ] **Step 4: 되돌리고 다시 초록인지 확인**

```bash
git checkout neos/coding/runtime.py
GOOGLE_API_KEY=test-key /Users/ywsung/Desktop/neos/.venv/bin/pytest -q \
  tests/coding/sandbox/test_runtime_ownership.py
git diff --stat neos/coding/runtime.py
```

Expected: 전부 PASS이고 `runtime.py`에 변경이 남아 있지 않다.

- [ ] **Step 5: 커밋**

```bash
git add tests/coding/sandbox/test_runtime_ownership.py
git commit -m "test(coding): guard the production model instrumentation

E-S4는 TrackedCodingModel 배선을 측정법으로 삼는데 그 배선을 검증하는 테스트가
없었다. 래퍼가 벗겨져도 루프는 정상 동작하므로 회귀가 조용히 지나간다."
```

---

### Task 5: CA5-a (1/2) — `build_create_args`가 라벨을 받는다

**Files:**
- Modify: `neos/coding/sandbox/command.py:155` (`build_create_args`)
- Modify: `neos/coding/sandbox/docker.py:326-345` (`DockerSandboxProvider.create`)
- Test: `tests/coding/sandbox/test_docker_command.py`

**Interfaces:**
- Consumes: 기존 `build_create_args(*, sandbox_id, image, limits, network_mode, allow_unpinned_image, tmpfs_bytes) -> tuple[str, ...]`
- Produces: `build_create_args(..., extra_labels: Mapping[str, str] | None = None) -> tuple[str, ...]`. Task 6이 이 파라미터로 관리형 라벨을 흘린다.

> **여기서 없애는 것.** `docker.py:339`가 `create_args.index("--user")`로 argv에 위치 기반 수술을 한다. `--user`가 argv에서 빠지는 순간 프로덕션 경로가 `ValueError`로 죽는다. shadow 어댑터(`docker_shadow.py:70`)는 이 패턴을 복사한 것이므로, 뿌리부터 없앤다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/coding/sandbox/test_docker_command.py` 끝에 추가 (파일 상단 import에 `build_create_args`·`SandboxLimits`가 이미 있으면 재추가하지 않는다):

```python
_SB = "sb_" + "a" * 32
_IMAGE = "neos-sandbox@sha256:" + "a" * 64


def _create_args(**kwargs):
    return build_create_args(
        sandbox_id=_SB,
        image=_IMAGE,
        limits=SandboxLimits.safe_defaults(),
        **kwargs,
    )


def test_build_create_args_emits_extra_labels() -> None:
    args = _create_args(extra_labels={"com.neos.coding.owner-id": "owner_1"})

    index = args.index("com.neos.coding.owner-id=owner_1")
    assert args[index - 1] == "--label"


def test_build_create_args_is_byte_identical_without_extra_labels() -> None:
    """관리형 라벨이 없을 때 argv가 종전과 완전히 같아야 한다.

    이 단언이 CA5-a 작업이 데이터 플레인을 건드리지 않았다는 증거다.
    """
    assert _create_args(extra_labels=None) == _create_args()
    assert _create_args(extra_labels={}) == _create_args()


def test_build_create_args_rejects_label_injection() -> None:
    with pytest.raises(SandboxPolicyViolation, match="docker_label_invalid"):
        _create_args(extra_labels={"com.neos.coding.owner-id": "a\nb"})
```

- [ ] **Step 2: 실패를 확인한다**

```bash
GOOGLE_API_KEY=test-key /Users/ywsung/Desktop/neos/.venv/bin/pytest -q \
  tests/coding/sandbox/test_docker_command.py -k extra_labels
```

Expected: FAIL — `TypeError: build_create_args() got an unexpected keyword argument 'extra_labels'`

- [ ] **Step 3: `build_create_args`에 파라미터를 넣는다**

`neos/coding/sandbox/command.py`:

```python
_LABEL_VALUE_FORBIDDEN = ("\n", "\r", "\x00")


def _label_args(labels: Mapping[str, str] | None) -> tuple[str, ...]:
    if not labels:
        return ()
    rendered: list[str] = []
    for key, value in labels.items():
        text = f"{key}={value}"
        if any(bad in text for bad in _LABEL_VALUE_FORBIDDEN):
            raise SandboxPolicyViolation("docker_label_invalid")
        rendered.extend(("--label", text))
    return tuple(rendered)
```

시그니처에 `extra_labels: Mapping[str, str] | None = None`을 추가하고,
반환 튜플의 `f"com.neos.coding.sandbox-id={sandbox_id}",` 바로 다음, `"--user",` 앞에
`*_label_args(extra_labels),`를 끼운다.

`from collections.abc import Mapping`을 import에 추가한다.

- [ ] **Step 4: 통과를 확인한다**

```bash
GOOGLE_API_KEY=test-key /Users/ywsung/Desktop/neos/.venv/bin/pytest -q \
  tests/coding/sandbox/test_docker_command.py
```

Expected: 전부 PASS

- [ ] **Step 5: provider가 위치 수술 대신 파라미터를 쓰게 바꾼다**

`neos/coding/sandbox/docker.py`의 `create()`에서 아래를 **삭제**한다:

```python
            metadata_labels = (
                f"com.neos.coding.owner-id={owner_id}",
                f"com.neos.coding.created-at={now.isoformat()}",
                "com.neos.coding.workspace-revision=0",
            )
            insertion = create_args.index("--user")
            for label in reversed(metadata_labels):
                create_args[insertion:insertion] = ["--label", label]
```

그리고 `build_create_args(...)` 호출에 인자를 넘긴다:

```python
            create_args = list(build_create_args(
                sandbox_id=sandbox_id,
                image=self._config.image,
                limits=limits,
                network_mode=self._config.network_mode,
                allow_unpinned_image=self._config.allow_unpinned_image,
                tmpfs_bytes=self._config.tmpfs_bytes,
                extra_labels={
                    "com.neos.coding.owner-id": owner_id,
                    "com.neos.coding.created-at": now.isoformat(),
                    "com.neos.coding.workspace-revision": "0",
                },
            ))
```

- [ ] **Step 6: 데이터 플레인 회귀가 없는지 확인한다**

```bash
GOOGLE_API_KEY=test-key /Users/ywsung/Desktop/neos/.venv/bin/pytest -q tests/coding/sandbox
grep -c 'index("--user")' neos/coding/sandbox/docker.py
```

Expected: 전부 PASS이고 grep 결과가 `0`.

- [ ] **Step 7: 커밋**

```bash
/Users/ywsung/Desktop/neos/.venv/bin/ruff check neos/coding/sandbox tests/coding/sandbox
git add neos/coding/sandbox/command.py neos/coding/sandbox/docker.py \
  tests/coding/sandbox/test_docker_command.py
git commit -m "refactor(coding): let docker argv carry labels by contract

create_args.index(\"--user\")로 argv에 위치 수술을 하던 것을 build_create_args의
extra_labels 파라미터로 바꾼다. --user가 argv에서 빠지면 ValueError로 죽던 결합을
없애고, 관리형 어댑터가 라벨을 얹을 공식 경로를 연다."
```

---

### Task 6: CA5-a (2/2) — provider가 라벨을 소유하고 shadow가 손을 뗀다

**Files:**
- Modify: `neos/coding/sandbox/docker.py` (`DockerSandboxProvider`)
- Modify: `neos/coding/managed/adapters/docker_shadow.py`
- Test: `tests/coding/managed/adapters/test_docker_shadow.py`

**Interfaces:**
- Consumes: Task 5의 `build_create_args(..., extra_labels=...)`
- Produces:
  - `DockerSandboxProvider.resource_labels(labels: Mapping[str, str])` — 컨텍스트 매니저. 블록 안에서 이 provider가 만드는 컨테이너·볼륨에 라벨이 붙는다.
  - `DockerSandboxProvider.command_runner -> DockerCommandRunner` — read-only property.
  - `DockerSandboxProvider.network_mode -> str` · `DockerSandboxProvider.image_identity -> str` — read-only property.
  - `DockerShadowManagedAdapter(*, provider, runner=None)` — 러너를 명시적으로 주입받는다.

> **없애는 것 셋.** ① `provider._runner = self._runner`(소유하지 않은 객체를 제자리에서 변형) ② `values.index("--user")`(위치 수술) ③ `provider._config` 읽기.
>
> ⚠️ **러너 접근 자체는 없애지 않는다.** `self._runner`는 12곳에서 쓰이는데 라벨 주입은
> 그중 하나(`docker_shadow.py:155`)뿐이다. 나머지는 shadow가 **자기 리소스**를 다루는
> 직접 docker CLI 호출이다 — 클레임 볼륨 생성(`:139`), `volume ls`(`:275`),
> `inspect`(`:289`·`:379`·`:402`), `rm`(`:420`·`:433`). shadow는 docker 클라이언트를
> 정당하게 필요로 한다.
>
> **따라서 고치는 것은 "의존을 없애기"가 아니라 "훔쳐서 변형하던 것을 명시적·공개
> 의존으로 바꾸기"다.** 공개 property를 읽는 것과 `provider._runner`에 대입하는 것은
> 같은 결함이 아니다 — 후자만 provider를 영구히 변형한다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/coding/managed/adapters/test_docker_shadow.py` 끝에 추가:

```python
from pathlib import Path

from neos.coding.managed.adapters import docker_shadow as docker_shadow_module


def test_docker_shadow_uses_only_the_public_provider_surface() -> None:
    """CA5-a 완료 기준.

    shadow가 provider의 private 속성을 읽거나 러너를 갈아끼우면, 관리형 어댑터가
    데이터 플레인 객체를 영구히 변형하는 구조가 된다.
    """
    source = Path(docker_shadow_module.__file__).read_text(encoding="utf-8")

    assert "provider._" not in source
    assert "_ManagedLabelRunner" not in source


async def test_resource_labels_reach_both_the_volume_and_the_container() -> None:
    _adapter, runner = docker_adapter()
    provider = DockerSandboxProvider(
        runner=runner,
        config=DockerSandboxConfig(image=IMAGE, network_mode="none"),
        clock=lambda: datetime(2026, 7, 25, 12, tzinfo=UTC),
    )

    with provider.resource_labels({ALLOCATION_ID_LABEL: "msa_1"}):
        await provider.create(
            owner_id="owner_1", limits=SandboxLimits.safe_defaults()
        )

    container_create = next(call for call in runner.calls if call[0] == "create")
    volume_create = next(
        call for call in runner.calls if call[:2] == ("volume", "create")
    )
    assert _labels_from_args(container_create)[ALLOCATION_ID_LABEL] == "msa_1"
    assert _labels_from_args(volume_create)[ALLOCATION_ID_LABEL] == "msa_1"


async def test_resource_labels_do_not_leak_outside_the_block() -> None:
    _adapter, runner = docker_adapter()
    provider = DockerSandboxProvider(
        runner=runner,
        config=DockerSandboxConfig(image=IMAGE, network_mode="none"),
        clock=lambda: datetime(2026, 7, 25, 12, tzinfo=UTC),
    )

    with provider.resource_labels({ALLOCATION_ID_LABEL: "msa_1"}):
        pass
    await provider.create(owner_id="owner_1", limits=SandboxLimits.safe_defaults())

    container_create = next(call for call in runner.calls if call[0] == "create")
    assert ALLOCATION_ID_LABEL not in _labels_from_args(container_create)
```

이 파일의 기존 헬퍼를 쓴다 — `docker_adapter()`(`:155`)가 `(adapter, EmulatedDockerRunner)`를
돌려주고, `_labels_from_args()`(`:147`)가 argv에서 라벨 dict를 뽑고, `runner.calls`가
호출 argv 튜플의 리스트다. **새 헬퍼를 만들지 않는다.**

- [ ] **Step 2: 실패를 확인한다**

```bash
GOOGLE_API_KEY=test-key /Users/ywsung/Desktop/neos/.venv/bin/pytest -q \
  tests/coding/managed/adapters/test_docker_shadow.py -k "public_provider_surface or resource_labels"
```

Expected: FAIL — `provider._`가 소스에 있고 `resource_labels` 속성이 없다.

- [ ] **Step 3: provider에 공개 확장점을 낸다**

`neos/coding/sandbox/docker.py` 모듈 상단에 추가:

```python
from collections.abc import Mapping
from contextlib import contextmanager
from contextvars import ContextVar

# 관리형 컨트롤 플레인이 이 provider가 만드는 리소스에 라벨을 얹는 공개 경로.
# ContextVar 이므로 같은 프로세스의 동시 create 가 서로 오염되지 않는다.
_MANAGED_LABELS: ContextVar[Mapping[str, str]] = ContextVar(
    "neos_docker_managed_labels", default={}
)
```

`DockerSandboxProvider`에 추가:

```python
    @contextmanager
    def resource_labels(self, labels: Mapping[str, str]):
        """블록 안에서 만들어지는 컨테이너·볼륨에 `labels` 를 붙인다."""
        token = _MANAGED_LABELS.set(dict(labels))
        try:
            yield
        finally:
            _MANAGED_LABELS.reset(token)

    @property
    def command_runner(self) -> DockerCommandRunner:
        """관리형 어댑터가 자기 리소스를 다룰 docker 클라이언트.

        읽기 전용이다 -- 이 러너를 **교체**하는 것이 CA5-a 가 없애려는 결함이었다.
        """
        return self._runner

    @property
    def network_mode(self) -> str:
        return self._config.network_mode

    @property
    def image_identity(self) -> str:
        return self._config.image
```

`create()`에서 볼륨 생성과 컨테이너 생성 양쪽에 흘린다:

```python
            managed_labels = _MANAGED_LABELS.get()
            await self._runner.run(
                "volume",
                "create",
                "--label",
                "com.neos.coding.sandbox=true",
                "--label",
                f"com.neos.coding.sandbox-id={sandbox_id}",
                *_label_args(managed_labels),
                volume_name,
                timeout_sec=self._config.create_timeout_sec,
            )
```

그리고 컨테이너 쪽 `extra_labels`를 병합한다:

```python
                extra_labels={
                    "com.neos.coding.owner-id": owner_id,
                    "com.neos.coding.created-at": now.isoformat(),
                    "com.neos.coding.workspace-revision": "0",
                    **managed_labels,
                },
```

`_label_args`는 Task 5에서 `command.py`에 만든 것을 import 한다.

- [ ] **Step 4: shadow가 공개 표면만 쓰게 고친다**

`neos/coding/managed/adapters/docker_shadow.py`:

1. `_ManagedLabelRunner` 클래스와 그 `ContextVar`를 **삭제**한다.
2. `__init__`의 러너 탈취·대입을 명시적 주입으로 바꾼다. **`self._runner`는 남긴다** —
   나머지 11곳이 이 러너로 자기 리소스를 다룬다:

```python
    def __init__(
        self,
        *,
        provider: DockerSandboxProvider,
        runner: DockerCommandRunner | None = None,
    ) -> None:
        self._provider = provider
        self._allocation_lock = asyncio.Lock()
        # provider 의 러너를 **교체**하지 않고 공개 표면으로 빌려 쓴다.
        self._runner = runner or provider.command_runner
```

즉 아래 세 줄을 **삭제**한다:

```python
        original_runner = provider._runner
        self._runner = (... _ManagedLabelRunner(original_runner))
        provider._runner = self._runner
```

3. capability 계산을 공개 property로 바꾼다:
   `network_block_all=provider.network_mode == "none",`
4. `allocate()`의 image 비교를 바꾼다:
   `if request.image_identity != self._provider.image_identity:`
5. 라벨을 붙이던 자리(`:155`의 `with self._runner.binding(labels):`)를 provider의
   컨텍스트 매니저로 바꾼다:

```python
        with self._provider.resource_labels(labels):
            created = await self._provider.create(
                owner_id=request.owner_id,
                limits=request.resource_limits,
            )
```

6. **나머지 `self._runner.run(...)` 호출 11곳은 그대로 둔다** — 클레임 볼륨 생성,
   `volume ls`, `inspect`, `rm`은 shadow 자신의 리소스를 다루는 정당한 docker CLI
   호출이다.

- [ ] **Step 5: 여기까지 통과를 확인한다**

```bash
GOOGLE_API_KEY=test-key /Users/ywsung/Desktop/neos/.venv/bin/pytest -q \
  tests/coding/managed tests/coding/sandbox
grep -c "provider\._" neos/coding/managed/adapters/docker_shadow.py
```

Expected: 전부 PASS이고 grep 결과가 `0`.

> 🔴 **아래 Step 6–9는 Task 1 리뷰가 찾은 결함의 이월분이다 (2026-08-11 판정).**
> Task 1이 채택한 CA5-b 코드는 **획득의 원자성**은 풀었지만 **해제의 보장**을 빠뜨렸다.
> 분산 락에서 이 둘은 쌍으로 온다 — 전자만 있으면 fail-closed가 **fail-forever**가 된다.
> Task 1은 소유권 판정 커밋으로 깨끗이 남기고, 기능 수정은 이 태스크가 맡는다.

- [ ] **Step 6: 클레임 누수 테스트를 쓴다 (실패 확인)**

`tests/coding/managed/adapters/test_docker_shadow.py`에 추가:

```python
async def test_a_failed_create_releases_the_claim() -> None:
    """클레임을 이긴 뒤 create 가 실패하면 클레임을 반납해야 한다.

    반납하지 않으면 그 idempotency_key 로 오는 모든 이후 allocate 가 나타나지 않을
    소유자를 기다리다 타임아웃한다 -- 운영자가 볼륨을 지울 때까지 키가 영구히 오염된다.
    """
    adapter, runner = docker_adapter()
    runner.fail_next("create", SandboxError("docker_create_failed"))

    with pytest.raises(SandboxError):
        await adapter.allocate(allocation_request())

    assert runner.volumes == {}

    # 키가 오염되지 않았다: 다음 시도가 정상적으로 성공한다.
    created = await adapter.allocate(allocation_request())
    assert created.state is ManagedSandboxState.ACTIVE


async def test_a_stale_claim_is_reclaimed_instead_of_blocking_forever() -> None:
    """소유자가 죽어 클레임만 남은 경우, 기다리다 포기하지 말고 회수해야 한다."""
    adapter, runner = docker_adapter()
    request = allocation_request()
    runner.seed_orphan_claim(
        adapter._claim_volume_name(request.idempotency_key),
        claimed_at=STALE_CLAIMED_AT,
    )

    created = await adapter.allocate(request)

    assert created.state is ManagedSandboxState.ACTIVE
```

`runner.fail_next(op, error)`와 `runner.seed_orphan_claim(name, *, claimed_at)`은
`EmulatedDockerRunner`(`:45`)에 함께 추가한다. `STALE_CLAIMED_AT`은
`claim_lease_seconds`보다 오래된 ISO 타임스탬프다.

```bash
GOOGLE_API_KEY=test-key /Users/ywsung/Desktop/neos/.venv/bin/pytest -q \
  tests/coding/managed/adapters/test_docker_shadow.py -k "releases_the_claim or stale_claim"
```

Expected: FAIL — 현재는 클레임이 남고 두 번째 `allocate`가 타임아웃한다.

- [ ] **Step 7: 실패 시 클레임을 반납한다**

`allocate()`에서 클레임을 이긴 뒤의 구간을 `try`로 감싸고, **`provider.create()`가
실패하면 클레임 볼륨을 지운 뒤 예외를 다시 올린다:**

```python
        try:
            with self._provider.resource_labels(labels):
                created = await self._provider.create(
                    owner_id=request.owner_id,
                    limits=request.resource_limits,
                )
        except BaseException:
            # 획득의 원자성만으로는 부족하다 -- 해제를 보장하지 않으면
            # fail-closed 가 fail-forever 가 된다.
            await self._remove_volume_if_present(claim_name)
            raise
```

`_remove_volume_if_present`는 CA5-b가 이미 만들어 둔 헬퍼다. `BaseException`으로
잡는 이유는 `CancelledError`에도 클레임을 남기지 않기 위해서다.

- [ ] **Step 8: 죽은 소유자의 클레임을 회수한다**

클레임 볼륨 생성 시 `CLAIMED_AT_LABEL`(`com.neos.coding.managed-claimed-at`)에
ISO 타임스탬프를 함께 싣는다. `_wait_for_claim_owner`가 데드라인에 도달하면 포기하기
전에 클레임을 다시 조회해서:

- 해당 idempotency_key로 컨테이너가 **없고**
- `claimed_at`이 `claim_lease_seconds`보다 오래됐으면

→ 그 클레임 볼륨을 지우고 **같은 호출 안에서 딱 한 번 재획득을 시도한다** (총 2회 시도).

> ⚠️ **정정 (2026-08-11).** 이 자리에 처음 적었던 *"같은 호출 안에서 재시도하지 않는다 —
> 한 호출이 락을 깨고 곧바로 잡으면 두 프로세스가 동시에 깨는 창이 생긴다"* 는 **틀렸고,
> Step 6의 테스트(`ACTIVE`를 단언)와도 모순이었다.** 근거: 이 프로토콜은 test-then-set이
> 아니라 **create-then-confirm-token**이다. `docker volume create`는 기존 볼륨에 no-op이라
> 나중에 온 쪽의 라벨이 덮이지 않으므로, 두 프로세스가 동시에 깨고 다시 만들어도 이어지는
> 토큰 비교가 승자를 **정확히 하나로** 좁힌다. 재획득 시점이 이번 호출이냐 다음 호출이냐는
> 이 성질을 바꾸지 않는다.
>
> **진짜 위험은 다른 곳에 있다 — 해제의 펜싱이다.** Step 8이 클레임을 재할당 가능하게
> 만드는 순간, "클레임을 만든 프로세스만 지운다"는 불변식이 깨진다. 아래 Step 8-b가 그것을
> 막는다. 이 정정이 없었다면 Step 8은 fail-forever를 **영구 오염**으로 바꿨을 것이다.

- [ ] **Step 8-b: 해제를 클레임 토큰으로 펜싱한다**

클레임 볼륨을 지우는 두 자리(실패 시 반납 · 성공 후 정리)가 **무조건** 지운다. 클레임이
재할당될 수 있게 된 이상 이건 **남의 락을 푸는 것**이 된다. 지우기 전에 `volume inspect`로
`CLAIM_TOKEN_LABEL`이 아직 **내 토큰**인지 확인하는 헬퍼를 만들어 두 자리 모두 그것을 쓴다:

```python
    async def _release_claim(self, claim_name: str, claim_token: str) -> None:
        """내 토큰이 아직 붙어 있을 때만 클레임을 푼다.

        Step 8 이 stale 클레임 회수를 도입한 순간 "만든 프로세스만 지운다"는 불변식이
        깨졌다. 펜싱하지 않으면 느린 소유자가 나중 소유자의 락을 풀고, 같은
        idempotency key 로 컨테이너가 둘 생겨 find_by_idempotency_key 가 영구히
        idempotency_metadata_not_unique 를 던진다.
        """
```

**미펜싱 해제가 만드는 연쇄 (리뷰 실측):** P0이 클레임 획득 → `create()`에서 리스 초과
지연 → P1이 stale 판정·삭제·재획득·`create()` → **같은 키의 컨테이너 2개** → P0이 끝나며
**P1의 클레임** 삭제 → 세 번째 프로세스 입장. 원래 버그(타임아웃)보다 나쁘다 —
`destroy()`도 `provider_ref`가 필요한데 조회 자체가 실패한다.

`neos/config/schema.py`의 `ManagedSandboxConfig`에 설정을 추가한다 (매직넘버 금지):

```python
    claim_lease_seconds: int = Field(
        default=300,
        gt=0,
        le=3600,
        description="클레임 볼륨의 수명. 이보다 오래되고 컨테이너가 없으면 회수한다.",
    )
```

- [ ] **Step 9: 통과를 확인한다**

```bash
GOOGLE_API_KEY=test-key /Users/ywsung/Desktop/neos/.venv/bin/pytest -q \
  tests/coding/managed tests/coding/sandbox tests/config
```

Expected: 전부 PASS

- [ ] **Step 10: 커밋**

```bash
/Users/ywsung/Desktop/neos/.venv/bin/ruff check neos/coding tests/coding
git add neos/coding/sandbox/docker.py neos/coding/managed/adapters/docker_shadow.py \
  tests/coding/managed/adapters/test_docker_shadow.py
git commit -m "feat(coding): give docker a public managed label surface

CA5-a 해소. shadow 어댑터가 provider._runner 를 갈아끼우고 private config 를 읽던
것을 없앤다. provider 가 resource_labels() 컨텍스트 매니저로 라벨을 소유하므로
argv 지식이 argv 를 만드는 쪽에 남고, 관리형 어댑터는 공개 표면만 쓴다."
```

---

### Task 7: 플랜14 Task 5 (1/3) — 펜스된 claim/commit

**Files:**
- Create: `neos/coding/managed/allocation.py`
- Modify: `neos/coding/managed/repository.py`
- Modify: `tests/coding/managed/test_repository.py` (단위 — FakeSession)
- Create: `tests/coding/managed/integration/test_postgres_allocation.py` (통합 — 실제 Postgres)

**Interfaces:**
- Consumes: 마이그레이션 045의 `coding_managed_sandboxes` (`fencing_token BIGINT NOT NULL CHECK (> 0)`, `lease_expires_at TIMESTAMPTZ`, `version BIGINT`, `generation INTEGER`, `provider_ref BYTEA`, `ownership_digest VARCHAR(128)`)
- Produces:
  - `ManagedAllocationLease(allocation_id: str, worker_id: str, fencing_token: int, expires_at: datetime)` — frozen dataclass, `neos/coding/managed/allocation.py`
  - `StaleManagedSandboxLease(RuntimeError)`
  - `PostgresManagedSandboxRepository.claim_allocation(allocation_id, worker_id, *, now, lease_seconds) -> ManagedAllocationLease`
  - `PostgresManagedSandboxRepository.commit_state(lease, target, *, now, error_code=None) -> ManagedSandboxAllocation`
  - `PostgresManagedSandboxRepository.commit_active(lease, result, *, encrypted_ref, now) -> ManagedSandboxAllocation`
  - `AllocationPlan(allocation, idempotency_key, image_identity, resource_limits, network_policy)` — frozen dataclass
  - `PostgresManagedSandboxRepository.read_allocation_plan(allocation_id) -> AllocationPlan`

> ⚠️ **`ManagedAllocationRequest`의 8필드가 한 테이블에 없다.** `allocation_id`·`region`·
> `ownership_digest`·`absolute_expires_at`은 `coding_managed_sandboxes`에 있지만
> `idempotency_key`·`resource_limits`·`network_policy`는 **`coding_sandbox_admissions`**에
> 있고, 도메인 `ManagedSandboxAllocation` dataclass는 그 셋도 `image_identity`도 담지
> 않는다. 그래서 Task 8이 어댑터 요청을 만들려면 **조인 뷰**가 필요하다 —
> `read_allocation_plan()`이 그것이다. 할당 dataclass를 부풀리지 않는다.

> **범위 결정 이행.** 원장 5번 줄: *"transition_allocation stays pure; version/fence checks are mandatory in Task 5 repository claim/commit."* 이 태스크가 그 약속의 만기일이다. `domain.transition_allocation()`은 **건드리지 않는다** — 순수 함수로 두고, 검사는 repository의 SQL WHERE 절에 둔다.
>
> **`worker_id`는 영속화하지 않는다.** 045에 `lease_owner` 컬럼이 없다. 소유권 증명은 `fencing_token`이 단독으로 한다(오래된 워커는 토큰이 낮아 commit이 0행). `worker_id`는 lease 객체와 로그·메트릭에만 남는 진단용이다. **마이그레이션 046을 만들지 않는다.**

> **이 저장소의 repository 테스트는 2층이다.** `test_repository.py`는 `FakeSession`으로
> **발행된 SQL 텍스트와 파라미터**를 단언하고(DB 없음), 실제 동시성 의미는
> `integration/`의 `@pytest.mark.integration` 테스트가 진짜 Postgres로 검증한다
> (`CODING_TEST_DATABASE_URL` 없으면 skip — 현재 `76 passed, 2 skipped`의 그 2건이다).
> **펜싱은 fake 세션으로 증명할 수 없으므로 두 층을 다 쓴다.**

- [ ] **Step 1: 단위 테스트를 쓴다 (발행된 SQL 검증)**

`tests/coding/managed/test_repository.py` 끝에 추가한다. 이 파일의 기존
`FakeSession`·`FakeResult`와 `repository(...)` 헬퍼(`:71`)를 재사용한다:

```python
async def test_claim_allocation_only_takes_a_free_or_expired_lease() -> None:
    session = FakeSession([FakeResult(row=_row(fencing_token=2))])
    repo = repository_with(session)

    lease = await repo.claim_allocation(
        "msa_1", "worker_1", now=NOW, lease_seconds=300
    )

    statement, params = session.statements[-1]
    assert "fencing_token = fencing_token + 1" in statement
    assert "lease_expires_at IS NULL" in statement
    assert "lease_expires_at <= :now" in statement
    assert params["allocation_id"] == "msa_1"
    assert lease.fencing_token == 2
    assert lease.worker_id == "worker_1"


async def test_claim_allocation_raises_when_a_live_lease_holds() -> None:
    session = FakeSession([FakeResult(row=None)])
    repo = repository_with(session)

    with pytest.raises(StaleManagedSandboxLease):
        await repo.claim_allocation("msa_1", "worker_2", now=NOW, lease_seconds=300)


async def test_commit_filters_on_the_fencing_token() -> None:
    session = FakeSession([FakeResult(row=_row(fencing_token=2))])
    repo = repository_with(session)
    lease = ManagedAllocationLease(
        allocation_id="msa_1",
        worker_id="worker_1",
        fencing_token=2,
        expires_at=NOW + timedelta(seconds=300),
    )

    await repo.commit_state(lease, ManagedSandboxState.ALLOCATING, now=NOW)

    statement, params = session.statements[-1]
    assert "fencing_token = :fencing_token" in statement
    assert params["fencing_token"] == 2


async def test_commit_active_binds_only_the_encrypted_reference() -> None:
    session = FakeSession([FakeResult(row=_row(fencing_token=2))])
    repo = repository_with(session)
    lease = ManagedAllocationLease(
        allocation_id="msa_1",
        worker_id="worker_1",
        fencing_token=2,
        expires_at=NOW + timedelta(seconds=300),
    )

    await repo.commit_active(
        lease,
        AllocationResult(
            provider_ref="ref_secret",
            ownership_digest="digest_1",
            state=ManagedSandboxState.ACTIVE,
        ),
        encrypted_ref=b"cipher",
        now=NOW,
    )

    _statement, params = session.statements[-1]
    assert params["provider_ref"] == b"cipher"
    assert "ref_secret" not in str(params)
```

`_row(...)`와 `repository_with(session)`은 이 파일의 기존 헬퍼 스타일을 따라
파일 상단에 만든다 — `repository_with`는 `session_factory`가 그 세션을 내주는
`PostgresManagedSandboxRepository`를 돌려준다 (`:71`의 기존 헬퍼와 같은 모양).

import에 추가:

```python
from datetime import timedelta

from neos.coding.managed.adapters import AllocationResult
from neos.coding.managed.allocation import (
    ManagedAllocationLease,
    StaleManagedSandboxLease,
)
from neos.coding.managed.domain import ManagedSandboxState
```

- [ ] **Step 2: 통합 테스트를 쓴다 (진짜 펜싱)**

`tests/coding/managed/integration/test_postgres_allocation.py`. fixture는
`test_postgres_admission.py`의 `managed_postgres_session_factory`를 그대로 쓰기 위해
`tests/coding/managed/integration/conftest.py`로 **옮긴다** (두 파일이 공유해야 한다):

```python
import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from neos.coding.managed.adapters import AllocationResult
from neos.coding.managed.allocation import StaleManagedSandboxLease
from neos.coding.managed.domain import ManagedSandboxState
from neos.coding.managed.repository import PostgresManagedSandboxRepository


NOW = datetime(2026, 8, 11, 12, tzinfo=UTC)


@pytest.mark.integration
async def test_only_one_worker_wins_a_concurrent_claim(
    managed_postgres_session_factory,
) -> None:
    """두 워커가 동시에 클레임하면 정확히 하나만 이겨야 한다.

    이것이 fake 세션으로 증명할 수 없는 부분이다 -- UPDATE ... WHERE 의 원자성이
    실제 Postgres 에서 성립하는지가 요점이다.
    """
    repo = PostgresManagedSandboxRepository(managed_postgres_session_factory)
    await _seed_admitted_allocation(managed_postgres_session_factory, "msa_1")

    outcomes = await asyncio.gather(
        repo.claim_allocation("msa_1", "worker_1", now=NOW, lease_seconds=300),
        repo.claim_allocation("msa_1", "worker_2", now=NOW, lease_seconds=300),
        return_exceptions=True,
    )

    won = [o for o in outcomes if not isinstance(o, BaseException)]
    lost = [o for o in outcomes if isinstance(o, StaleManagedSandboxLease)]
    assert len(won) == 1
    assert len(lost) == 1


@pytest.mark.integration
async def test_a_stale_token_cannot_commit_after_lease_takeover(
    managed_postgres_session_factory,
) -> None:
    repo = PostgresManagedSandboxRepository(managed_postgres_session_factory)
    await _seed_admitted_allocation(managed_postgres_session_factory, "msa_2")
    later = NOW + timedelta(minutes=10)

    stale = await repo.claim_allocation(
        "msa_2", "worker_1", now=NOW, lease_seconds=300
    )
    fresh = await repo.claim_allocation(
        "msa_2", "worker_2", now=later, lease_seconds=300
    )
    result = AllocationResult(
        provider_ref="ref_1",
        ownership_digest="digest_1",
        state=ManagedSandboxState.ACTIVE,
    )

    with pytest.raises(StaleManagedSandboxLease):
        await repo.commit_active(stale, result, encrypted_ref=b"cipher", now=later)

    committed = await repo.commit_active(
        fresh, result, encrypted_ref=b"cipher", now=later
    )
    assert committed.state is ManagedSandboxState.ACTIVE
```

`_seed_admitted_allocation()`은 `test_postgres_admission.py`의 `_seed_runs()`를 따라
`coding_tasks` → `coding_runs` → `coding_sandbox_admissions` →
`coding_managed_sandboxes`(state `admitted`, `generation=1`, `fencing_token=1`,
`version=1`) 순으로 `INSERT` 한다. 같은 파일에 만들고 두 테스트가 공유한다.

- [ ] **Step 3: 실패를 확인한다**

```bash
GOOGLE_API_KEY=test-key /Users/ywsung/Desktop/neos/.venv/bin/pytest -q \
  tests/coding/managed/test_repository.py
```

Expected: FAIL — `ModuleNotFoundError: neos.coding.managed.allocation`

- [ ] **Step 4: lease 계약을 만든다**

`neos/coding/managed/allocation.py`:

```python
from dataclasses import dataclass
from datetime import datetime


class StaleManagedSandboxLease(RuntimeError):
    """펜싱 토큰이 낡아 이 워커는 더 이상 이 할당을 진행시킬 수 없다."""


@dataclass(frozen=True, slots=True)
class ManagedAllocationLease:
    allocation_id: str
    worker_id: str
    fencing_token: int
    expires_at: datetime
```

> `worker_id`는 DB에 저장되지 않는다 — 045에 컬럼이 없고, 소유권 증명은
> `fencing_token`이 단독으로 한다. 진단·로깅용으로만 들고 다닌다.

- [ ] **Step 5: repository에 claim을 구현한다**

`neos/coding/managed/repository.py`의 `PostgresManagedSandboxRepository`에 추가:

```python
    async def claim_allocation(
        self,
        allocation_id: str,
        worker_id: str,
        *,
        now: datetime,
        lease_seconds: int,
    ) -> ManagedAllocationLease:
        _require_timezone_aware("claim time", now)
        if lease_seconds < 1:
            raise ValueError("lease_seconds_invalid")
        expires_at = now + timedelta(seconds=lease_seconds)
        async with await self._session_factory() as session:
            async with session.begin():
                row = (
                    await session.execute(
                        text(
                            """
                            UPDATE coding_managed_sandboxes
                               SET fencing_token = fencing_token + 1,
                                   lease_expires_at = :expires_at,
                                   version = version + 1,
                                   updated_at = :now
                             WHERE allocation_id = :allocation_id
                               AND (
                                   lease_expires_at IS NULL
                                   OR lease_expires_at <= :now
                               )
                         RETURNING fencing_token
                            """
                        ),
                        {
                            "allocation_id": allocation_id,
                            "expires_at": expires_at,
                            "now": now,
                        },
                    )
                ).one_or_none()
        if row is None:
            raise StaleManagedSandboxLease(allocation_id)
        return ManagedAllocationLease(
            allocation_id=allocation_id,
            worker_id=worker_id,
            fencing_token=row.fencing_token,
            expires_at=expires_at,
        )
```

`UPDATE`가 행을 잠그므로 별도 `SELECT ... FOR UPDATE`가 필요 없다.
살아 있는 리스가 있으면 `WHERE`가 걸러 0행이 되고 `StaleManagedSandboxLease`가 난다 —
만료 리스는 같은 조건이 통과시키므로 `reclaim_expired`가 따로 필요 없다.

- [ ] **Step 6: commit 두 개를 구현한다**

```python
    async def commit_state(
        self,
        lease: ManagedAllocationLease,
        target: ManagedSandboxState,
        *,
        now: datetime,
        error_code: ProviderErrorCode | None = None,
    ) -> ManagedSandboxAllocation:
        return await self._commit(
            lease,
            now=now,
            assignments="state = :state, error_code = :error_code",
            params={"state": target.value, "error_code": error_code},
        )

    async def commit_active(
        self,
        lease: ManagedAllocationLease,
        result: AllocationResult,
        *,
        encrypted_ref: bytes,
        now: datetime,
    ) -> ManagedSandboxAllocation:
        return await self._commit(
            lease,
            now=now,
            assignments=(
                "state = :state, provider_ref = :provider_ref, "
                "ownership_digest = :ownership_digest, error_code = NULL"
            ),
            params={
                "state": result.state.value,
                "provider_ref": encrypted_ref,
                "ownership_digest": result.ownership_digest,
            },
        )
```

공통 `_commit`은 `fencing_token`을 WHERE에 넣어 낡은 리스를 거른다:

```python
    async def _commit(
        self,
        lease: ManagedAllocationLease,
        *,
        now: datetime,
        assignments: str,
        params: dict[str, object],
    ) -> ManagedSandboxAllocation:
        _require_timezone_aware("commit time", now)
        async with await self._session_factory() as session:
            async with session.begin():
                row = (
                    await session.execute(
                        text(
                            f"""
                            UPDATE coding_managed_sandboxes
                               SET {assignments},
                                   version = version + 1,
                                   updated_at = :now
                             WHERE allocation_id = :allocation_id
                               AND fencing_token = :fencing_token
                         RETURNING allocation_id, state, version,
                                   generation, fencing_token
                            """
                        ),
                        {
                            **params,
                            "allocation_id": lease.allocation_id,
                            "fencing_token": lease.fencing_token,
                            "now": now,
                        },
                    )
                ).one_or_none()
        if row is None:
            raise StaleManagedSandboxLease(lease.allocation_id)
        return _allocation_from_row(row)
```

`assignments`는 **호출자가 넘기는 리터럴 문자열만** 들어간다 (사용자 입력이 아니다).
값은 전부 바인드 파라미터다.

`_allocation_from_row`는 기존 `_read_admission` 옆에 같은 스타일로 만든다.
`neos.coding.managed.allocation`에서 `ManagedAllocationLease`·
`StaleManagedSandboxLease`를 import 한다.

이어서 조인 뷰를 만든다. `neos/coding/managed/allocation.py`:

```python
@dataclass(frozen=True, slots=True)
class AllocationPlan:
    """할당 행 + admission 행에서 어댑터 요청에 필요한 것만 모은 읽기 뷰.

    `ManagedSandboxAllocation` 을 부풀리지 않는 이유는 그 dataclass 가 원장 행의
    모양이고, idempotency_key/resource_limits/network_policy 는 admission 소유이기
    때문이다.
    """

    allocation: ManagedSandboxAllocation
    idempotency_key: str
    image_identity: str
    resource_limits: SandboxLimits
    network_policy: ManagedNetworkPolicy
```

`repository.py`:

```python
    async def read_allocation_plan(self, allocation_id: str) -> AllocationPlan:
        async with await self._session_factory() as session:
            async with session.begin():
                row = (
                    await session.execute(
                        text(
                            """
                            SELECT s.*,
                                   a.idempotency_key,
                                   a.resource_limits,
                                   a.network_policy
                              FROM coding_managed_sandboxes AS s
                              JOIN coding_sandbox_admissions AS a
                                ON a.admission_id = s.admission_id
                             WHERE s.allocation_id = :allocation_id
                            """
                        ),
                        {"allocation_id": allocation_id},
                    )
                ).one_or_none()
        if row is None:
            raise ManagedSandboxNotFound(allocation_id)
        return _plan_from_row(row)
```

`coding_sandbox_admissions`의 `resource_limits`·`network_policy` 컬럼명이 다르면
아래로 확인하고 SELECT 절을 맞춘다:

```bash
sed -n '3,50p' db/migrations/045_add_coding_managed_sandboxes.sql
```

- [ ] **Step 7: 통과를 확인한다**

```bash
GOOGLE_API_KEY=test-key /Users/ywsung/Desktop/neos/.venv/bin/pytest -q \
  tests/coding/managed
```

Expected: `80 passed, 4 skipped` — 단위 4건이 더해지고, 신규 통합 2건은
`CODING_TEST_DATABASE_URL`이 없으면 기존 2건과 함께 skip 된다.

`CODING_TEST_DATABASE_URL`이 설정돼 있다면 통합까지 함께 확인한다:

```bash
CODING_TEST_DATABASE_URL=... GOOGLE_API_KEY=test-key \
  /Users/ywsung/Desktop/neos/.venv/bin/pytest -q -m integration tests/coding/managed
```

Expected: `4 passed` — 펜싱이 진짜 Postgres에서 성립한다는 증거다.
DB가 없어 skip 됐다면 **그 사실을 원장에 남긴다** (Task 9 Step 8).

- [ ] **Step 8: `transition_allocation`이 그대로인지 확인하고 커밋**

```bash
git diff --stat neos/coding/managed/domain.py
```

Expected: **출력 없음** — 원장 5번 줄의 범위 결정("순수 함수로 유지")을 지켰다는 증거다.

```bash
/Users/ywsung/Desktop/neos/.venv/bin/ruff check neos/coding/managed tests/coding/managed
git add neos/coding/managed/allocation.py neos/coding/managed/repository.py \
  tests/coding/managed/test_repository.py \
  tests/coding/managed/integration/test_postgres_allocation.py \
  tests/coding/managed/integration/conftest.py
git commit -m "feat(coding): fence managed sandbox allocation claims

Task 1 범위 결정 이행 -- transition_allocation 은 순수 함수로 두고 version/fence
검사를 repository claim/commit 에 둔다. 045 에 lease_owner 컬럼이 없으므로 소유권
증명은 fencing_token 이 단독으로 하고 worker_id 는 진단용으로만 들고 다닌다."
```

---

### Task 8: 플랜14 Task 5 (2/3) — `advance()`와 모호한 결과 복구

**Files:**
- Modify: `neos/coding/managed/allocation.py`
- Create: `tests/coding/managed/test_allocation_service.py`

**Interfaces:**
- Consumes: Task 7의 `claim_allocation`·`commit_state`·`commit_active`·`StaleManagedSandboxLease`. `FakeManagedSandboxAdapter(allocate_fault=...)`와 `.allocate_calls`·`.rediscovery_calls`·`.find_by_idempotency_key()`.
- Produces: `ManagedSandboxAllocationService.advance(allocation_id: str, *, worker_id: str) -> ManagedSandboxAllocation`

> **오류 분류가 이 태스크의 핵심이다.** 계층은 `CreateSucceededThenTimedOut` → `ManagedAdapterTimeoutError` → (`ManagedAdapterError`, `TimeoutError`)이다. 따라서 **`ManagedAdapterTimeoutError`가 모호성**(RECOVERY_PENDING)이고, 나머지 typed error(`ManagedAdapterValidationError`·`ManagedAdapterOwnershipError`·`ManagedAdapterNotFoundError`)는 **확정 실패**(FAILED)다. `except` 순서를 뒤집으면 타임아웃이 확정 실패로 잘못 분류된다.
>
> **한 번의 `advance()`는 provider 연산 1회 + 내구 전이 1회만 한다.** 루프를 돌리지 않는다 — 재시도는 호출자(Task 6의 Celery 조정자, 이 계획 범위 밖)가 다시 `advance()`를 부르는 것으로 한다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/coding/managed/test_allocation_service.py`:

```python
from datetime import UTC, datetime

import pytest

from neos.coding.managed.adapters import (
    CreateThenTimeout,
    FakeManagedSandboxAdapter,
    ManagedAdapterValidationError,
)
from neos.coding.managed.domain import ManagedSandboxState


NOW = datetime(2026, 8, 11, 12, tzinfo=UTC)


async def test_allocate_timeout_rediscovers_without_a_second_create(
    allocation_service,
) -> None:
    """create-then-timeout 은 재생성이 아니라 재발견으로 복구돼야 한다.

    두 번째 create 를 내면 고아 샌드박스가 생기고 쿼터가 샌다.
    """
    service, adapter = allocation_service(
        adapter=FakeManagedSandboxAdapter(allocate_fault=CreateThenTimeout())
    )

    first = await service.advance("msa_1", worker_id="worker_1")
    assert first.state is ManagedSandboxState.RECOVERY_PENDING

    second = await service.advance("msa_1", worker_id="worker_2")
    assert second.state is ManagedSandboxState.ACTIVE
    assert adapter.allocate_calls == 1
    assert adapter.rediscovery_calls == 1


async def test_a_definite_failure_commits_failed(allocation_service) -> None:
    service, adapter = allocation_service(
        adapter=FakeManagedSandboxAdapter(
            allocate_fault=ManagedAdapterValidationError("image_identity_mismatch")
        )
    )

    result = await service.advance("msa_1", worker_id="worker_1")

    assert result.state is ManagedSandboxState.FAILED
    assert adapter.allocate_calls == 1


async def test_recovery_without_a_provider_record_needs_an_operator(
    allocation_service,
) -> None:
    """재발견도 실패하면 자동 복구를 시도하지 않는다 (fail-closed)."""
    service, adapter = allocation_service(
        adapter=FakeManagedSandboxAdapter(allocate_fault=CreateThenTimeout()),
        forget_after_timeout=True,
    )

    await service.advance("msa_1", worker_id="worker_1")
    result = await service.advance("msa_1", worker_id="worker_2")

    assert result.state is ManagedSandboxState.MANUAL_RECOVERY_REQUIRED


async def test_advance_performs_at_most_one_provider_call(allocation_service) -> None:
    service, adapter = allocation_service()

    await service.advance("msa_1", worker_id="worker_1")

    assert adapter.allocate_calls == 1
    assert adapter.rediscovery_calls == 0
```

`allocation_service`는 **DB를 쓰지 않는다** — 이 태스크가 검증하는 것은 오류 분류와
전이 순서이지 SQL이 아니다. 같은 파일에 인메모리 fake repository를 만들어 fixture로 낸다:

```python
class FakeAllocationRepository:
    """claim/commit 계약만 흉내 내는 인메모리 repository.

    펜싱의 **원자성**은 Task 7 의 통합 테스트가 본다. 여기서는 서비스가 어떤 순서로
    무엇을 커밋하는지만 본다.
    """

    def __init__(self, allocation) -> None:
        self.allocation = allocation
        self.committed: list[ManagedSandboxState] = []
        self._token = allocation.fencing_token

    async def claim_allocation(self, allocation_id, worker_id, *, now, lease_seconds):
        self._token += 1
        return ManagedAllocationLease(
            allocation_id=allocation_id,
            worker_id=worker_id,
            fencing_token=self._token,
            expires_at=now + timedelta(seconds=lease_seconds),
        )

    async def read_allocation(self, allocation_id):
        return self.allocation

    async def commit_state(self, lease, target, *, now, error_code=None):
        self.committed.append(target)
        self.allocation = replace(self.allocation, state=target, error_code=error_code)
        return self.allocation

    async def commit_active(self, lease, result, *, encrypted_ref, now):
        self.committed.append(result.state)
        self.allocation = replace(self.allocation, state=result.state)
        return self.allocation


@pytest.fixture
def allocation_service():
    def build(*, adapter=None, forget_after_timeout=False):
        adapter = adapter or FakeManagedSandboxAdapter()
        repository = FakeAllocationRepository(_admitted_allocation())
        service = ManagedSandboxAllocationService(
            repository=repository,
            adapters={"docker": adapter},
            cipher=_IdentityCipher(),
            lease_seconds=300,
            clock=lambda: NOW,
        )
        if forget_after_timeout:
            adapter.forget_all()
        return service, adapter

    return build
```

`_IdentityCipher`는 `encrypt(s) -> s.encode()` / `decrypt(b) -> b.decode()`인 테스트
전용 cipher다 (Task 9의 진짜 cipher는 별도로 검증한다).
`_admitted_allocation()`은 `state=ADMITTED`, `provider="docker"`, `generation=1`,
`fencing_token=1`인 `ManagedSandboxAllocation`을 만든다.
`adapter.forget_all()`은 fake의 내부 기록을 비워 재발견이 `None`을 내게 하는 테스트
전용 메서드다 — `FakeManagedSandboxAdapter`에 없으면 함께 만든다.

- [ ] **Step 2: 실패를 확인한다**

```bash
GOOGLE_API_KEY=test-key /Users/ywsung/Desktop/neos/.venv/bin/pytest -q \
  tests/coding/managed/test_allocation_service.py
```

Expected: FAIL — `ImportError: cannot import name 'ManagedSandboxAllocationService'`

- [ ] **Step 3: 서비스를 구현한다**

`neos/coding/managed/allocation.py`에 추가:

```python
class ManagedSandboxAllocationService:
    """할당을 **한 칸씩** 전진시킨다.

    한 번의 `advance()` 는 provider 연산 1회 + 내구 전이 1회만 한다. 루프를 돌리지
    않는 이유는 프로세스가 어느 지점에서 죽어도 원장이 다음 진입점을 알려주게
    하기 위해서다 -- 재시도는 호출자가 다시 부르는 것으로 한다.
    """

    def __init__(
        self,
        *,
        repository,
        adapters: Mapping[str, object],
        cipher,
        lease_seconds: int,
        clock=None,
    ) -> None:
        self._repository = repository
        self._adapters = dict(adapters)
        self._cipher = cipher
        self._lease_seconds = lease_seconds
        self._clock = clock or (lambda: datetime.now(UTC))

    async def advance(self, allocation_id: str, *, worker_id: str):
        now = self._clock()
        lease = await self._repository.claim_allocation(
            allocation_id, worker_id, now=now, lease_seconds=self._lease_seconds
        )
        plan = await self._repository.read_allocation_plan(allocation_id)
        adapter = self._adapters[plan.allocation.provider]

        if plan.allocation.state is ManagedSandboxState.ADMITTED:
            return await self._allocate(lease, plan, adapter, now=now)
        if plan.allocation.state is ManagedSandboxState.RECOVERY_PENDING:
            return await self._rediscover(lease, plan, adapter, now=now)
        raise InvalidManagedSandboxTransition(plan.allocation.state.value)

    async def _allocate(self, lease, plan, adapter, *, now):
        await self._repository.commit_state(
            lease, ManagedSandboxState.ALLOCATING, now=now
        )
        try:
            result = await adapter.allocate(_request_for(plan))
        except ManagedAdapterTimeoutError:
            # 모호하다 -- provider 가 만들었는지 알 수 없으므로 재생성하지 않는다.
            return await self._repository.commit_state(
                lease,
                ManagedSandboxState.RECOVERY_PENDING,
                now=now,
                error_code=ProviderErrorCode.PROVIDER_TIMEOUT,
            )
        except ManagedAdapterError as error:
            return await self._repository.commit_state(
                lease,
                ManagedSandboxState.FAILED,
                now=now,
                error_code=_error_code(error),
            )
        return await self._commit_result(lease, allocation, result, now=now)

    async def _rediscover(self, lease, plan, adapter, *, now):
        found = await adapter.find_by_idempotency_key(plan.idempotency_key)
        if found is None:
            # 자동 복구를 시도하지 않는다 -- 운영자 승인이 필요하다 (fail-closed).
            return await self._repository.commit_state(
                lease,
                ManagedSandboxState.MANUAL_RECOVERY_REQUIRED,
                now=now,
                error_code=ProviderErrorCode.PROVIDER_NOT_FOUND,
            )
        return await self._commit_result(lease, plan, found, now=now)

    async def _commit_result(self, lease, plan, result, *, now):
        encrypted = self._cipher.encrypt(result.provider_ref)
        return await self._repository.commit_active(
            lease, result, encrypted_ref=encrypted, now=now
        )
```

`_request_for(plan)`은 조인 뷰에서 8필드를 채워 `ManagedAllocationRequest`를 만든다:

```python
def _request_for(plan: AllocationPlan) -> ManagedAllocationRequest:
    allocation = plan.allocation
    return ManagedAllocationRequest(
        allocation_id=allocation.allocation_id,
        idempotency_key=plan.idempotency_key,
        region=allocation.region,
        image_identity=plan.image_identity,
        resource_limits=plan.resource_limits,
        network_policy=plan.network_policy,
        ownership_digest=allocation.ownership_digest,
        absolute_expires_at=allocation.absolute_expires_at,
    )
```

`except` 절의 **순서를 바꾸지 않는다** — `ManagedAdapterTimeoutError`가
`ManagedAdapterError`의 하위이므로 뒤에 두면 절대 잡히지 않는다.

`_error_code()`도 같은 모듈에 만든다 —
`ManagedAdapterValidationError` → `POLICY_DENIED`,
`ManagedAdapterOwnershipError` → `PROVIDER_AUTH_ERROR`,
`ManagedAdapterNotFoundError` → `PROVIDER_NOT_FOUND`, 그 밖 → `OTHER`.

`read_allocation_plan()`은 Task 7에서 이미 만들었다.

`FakeAllocationRepository`도 `read_allocation` 대신 `read_allocation_plan`을 내야
한다 — Step 1의 fake에서 `read_allocation`을 아래로 바꾼다:

```python
    async def read_allocation_plan(self, allocation_id):
        return AllocationPlan(
            allocation=self.allocation,
            idempotency_key="idem_1",
            image_identity=IMAGE,
            resource_limits=SandboxLimits.safe_defaults(),
            network_policy=ManagedNetworkPolicy.BLOCK_ALL,
        )
```

- [ ] **Step 4: 통과를 확인한다**

```bash
GOOGLE_API_KEY=test-key /Users/ywsung/Desktop/neos/.venv/bin/pytest -q tests/coding/managed
```

Expected: 전부 PASS

- [ ] **Step 5: 커밋**

```bash
/Users/ywsung/Desktop/neos/.venv/bin/ruff check neos/coding/managed tests/coding/managed
git add neos/coding/managed/allocation.py neos/coding/managed/repository.py \
  tests/coding/managed/test_allocation_service.py
git commit -m "feat(coding): recover ambiguous managed allocation outcomes

create-then-timeout 을 재생성이 아니라 재발견으로 복구한다. 타임아웃은 모호성이므로
RECOVERY_PENDING 으로, 확정 typed 실패는 FAILED 로 가른다. 재발견도 실패하면
자동 복구 대신 MANUAL_RECOVERY_REQUIRED 로 멈춘다 (fail-closed)."
```

---

### Task 9: 플랜14 Task 5 (3/3) — cipher와 런타임 배선

**Files:**
- Create: `neos/coding/managed/crypto.py`
- Modify: `neos/config/schema.py` (관리형 설정에 키·리스 TTL 추가)
- Modify: `neos/coding/runtime.py`
- Create: `tests/coding/managed/test_crypto.py`
- Modify: `tests/coding/sandbox/test_runtime_ownership.py`
- Modify: `.superpowers/sdd/2026-07-25-managed-sandbox-control-plane/progress.md`

**Interfaces:**
- Consumes: Task 8의 `ManagedSandboxAllocationService(..., cipher=...)`, Task 4의 회귀 가드
- Produces:
  - `ProviderReferenceCipher` 프로토콜 — `encrypt(provider_ref: str) -> bytes` · `decrypt(encrypted_ref: bytes) -> str` (**동기 메서드**)
  - `AesGcmProviderReferenceCipher(key: bytes, key_version: int)`
  - `runtime` 어댑터 레지스트리 — `{provider_name: adapter}`

> **D1c를 지킨다.** 이 태스크가 `runtime.py`를 편집한다. Task 4의 가드가 초록인지 **편집 후 반드시 확인한다.** 어댑터 레지스트리는 *샌드박스 provider* 축이고 `TrackedCodingModel`은 *모델* 축이라 직교하지만, 같은 함수 안에 있어 실수하기 쉽다.
>
> **`managed.enabled=false`에서 기존 동작 불변.** 레지스트리는 비활성일 때 만들지 않는다.

- [ ] **Step 1: cipher 테스트를 쓴다**

`tests/coding/managed/test_crypto.py`:

```python
import pytest

from neos.coding.managed.crypto import AesGcmProviderReferenceCipher


KEY = bytes(range(32))


def _cipher(key_version: int = 1) -> AesGcmProviderReferenceCipher:
    return AesGcmProviderReferenceCipher(
        key=KEY,
        key_version=key_version,
        associated_data="msa_1:docker:1",
    )


def test_roundtrip_recovers_the_reference() -> None:
    cipher = _cipher()
    assert cipher.decrypt(cipher.encrypt("ref_secret")) == "ref_secret"


def test_ciphertext_never_contains_the_plaintext() -> None:
    assert b"ref_secret" not in _cipher().encrypt("ref_secret")


def test_nonce_is_random_so_ciphertexts_differ() -> None:
    cipher = _cipher()
    assert cipher.encrypt("ref_secret") != cipher.encrypt("ref_secret")


def test_a_different_allocation_cannot_decrypt() -> None:
    """AAD 가 allocation_id:provider:generation 이므로 교차 복호가 막힌다."""
    sealed = _cipher().encrypt("ref_secret")
    other = AesGcmProviderReferenceCipher(
        key=KEY, key_version=1, associated_data="msa_2:docker:1"
    )
    with pytest.raises(Exception):
        other.decrypt(sealed)


def test_a_wrong_key_cannot_decrypt() -> None:
    sealed = _cipher().encrypt("ref_secret")
    other = AesGcmProviderReferenceCipher(
        key=bytes(32), key_version=1, associated_data="msa_1:docker:1"
    )
    with pytest.raises(Exception):
        other.decrypt(sealed)
```

- [ ] **Step 2: 실패를 확인한다**

```bash
GOOGLE_API_KEY=test-key /Users/ywsung/Desktop/neos/.venv/bin/pytest -q \
  tests/coding/managed/test_crypto.py
```

Expected: FAIL — `ModuleNotFoundError: neos.coding.managed.crypto`

- [ ] **Step 3: cipher를 구현한다**

`neos/coding/managed/crypto.py`:

```python
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


_NONCE_BYTES = 12
_VERSION_BYTES = 2


class AesGcmProviderReferenceCipher:
    """provider 참조를 봉인한다.

    평문 참조는 저장도 로깅도 하지 않는다 -- 원장이 유출돼도 provider 세션을
    직접 조작할 수 없어야 한다. AAD 에 allocation_id:provider:generation 을 묶어
    다른 할당의 봉인을 가져다 쓰는 것을 막는다.
    """

    __slots__ = ("_aesgcm", "_associated_data", "_key_version")

    def __init__(
        self, *, key: bytes, key_version: int, associated_data: str
    ) -> None:
        if len(key) not in (16, 24, 32):
            raise ValueError("managed_cipher_key_invalid")
        if key_version < 1:
            raise ValueError("managed_cipher_key_version_invalid")
        self._aesgcm = AESGCM(key)
        self._key_version = key_version
        self._associated_data = associated_data.encode("utf-8")

    def encrypt(self, provider_ref: str) -> bytes:
        nonce = os.urandom(_NONCE_BYTES)
        sealed = self._aesgcm.encrypt(
            nonce, provider_ref.encode("utf-8"), self._associated_data
        )
        return (
            self._key_version.to_bytes(_VERSION_BYTES, "big") + nonce + sealed
        )

    def decrypt(self, encrypted_ref: bytes) -> str:
        nonce = encrypted_ref[_VERSION_BYTES : _VERSION_BYTES + _NONCE_BYTES]
        sealed = encrypted_ref[_VERSION_BYTES + _NONCE_BYTES :]
        return self._aesgcm.decrypt(
            nonce, sealed, self._associated_data
        ).decode("utf-8")
```

`__repr__`을 정의하지 않는다 — 기본 `repr`은 키를 노출하지 않는다.

- [ ] **Step 4: 설정을 추가한다 (매직넘버 금지)**

> ⚠️ **`allocation_lease_seconds`는 이미 있다** — `ManagedSandboxConfig`(`schema.py:787`,
> `default=60, gt=0, le=600`). **다시 추가하지 말고 그대로 쓴다.** Task 8의 서비스에
> `lease_seconds=config.sandbox.managed.allocation_lease_seconds`로 넘긴다.

`ManagedSandboxConfig`(`schema.py:779`)에 **한 줄만** 추가한다:

```python
    provider_reference_key_version: int = Field(
        default=1,
        ge=1,
        description="provider 참조 봉인에 쓰는 키 버전.",
    )
```

키 자체는 시크릿이므로 `config.secrets`에 `managed_provider_reference_key`로 둔다 —
기존 시크릿 필드 옆에 같은 스타일로 추가하고, `.env.template`에도 **이름만** 넣는다
(값은 넣지 않는다).

> **키가 없는데 `managed.enabled=true`면 기동에서 막는다.** 트랙 B의 I2가 남긴 교훈이다 —
> 빈 키로 뜨면 빈 키로 서명한 토큰이 통과한다. `validate_coding_model_policy()` 옆에
> 같은 형태의 검증을 붙인다.

- [ ] **Step 5: 통과를 확인한다**

```bash
GOOGLE_API_KEY=test-key /Users/ywsung/Desktop/neos/.venv/bin/pytest -q \
  tests/coding/managed/test_crypto.py tests/config
```

Expected: 전부 PASS

- [ ] **Step 6: 런타임 레지스트리를 배선하고 D1c 가드를 확인한다**

`neos/coding/runtime.py`의 `_prepare_real_coding_loop`에서 **`TrackedCodingModel`
래핑 블록을 건드리지 않고**, 관리형이 켜졌을 때만 어댑터 레지스트리를 만든다:

```python
def _managed_adapter_registry(*, config: AppConfig, sandboxes):
    """관리형이 꺼져 있으면 아무것도 만들지 않는다 -- 기존 동작 불변."""
    managed = config.sandbox.managed
    if not managed.enabled:
        return {}
    return {"docker": DockerShadowManagedAdapter(provider=sandboxes)}
```

`finish(sandboxes)` 안에서 호출하고, 레지스트리가 비어 있으면 할당 서비스를
만들지 않는다.

`tests/coding/sandbox/test_runtime_ownership.py`에 추가:

```python
def test_managed_registry_is_empty_when_managed_is_disabled(monkeypatch) -> None:
    """managed.enabled=false 에서 기존 Memory/Docker 경로가 그대로여야 한다."""
    config = AppConfig.model_validate({
        "coding_model": {
            "enabled": True,
            "input_cost_micros_per_million": 1,
            "output_cost_micros_per_million": 1,
        },
        "sandbox": {"enabled": True},
        "secrets": {"anthropic_api_key": "test"},
    })

    assert runtime_module._managed_adapter_registry(
        config=config, sandboxes=object()
    ) == {}
```

- [ ] **Step 7: D1c 가드가 여전히 초록인지 확인한다**

```bash
GOOGLE_API_KEY=test-key /Users/ywsung/Desktop/neos/.venv/bin/pytest -q \
  tests/coding/sandbox/test_runtime_ownership.py -v
```

Expected: `test_real_loop_wraps_the_production_model_for_collection` **PASS**.
빨개지면 `runtime.py` 편집이 D1c 배선을 건드린 것이므로 되돌린다.

- [ ] **Step 8: 전체 스위트와 원장 기록**

```bash
GOOGLE_API_KEY=test-key /Users/ywsung/Desktop/neos/.venv/bin/pytest -q tests/coding
/Users/ywsung/Desktop/neos/.venv/bin/ruff check neos/coding tests/coding
```

Expected: `0 failed`

`.superpowers/sdd/2026-07-25-managed-sandbox-control-plane/progress.md` 끝에 덧붙인다
(**로컬 전용 — 커밋하지 않는다**, PF1 판정):

```
Task 5: complete (2026-08-11) — 펜스된 claim/commit, 모호한 결과 복구, provider 참조
봉인, 런타임 어댑터 레지스트리. Task 1 범위 결정 #1(version/fence 검사) 이행 완료.
045 에 lease_owner 컬럼이 없어 worker_id 는 영속화하지 않고 fencing_token 이 단독으로
소유권을 증명한다 — 마이그레이션 046 을 만들지 않았다.
통합 테스트(펜싱 원자성)는 CODING_TEST_DATABASE_URL 유무에 따라 실행/skip 된다.
```

Task 7 Step 7에서 통합 테스트가 skip 됐다면 그 사실도 여기 한 줄로 남긴다.

- [ ] **Step 9: 커밋**

`.superpowers/`는 gitignore이므로 원장 파일은 `git add`에 넣지 않는다.

```bash
git add neos/coding/managed/crypto.py neos/config/schema.py neos/coding/runtime.py \
  tests/coding/managed/test_crypto.py tests/coding/sandbox/test_runtime_ownership.py
git commit -m "feat(coding): seal managed provider references

AES-GCM 으로 provider 참조를 봉인한다. AAD 에 allocation_id:provider:generation 을
묶어 교차 복호를 막고, 평문 참조는 저장도 로깅도 하지 않는다. 런타임 어댑터
레지스트리는 managed.enabled 가 켜졌을 때만 만들어 기존 경로를 불변으로 둔다."
```

---

### Task 10: 문서 정정 반영

**Files:**
- Modify: `docs/DEEP_ANALYSIS_HARNESS_ROADMAP.md` (§12)
- Modify: `docs/coding_agent_task_resume.md`

**Interfaces:**
- Consumes: Task 1–9의 결과
- Produces: 인벤토리와 실제 상태가 일치하는 문서

> **왜 별도 태스크인가.** 스펙 §9의 완료 기준 7번이며, 이 계획이 문서 다섯 곳을 무효화한다. 고치지 않으면 다음 재개가 다시 같은 곳에서 넘어진다 — §12.3이 스스로 적은 실패 모드다.

- [ ] **Step 1: 로드맵 §12의 인벤토리를 갱신한다**

`docs/DEEP_ANALYSIS_HARNESS_ROADMAP.md` §12.7에서:
- **CA2** → 종결. *"CA5-b 구현으로 판정하고 채택 (2026-08-11). 판정 근거는 스펙 §1.1"*
- **CA3** → 종결. *"dev → 워크트리 merge 로 합류. `git merge-tree` 실측 충돌 0건이었고, 리베이스를 쓰지 않은 이유는 11커밋 해시 재작성이 CA4 정리의 근거를 지우기 때문"*
- **CA4** → 종결. *"이중 기록 + Task 4 누락. 기존 24줄을 보존한 채 정정 블록을 덧붙였다"*
- **CA5** → 종결. *"CA5-a(공개 라벨 확장점) / CA5-b(크로스 프로세스 원자적 create)로 분리해 둘 다 해소"*
- **CA1** → *"Task 5 완료. Task 6–10 미착수 (10개 중 5개)"*

- [ ] **Step 2: §12.3의 충돌면 표를 정정한다**

`runtime.py`를 넷째 행으로 추가하고, 재현 절차에 비파괴 측정을 넣는다:

```markdown
| `neos/coding/runtime.py` | **2커밋** +18/−3 (D1c·역할 라우팅) | Task 5가 수정 | 🟡 **앞으로 바꿀 파일** |

> 충돌면을 "브랜치가 이미 바꾼 파일"로만 재면 과소평가된다. **앞으로 바꿀 파일**까지
> 세야 한다. 그리고 추정 대신 측정할 수 있다 — 아무것도 체크아웃하지 않는다:
> `git merge-tree --write-tree --name-only dev <branch>` (exit 0 + 트리 OID 한 줄 = 충돌 없음)
```

- [ ] **Step 3: §12.6의 E-S4 행을 정정한다**

측정법에 가드 테스트를 명시한다:

```markdown
| **E-S4** | 코딩 루프의 LLM 호출이 전부 원장에 남는다 | ✅ | `tests/coding/sandbox/test_runtime_ownership.py::test_real_loop_wraps_the_production_model_for_collection` — 2026-08-11 이전에는 측정법만 있고 **그것을 실행하는 테스트가 없었다** |
```

- [ ] **Step 4: 재개 문서를 갱신한다**

`docs/coding_agent_task_resume.md`:
- §4(미커밋 변경) → 판정 완료로 바꾸고 근거 넷과 커밋 해시를 남긴다
- §6(재개 절차) → 플랜14 Task 6부터 시작하도록 갱신하고, CA3 미결 경고 상자를 제거한다
- §3「Task 4가 남긴 우려」 → CA5-a/CA5-b 각각의 해소 커밋을 적는다

> §4「원장 무결성 문제」는 **Task 2가 이미 교체했다** — 다시 쓰지 않는다.

- [ ] **Step 5: 커밋**

```bash
cd /Users/ywsung/Desktop/neos/.worktrees/managed-sandbox-control-plane
git add docs/DEEP_ANALYSIS_HARNESS_ROADMAP.md docs/coding_agent_task_resume.md
git commit -m "docs(coding): record the track E unblock

CA2·CA3·CA4·CA5 종결과 판정 근거를 인벤토리에 반영한다. §12.3 충돌면 표에
runtime.py 를 넷째 행으로 추가하고, 커밋 수 대신 git merge-tree 로 측정하는 절차를
남긴다. E-S4 의 측정법에 회귀 가드 테스트 경로를 적는다."
```

---

## 완료 확인

전부 끝난 뒤 아래가 참이어야 한다 (스펙 §9).

```bash
cd /Users/ywsung/Desktop/neos/.worktrees/managed-sandbox-control-plane

git status --short                                    # 비어 있음
git merge-base --is-ancestor dev HEAD && echo "dev 포함"
grep -c "provider\._" neos/coding/managed/adapters/docker_shadow.py   # 0
grep -c "Task 4" .superpowers/sdd/*/progress.md       # 1 이상
GOOGLE_API_KEY=test-key /Users/ywsung/Desktop/neos/.venv/bin/pytest -q tests/coding
/Users/ywsung/Desktop/neos/.venv/bin/ruff check neos/coding tests/coding
```

**출하 기준 변화:** E-S3이 ❌ → 🟡(부분, Task 5 몫), E-S4가 ✅(가드 없음) → ✅(가드 포함).
E-S1·E-S2는 변하지 않는다 — dev로의 역방향 머지와 플래그 활성화는 이 계획 범위 밖이다.
