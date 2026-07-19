# YAML-only Feature Flag Warnings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Warn in every environment when a known YAML-only feature flag is supplied as an environment variable, without allowing it to override YAML, and reconcile the loop TODO with already completed work.

**Architecture:** Keep YAML authoritative by maintaining a small explicit environment-variable-to-YAML-path mapping in the configuration loader. A dedicated warning function inspects the already merged bootstrap and process environment once per configuration load; existing secret, bootstrap, legacy override, and `NEOS_*` validation behavior remains separate.

**Tech Stack:** Python 3.12, pytest, `python-dotenv`, Pydantic configuration schema, Markdown documentation

## Global Constraints

- Emit `UserWarning` in development, test, staging, and production.
- Warn only for the seven explicitly mapped YAML-only feature flags.
- Never apply these environment-variable values to application configuration.
- A key present in both bootstrap `.env` and process environment produces one warning.
- Do not edit `.env.template`; it contains unrelated user changes and already directs non-secret settings to YAML.
- Preserve all unrelated dirty worktree files.

---

## File structure

- Modify `neos/config/loader.py`: own the explicit YAML-only flag registry and warning emission during configuration load.
- Modify `tests/config/test_config_loader.py`: own the warning, non-override, non-match, and duplicate-source behavioral contracts.
- Modify `docs/TODO_260729.md`: record verified completion of sections 1, 2, 3, and replace the stale priority table.

### Task 1: Define and enforce the YAML-only warning contract

**Files:**
- Modify: `tests/config/test_config_loader.py`
- Modify: `neos/config/loader.py`

**Interfaces:**
- Consumes: `load_app_config(env: str | None = None, config_path: str | None = None, secrets_path: str | None = None) -> AppConfig`
- Produces: `YAML_ONLY_FEATURE_FLAG_ENV_KEYS: dict[str, str]`
- Produces: `warn_yaml_only_feature_flag_env(env: Mapping[str, str]) -> None`

- [ ] **Step 1: Isolate the seven keys in the autouse fixture**

Add deletion of every new mapping key so a developer's shell cannot make loader tests order- or machine-dependent:

```python
import warnings

import pytest


@pytest.fixture(autouse=True)
def isolate_repo_dotenv(tmp_path, monkeypatch):
    monkeypatch.setattr(loader, "DEFAULT_DOTENV_PATH", tmp_path / "missing.env")
    for env_key in loader.LEGACY_ENV_KEYS | loader.YAML_ONLY_FEATURE_FLAG_ENV_KEYS:
        monkeypatch.delenv(env_key, raising=False)
```

- [ ] **Step 2: Write the failing parameterized warning and YAML-authority test**

Add the following test below `test_legacy_non_secret_env_overrides_yaml_with_warning`:

```python
@pytest.mark.parametrize(
    ("env_key", "yaml_path"),
    loader.YAML_ONLY_FEATURE_FLAG_ENV_KEYS.items(),
)
def test_yaml_only_feature_flag_env_warns_without_overriding_yaml(
    tmp_path,
    monkeypatch,
    env_key,
    yaml_path,
):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    write_yaml(config_dir / "neos.default.yaml", "deep_analysis:\n  enabled: false\n")
    monkeypatch.setattr(loader, "DEFAULT_CONFIG_DIR", config_dir)
    monkeypatch.setenv(env_key, "true")

    with pytest.warns(UserWarning, match=rf"{env_key}.*{yaml_path}"):
        config = loader.load_app_config(env="development")

    if env_key == "DEEP_ANALYSIS_ENABLED":
        assert config.deep_analysis.enabled is False
```

The parameterization verifies the exact key/path copy for all seven flags. The final assertion proves the representative environment value does not become authoritative.

- [ ] **Step 3: Write failing scope and deduplication tests**

