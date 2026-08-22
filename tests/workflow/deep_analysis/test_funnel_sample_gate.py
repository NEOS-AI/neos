"""표본 경계 매니페스트 게이트 -- 로드맵 §15.4 금지 3번.

매니페스트 없는 런은 표본이 아니다. 지침이 아니라 기계가 거부한다.

이 파일은 Task 7 브리프의 컨트롤러 스코프 서브셋이다 (R2 재정) --
`divergent_manifest_fields` 는 여기서 구현하지 않고, 그 다섯 개 테스트도
쓰지 않는다. 4개만 쓴다: 게이트가 존재하고, 순서가 맞고, 거부·통과 양쪽이
실제로 동작한다는 것.
"""

import inspect

import pytest

import scripts.deep_analysis_funnel_sample as sample
from scripts.deep_analysis_funnel_sample import MissingManifestError


def _async_return(value):
    async def _fn(*_args, **_kwargs):
        return value

    return _fn


def test_missing_manifest_error_names_the_runs():
    error = MissingManifestError(["r7", "r9"])

    assert "r7" in str(error) and "r9" in str(error)


@pytest.mark.asyncio
async def test_gate_raises_before_reading_manifests(monkeypatch):
    """매니페스트 없는 런이 하나라도 있으면 거부한다.

    로드맵 §15.4 금지 3번은 지침이 아니라 기계다. 아티팩트가 써지고 나면
    §10.2 의 "정확히 1회" 규칙 때문에 다시 낼 기회가 없다.

    `manifests_for` 가 불리지 않았다는 것까지 단언한다 -- 게이트가 통과
    경로와 섞이면 "거부했는데 아티팩트는 써졌다" 가 가능해진다.
    """
    read = []

    async def _spy_manifests_for(*_args, **_kwargs):
        read.append("called")
        return {}

    monkeypatch.setattr(sample, "runs_without_manifest", _async_return(["r2"]))
    monkeypatch.setattr(sample, "manifests_for", _spy_manifests_for)

    with pytest.raises(MissingManifestError) as caught:
        await sample._gate_and_read_manifests(object(), ["r1", "r2"])

    assert caught.value.run_ids == ["r2"]
    assert read == []


def test_gate_is_called_before_write_artifacts_in_main():
    """소스 순서로 확인한다 -- 게이트가 아티팩트 쓰기보다 앞이어야 한다.

    함수 단위 테스트는 게이트가 *존재* 함만 보인다. 그것이 `_main()` 의
    성공 경로에서 `write_artifacts` 앞에 있는지는 별개 사실이고,
    순서가 뒤집히면 거부해도 아티팩트는 이미 써진다.
    """
    source = inspect.getsource(sample._main)
    gate = source.index("_gate_and_read_manifests")
    write = source.index("write_artifacts(\n            result")

    assert gate < write


@pytest.mark.asyncio
async def test_gate_returns_manifests_when_every_run_has_one(monkeypatch):
    monkeypatch.setattr(sample, "runs_without_manifest", _async_return([]))
    monkeypatch.setattr(sample, "manifests_for", _async_return({"r1": {"profile": "dev"}}))

    found = await sample._gate_and_read_manifests(object(), ["r1"])

    assert found == {"r1": {"profile": "dev"}}
