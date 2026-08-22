import pytest

from neos.workflow.deep_analysis.model_roles import (
    HARNESS_ROLES,
    resolve_all,
    resolve_harness_model,
)


def test_role_table_matches_pre_migration_call_sites():
    """이전 전 9개 호출 지점의 역할을 회귀 고정한다.

    worker.py:316 (scout=everyday / dig=powerful) ·
    synthesizer.py:272,328,496,627 (synth=powerful) ·
    orchestrator.py:706,730 (dig=powerful) · orchestrator.py:903 (judge=everyday) ·
    service.py:61 (judge=everyday).

    이 단언이 없으면 Task 2 의 이전이 역할을 조용히 바꿔도 아무것도 실패하지
    않는다 -- 그리고 그 거짓말은 재생성 불가능한 아티팩트에 실린다.
    """
    assert HARNESS_ROLES == {
        "scout": "everyday",
        "dig": "powerful",
        "synth": "powerful",
        "judge": "everyday",
    }


def test_resolve_harness_model_returns_resolution_with_role():
    resolution = resolve_harness_model("dig")

    assert resolution.role == "powerful"
    assert resolution.provider == "anthropic"
    assert isinstance(resolution.model, str) and resolution.model


def test_resolve_harness_model_rejects_unknown_name():
    with pytest.raises(KeyError):
        resolve_harness_model("scribe")


def test_resolve_all_covers_every_role():
    resolved = resolve_all()

    assert set(resolved) == set(HARNESS_ROLES)