```python
def test_unrelated_enabled_env_does_not_emit_yaml_only_warning(monkeypatch):
    monkeypatch.setenv("THIRD_PARTY_ENABLED", "true")

    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        loader.load_app_config(env="development")

    assert not [
        warning
        for warning in captured
        if "is ignored; configure" in str(warning.message)
    ]


def test_yaml_only_flag_in_dotenv_and_process_env_warns_once(tmp_path, monkeypatch):
    dotenv_path = write_dotenv(tmp_path / ".env", "DEEP_ANALYSIS_ENABLED=false\n")
    monkeypatch.setattr(loader, "DEFAULT_DOTENV_PATH", dotenv_path)
    monkeypatch.setenv("DEEP_ANALYSIS_ENABLED", "true")

    with pytest.warns(UserWarning) as captured:
        loader.load_app_config(env="development")

    matching = [
        warning
        for warning in captured
        if "DEEP_ANALYSIS_ENABLED is ignored" in str(warning.message)
    ]
    assert len(matching) == 1
```

- [ ] **Step 4: Run the focused tests and verify the intended failure**

Run:

```bash
.venv/bin/pytest tests/config/test_config_loader.py -q
```

Expected: collection or test failure because `loader.YAML_ONLY_FEATURE_FLAG_ENV_KEYS` does not exist yet.

- [ ] **Step 5: Add the explicit mapping beside the loader environment registries**

Insert after `SECRET_ENV_MAPPING` and before `LEGACY_ENV_KEYS`:

```python
YAML_ONLY_FEATURE_FLAG_ENV_KEYS = {
    "DEEP_ANALYSIS_ENABLED": "deep_analysis.enabled",
    "RECURSIVE_AGENT_ENABLED": "recursive_agent.enabled",
    "HYPER_DEEP_AGENT_ENABLED": "hyper_deep_agent.enabled",
    "A2UI_ENABLED": "a2ui.enabled",
    "RAY_ENABLED": "ray.enabled",
    "EXECUTION_APPROVAL_ENABLED": "execution_approval.enabled",
    "CELERY_ENABLED": "celery.enabled",
}
```

- [ ] **Step 6: Add the minimal warning function**

Insert after `apply_legacy_env_overrides`:

```python
def warn_yaml_only_feature_flag_env(env: Mapping[str, str]) -> None:
    for env_key, dotted_path in YAML_ONLY_FEATURE_FLAG_ENV_KEYS.items():
        if env_key not in env:
            continue
        warnings.warn(
            f"{env_key} is ignored; configure {dotted_path} in YAML.",
            UserWarning,
            stacklevel=2,
        )
```

- [ ] **Step 7: Invoke the warning scan once without changing precedence**

In `load_app_config`, name the merged non-secret environment and reuse it for the legacy override:

```python
    runtime_env = {**bootstrap_env, **process_env}
    warn_yaml_only_feature_flag_env(runtime_env)
    config_data = apply_legacy_env_overrides(config_data, runtime_env, app_env)
```

This replaces only the existing inline `{**bootstrap_env, **process_env}` argument to `apply_legacy_env_overrides`.

- [ ] **Step 8: Run focused tests and verify they pass**

Run:

```bash
.venv/bin/pytest tests/config/test_config_loader.py -q
```

Expected: all tests in the file pass and each of the seven parameter cases emits exactly the requested warning class and text.

- [ ] **Step 9: Run the full configuration suite**

Run:

```bash
.venv/bin/pytest tests/config -q
```

Expected: all configuration tests pass with no regression in secret, legacy override, schema, or `NEOS_*` behavior.

- [ ] **Step 10: Commit the tested loader contract**

```bash
git add neos/config/loader.py tests/config/test_config_loader.py
git commit -m "fix: warn for ignored YAML-only feature flags"
```

### Task 2: Reconcile the loop TODO with verified repository state

**Files:**
- Modify: `docs/TODO_260729.md`

**Interfaces:**
- Consumes: passing Task 1 configuration tests and existing merged CI/failure-bound commits
- Produces: an accurate completed/remaining-work record and next-priority order

- [ ] **Step 1: Mark section 1 resolved without erasing the historical failure analysis**

Append a resolution paragraph before section 2:

```markdown
**해결 (2026-07-19):** 오케스트레이터에 토큰 소비와 독립적인 연속 계통 실패 상한을
추가하고, 인라인 실행 경로에 wall-clock timeout과 durable failure 기록을 추가했다.
항상 실패하며 토큰을 소비하지 않는 워커와 인라인 timeout 회귀 테스트로 두 종료 경계를
고정했다.
```

- [ ] **Step 2: Mark section 2 resolved with the warning-only policy**

