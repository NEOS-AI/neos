import inspect
import re
from pathlib import Path

import pytest

from neos.config.model_routing import ModelResolution, ResolutionSource
from neos.workflow.deep_analysis.manifest import (
    MANIFEST_KIND,
    MANIFEST_VERSION,
    RUN_PROMPTS,
    build_manifest,
    component_id,
    prompt_hashes,
)


def _resolution(model: str, role: str) -> ModelResolution:
    return ModelResolution(
        model=model,
        provider="anthropic",
        role=role,
        source=ResolutionSource.ROLE_DEFAULT,
    )


_MODELS = {
    "scout": _resolution("claude-sonnet-5", "everyday"),
    "dig": _resolution("claude-opus-5", "powerful"),
    "synth": _resolution("claude-opus-5", "powerful"),
    "judge": _resolution("claude-sonnet-5", "everyday"),
}
_BUDGET = {
    "global_token_cap": 140000,
    "synthesis_max_tokens": 2000,
    "finalization_floor_tokens": 53600,
    "report_floor_tokens": 43200,
    "grading_floor_tokens": 21600,
    "min_viable_output_tokens": 2048,
    "available_for_investigation": 86400,
    "report_floor_funded_attempts": 1.2,
}


def _build(**overrides):
    kwargs = {
        "profile": "dev",
        "models": _MODELS,
        "budget": _BUDGET,
        "prompts": {"decompose": "sha256:abc"},
        "skills": [{"name": "web-search", "version": "1.0.0"}],
        "components": {"grader": "graders.deterministic:DeterministicGrader"},
        "config": {"max_depth": 2},
    }
    kwargs.update(overrides)
    return build_manifest(**kwargs)


def test_build_manifest_does_not_read_settings():
    """계산 능력이 없어야 매니페스트가 실제와 어긋날 수 없다.

    기존 지문(`scripts/deep_analysis_funnel_sample.py:181`)이 dev 런에
    기본 프로파일 캡 300000 을 적은 것은 버그가 아니라 재계산이다.
    같은 값을 두 곳에서 유도하면 두 곳이 갈라진다.
    """
    source = inspect.getsource(build_manifest)

    assert "settings" not in source
    assert "floor_tokens(" not in source


def test_build_manifest_is_pure():
    assert _build() == _build()


def test_build_manifest_records_version_and_profile():
    manifest = _build()

    assert manifest["manifest_version"] == MANIFEST_VERSION
    assert manifest["profile"] == "dev"


def test_build_manifest_writes_resolution_not_config():
    manifest = _build()

    assert manifest["models"]["dig"] == {
        "role": "powerful",
        "model": "claude-opus-5",
        "source": "role_default",
    }


def test_build_manifest_confesses_judge_equals_scout():
    """E3 를 매니페스트가 자백한다.

    judge 와 scout 이 둘 다 `None` 이라 같은 역할로 해석되는 것이 E3
    (로드맵 §6 ①)이고 지금도 깨져 있다. 관측이지 강제가 아니다 --
    모델을 바꾸면 이전 표본과 비교 불가해진다.
    """
    assert _build()["judge_equals_scout"] is True


def test_build_manifest_reports_distinct_judge_and_scout():
    models = dict(_MODELS)
    models["judge"] = _resolution("claude-opus-5", "powerful")

    assert _build(models=models)["judge_equals_scout"] is False


def test_build_manifest_carries_budget_values_unchanged():
    assert _build()["budget"] == _BUDGET


def test_skills_none_is_not_empty_list():
    """0 과 '계측 없음' 을 구별한다 (F1-m1 의 교훈).

    레지스트리가 없는 것과 레지스트리에 스킬이 0개인 것은 다른 사실이다.
    """
    assert _build(skills=None)["skills"] is None
    assert _build(skills=[])["skills"] == []


def test_run_prompts_matches_every_render_call_site_under_the_harness():
    """FIX 4: 하드코딩된 리터럴이 아니라 소스를 스캔해 독립적으로 유도한다.

    이전 버전은 `set(RUN_PROMPTS) == {...하드코딩된 8개...}` 였다 -- 이건
    상수를 잘못 옮겨 적는 실수는 잡지만, 진짜 위험한 실패는 못 잡는다:
    누군가 아홉 번째 런 경로 프롬프트를 추가하고 `RUN_PROMPTS`에 넣는 것을
    잊으면, 하드코딩된 리터럴도 똑같이 8개인 채로 남아 테스트가 계속
    통과한다. 그러면 매니페스트는 조용히 그 프롬프트를 놓친다.

    대신 `neos/workflow/deep_analysis/` 전체에서 `render("<name>", ...)`
    호출부(줄바꿈 포함)를 스캔해 이름 집합을 독립적으로 유도하고
    `RUN_PROMPTS`와 대조한다. `render(` 정의 자체(`prompt_loader.py`)나
    `citation_renderer.render(draft)` 같은 무관한 메서드 호출은 다음 토큰이
    문자열 리터럴이 아니라서 매치되지 않는다.
    """
    harness_root = Path(__file__).resolve().parents[3] / "neos" / "workflow" / "deep_analysis"
    call_site_pattern = re.compile(r'render\(\s*"([a-z_]+)"')

    found: set[str] = set()
    for path in harness_root.rglob("*.py"):
        found |= set(call_site_pattern.findall(path.read_text()))

    assert found, "스캔이 호출부를 하나도 못 찾았다 -- 패턴이 깨졌다"
    # `diagnose_bottleneck`은 F1 진단자(표본을 *읽는* 쪽) 전용이고
    # `scripts/deep_analysis_diagnostician.py`만 로드한다 -- 하네스 트리
    # 밖이라 스캔에 잡히지 않는다. 넣으면 그 무관한 파일을 고칠 때마다
    # 실제로 동일한 두 런이 서로 달라 보이므로 일부러 뺀다.
    assert "diagnose_bottleneck" not in found
    assert set(RUN_PROMPTS) == found


def test_prompt_hashes_covers_every_run_prompt():
    hashes = prompt_hashes()

    assert set(hashes) == set(RUN_PROMPTS)
    assert all(value.startswith("sha256:") for value in hashes.values())


def test_prompt_hashes_returned_mapping_rejects_mutation():
    """`lru_cache` 는 매 호출에 같은 객체를 돌려준다.

    가변 dict 였다면 한 호출자의 변형이 프로세스의 나머지 전부를
    감지 불가능하게 오염시킨다.
    """
    hashes = prompt_hashes()

    with pytest.raises(TypeError):
        hashes["decompose"] = "sha256:tampered"


def test_component_id_strips_the_harness_package_prefix():
    from neos.workflow.deep_analysis.graders.deterministic import (
        DeterministicGrader,
    )

    # `quote_threshold`/`confidence_cap` 은 필수 키워드다
    # (`graders/deterministic.py:10-16`). `component_id` 는 인스턴스의
    # 타입만 보므로 값은 무엇이든 무방하다.
    grader = DeterministicGrader(
        None, quote_threshold=0.9, confidence_cap={}
    )

    assert component_id(grader) == "graders.deterministic:DeterministicGrader"
    assert component_id(None) is None


def test_manifest_kind_fits_the_event_column():
    """`DAEvent.kind` 는 String(40) 이다 -- 마이그레이션 없이 들어가야 한다."""
    assert len(MANIFEST_KIND) <= 40
