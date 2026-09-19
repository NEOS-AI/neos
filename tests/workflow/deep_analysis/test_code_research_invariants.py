"""J1 불변식을 구현보다 먼저 고정한다 (계약 §1).

계약이 "불변식 — 구현 전에 테스트로 먼저 고정한다" 라고 적은 이유는 J 가 여는
것이 **샌드박스에서 임의 코드를 돌리는 워커**이기 때문이다. 경계를 나중에
테스트로 덮으면, 덮는 시점에는 이미 그 경계를 넘는 코드가 있다.

여기 있는 것은 I3·I7 과 §7 설정 기본값이다. I1(바이트 동일)·I2(원장 미주입)·
I4~I6 은 각각 대상 코드가 생기는 단계에서 같은 자리에 붙인다.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.no_db


def test_research_offline_profile_denies_all_network() -> None:
    """I3. 프로파일은 B2 와 **같은** named profile 체계에 등록된다.

    DA 전용 샌드박스 경로를 따로 만들지 않는다(계약 §3.2). 그러므로 이
    테스트는 `neos.coding.sandbox.managed.profiles` 를 본다 — 여기에 없다면
    DA 가 자기 경로를 팠다는 뜻이다.
    """
    from neos.coding.sandbox.managed.profiles import (
        DENY_ALL,
        PROFILES,
        get_profile,
    )

    profile = get_profile("research-offline-v1")

    assert profile.network == DENY_ALL
    assert PROFILES["research-offline-v1"] is profile


def test_the_profile_registry_stays_immutable() -> None:
    """등록이 늘어도 레지스트리는 런타임에 고쳐지지 않는다."""
    from neos.coding.sandbox.managed.profiles import PROFILES, get_profile

    with pytest.raises(TypeError):
        PROFILES["research-offline-v1"] = get_profile("offline-v1")  # type: ignore[index]


def test_code_research_is_off_by_default() -> None:
    """§7. 전부 기본 off·보수값. 켜는 것은 표본 경계다."""
    from neos.config.schema import AppConfig

    code_research = AppConfig().deep_analysis.code_research

    assert AppConfig().deep_analysis.code_research_enabled is False
    # analyze·compose 는 표본 경계마다 하나씩 연다(§8).
    assert code_research.specs_enabled == ["research"]
    assert code_research.sandbox_profile == "research-offline-v1"


def _config(**overrides):
    """`tests/config/test_coding_model_config.py` 의 `real_config` 와 같은 모양."""
    data = {
        "environment": "development",
        "deep_analysis": {"code_research_enabled": True},
    }
    data.update(overrides)
    return data


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_enabling_outside_development_without_the_managed_plane_is_refused(
    environment,
) -> None:
    """I7. development 밖에서 켜려면 B2 게이트가 필요하다.

    설정에 `b2` 라는 값은 없다. 게이트를 **관리형 평면**으로 읽는다:
    provider 가 managed 이고 그 평면이 켜져 있어야 한다. 계약 §4.5 의
    "Docker 를 production 경계로 쓰지 않는다" 와 같은 방향이고, 이미 있는
    "production + docker 거절" 검증과 같은 자리다.
    """
    from pydantic import ValidationError

    from neos.config.schema import AppConfig

    with pytest.raises(ValidationError) as raised:
        AppConfig.model_validate(_config(environment=environment))

    message = str(raised.value)
    # 이 문구는 **이 검증만** 낼 수 있다. 그냥 `match="code_research"` 로 두면
    # 필드가 없을 때 pydantic 이 내는 `extra_forbidden` 의 필드 경로에도 그
    # 문자열이 있어서, 게이트를 구현하지 않아도 초록이 된다(K2b 에서 같은
    # 모양으로 한 번 속았다).
    assert "code research outside development" in message
    assert "extra_forbidden" not in message


def test_enabling_outside_development_is_allowed_on_the_managed_plane() -> None:
    """게이트는 양방향이다 — 막기만 하고 통과시키지 못하면 확인된 게 아니다.

    관리형 평면을 켜면 봉인 키 둘이 따라온다(참조 키·소유권 키, 서로 달라야
    한다). 여기서 그걸 채우는 이유는 J 가 요구해서가 아니라, 이 테스트가
    **게이트 때문에** 통과하는지 확인하려면 다른 이유로 거절당하지 않아야
    하기 때문이다.
    """
    import base64

    from neos.config.schema import AppConfig

    config = AppConfig.model_validate(
        _config(
            environment="staging",
            sandbox={"provider": "managed", "managed": {"enabled": True}},
            secrets={
                "managed_provider_reference_key": base64.b64encode(
                    bytes(32)
                ).decode("ascii"),
                "managed_coding_ownership_key": base64.b64encode(
                    b"\x01" * 32
                ).decode("ascii"),
            },
        )
    )

    assert config.deep_analysis.code_research_enabled is True


def test_code_research_on_docker_requires_no_network() -> None:
    """I3 을 development 경로에서 **실제로** 강제한다.

    프로파일은 레지스트리에서 `DENY_ALL` 이지만, Docker provider 는
    `profile` 이라는 단어를 모른다(확인함 — `docker.py` 에 한 번도 나오지
    않는다). 그 경로의 격리는 오로지 `sandbox.docker.network_mode` 에서 오고,
    그 필드는 제약 없는 문자열이다. 그래서 둘을 여기서 묶는다 -- 묶지 않으면
    프로파일이 "네트워크 없음" 이라고 적혀 있는 채로 컨테이너에는 네트워크가
    붙는다. 낡은 면제 플래그가 가드를 조용히 끄는 것과 같은 모양이다.
    """
    from pydantic import ValidationError

    from neos.config.schema import AppConfig

    with pytest.raises(ValidationError) as raised:
        AppConfig.model_validate(
            _config(sandbox={"provider": "docker", "docker": {"network_mode": "bridge"}})
        )

    message = str(raised.value)
    assert "network_mode" in message
    assert "extra_forbidden" not in message


def test_code_research_on_docker_with_no_network_is_accepted() -> None:
    """가드는 양방향이다."""
    from neos.config.schema import AppConfig

    config = AppConfig.model_validate(
        _config(sandbox={"provider": "docker", "docker": {"network_mode": "none"}})
    )

    assert config.deep_analysis.code_research_enabled is True


def test_enabling_in_development_needs_no_managed_plane() -> None:
    """development 는 Docker(`network=none`)로 충분하다(로드맵 §4.5)."""
    from neos.config.schema import AppConfig

    config = AppConfig.model_validate(_config())

    assert config.deep_analysis.code_research_enabled is True