Replace `현재 상태`, `남은 함정`, and `제안 (택1)` in section 2 with:

```markdown
**해결 (2026-07-19):** 7개 YAML 전용 플래그를 명시적으로 등록했다. `.env` 또는
프로세스 환경에 이 키가 있으면 모든 실행 환경에서 `UserWarning`으로 무시 사실과 정확한
YAML 경로를 안내한다. 환경변수 값은 적용하지 않으므로 YAML이 계속 유일한 권위다.
일반 `*_ENABLED` 패턴은 외부 변수 오탐을 피하기 위해 경고하지 않는다.
```

- [ ] **Step 3: Mark section 3 resolved with the actual workflow contract**

Replace its stale evidence, impact, and prerequisite paragraphs with:

```markdown
**해결 (2026-07-19):** `.github/workflows/backend-ci.yml`을 추가했다. quality job은
pytest importlib 수집, lint와 설정 검증을 수행하고, workflow/API job은 Postgres·Redis
서비스와 결정론적 테스트 JWT를 사용해 각각의 회귀 suite를 실행한다. §9 수집 충돌,
§10 API 순서 의존 재발 감지, §11 analytics run 격리가 CI 계약에 포함됐다.
```

- [ ] **Step 4: Replace the stale priority summary**

Use this table so only unresolved work is ranked:

```markdown
## 요약 — 다음 권고 순서

| # | 항목 | 근거 |
|---|---|---|
| 1 | **§4 토큰 캡 초과 제어** | 비용 상한 계약이 라운드 내부 병렬 소비를 막지 못함 |
| 2 | **§7 verified 비율 원인 분해** | 심층분석 결과의 실용성을 계측으로 먼저 구분해야 함 |
| 3 | **§5 브로커 장애 정책 결정** | 내구성과 가용성의 제품·운영 트레이드오프가 필요함 |
| 4 | **§15 프로세스 간 스트리밍 조사** | 실제 영향 경로가 아직 미확인임 |
| 5 | **§6 PDF 소스 지원** | 현재 빌트인 소스는 우회됐으며 의존성 결정이 필요함 |
| 6 | **§8 영속화 예외 경계 유지 관찰** | 실제 DB 통합 테스트로 완화됐고 현재 동작 변경은 불필요함 |

**완료:** §1, §2, §3, §9, §11. §10은 production 원인 수정이 아니라 CI 재발 감지
계약까지 완료했다.
```

- [ ] **Step 5: Validate documentation consistency**

Run:

```bash
rg -n "해결 \(2026-07-19\)|요약 — 다음 권고 순서|§4 토큰 캡" docs/TODO_260729.md
git diff --check -- docs/TODO_260729.md
```

Expected: resolution entries for sections 1, 2, 3, 9, 11; the new priority heading and §4 first; no whitespace errors.

- [ ] **Step 6: Commit the reconciled TODO**

```bash
git add docs/TODO_260729.md
git commit -m "docs: reconcile loop TODO priorities"
```

### Task 3: Final regression verification

**Files:**
- Verify only: `neos/config/loader.py`
- Verify only: `tests/config/test_config_loader.py`
- Verify only: `docs/TODO_260729.md`

**Interfaces:**
- Consumes: Task 1 implementation and Task 2 documentation
- Produces: evidence that the focused feature and CI-targeted backend suites remain green

- [ ] **Step 1: Run focused configuration verification from a clean process**

```bash
.venv/bin/pytest tests/config -q
```

Expected: all tests pass.

- [ ] **Step 2: Run the GitHub Actions workflow suite locally**

```bash
.venv/bin/pytest tests/workflow -q
```

Expected: all workflow tests pass with importlib collection mode supplied by project pytest configuration.

- [ ] **Step 3: Run the GitHub Actions API suite locally**

```bash
.venv/bin/pytest tests/api -q
```

Expected: all API tests pass in one process. If required Postgres or Redis services are unavailable locally, record the exact infrastructure failure and rely only on the focused configuration result for this change; do not describe the unavailable suite as passing.

- [ ] **Step 4: Inspect final scope**

```bash
git status --short
git log -3 --oneline
```

Expected: the two implementation commits are present; pre-existing unrelated modifications and untracked files remain untouched.
