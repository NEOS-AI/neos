from pathlib import Path

import pytest

from neos.config.model_routing import ResolutionSource
from neos.config.settings import settings
from neos.workflow.deep_analysis.model_roles import (
    HARNESS_ROLES,
    resolve_all,
    resolve_harness_model,
)

_HARNESS_DIR = (
    Path(__file__).resolve().parents[3]
    / "neos" / "workflow" / "deep_analysis"
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


def test_resolve_harness_model_consumes_feature_override(monkeypatch):
    """오늘은 `deep_analysis.models.*` 가 전부 `None` 이라 기존 테스트로는
    override 배선이 실제로 동작하는지, 그냥 무시하는지 구별할 수 없다.
    """
    sentinel = "sentinel-override-model-xyz"
    monkeypatch.setattr(
        settings.config.deep_analysis.models, "judge", sentinel, raising=False
    )

    resolution = resolve_harness_model("judge")

    assert resolution.model == sentinel
    assert resolution.source is ResolutionSource.FEATURE_OVERRIDE


def test_no_direct_resolve_model_call_in_harness():
    """`model_roles.py` 밖에서 `resolve_model` 을 직접 부르지 않는다.

    사본이 다시 생기는 것을 기계가 막는다. 이 테스트가 없으면 다음 사람이
    호출 지점 하나를 추가하면서 역할을 손으로 적고, 매니페스트는 그것을
    모른 채 다른 값을 적는다.
    """
    offenders = []
    for path in sorted(_HARNESS_DIR.rglob("*.py")):
        if path.name == "model_roles.py":
            continue
        source = path.read_text(encoding="utf-8")
        if "resolve_model(" in source:
            offenders.append(str(path.relative_to(_HARNESS_DIR)))

    assert offenders == []
