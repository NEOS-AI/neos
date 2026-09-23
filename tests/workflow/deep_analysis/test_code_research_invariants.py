"""J1 불변식을 구현보다 먼저 고정한다 (계약 §1).

계약이 "불변식 — 구현 전에 테스트로 먼저 고정한다" 라고 적은 이유는 J 가 여는
것이 **샌드박스에서 임의 코드를 돌리는 워커**이기 때문이다. 경계를 나중에
테스트로 덮으면, 덮는 시점에는 이미 그 경계를 넘는 코드가 있다.

여기 있는 것은 I3·I7 과 §7 설정 기본값, 그리고 **I1·I2** 다. I1·I2 는 대상
코드(`research_tools.py` · `submission.py`)가 생긴 2026-09-20 에 붙였다.
I4~I6 은 각각 대상 코드가 생기는 단계에서 같은 자리에 붙인다.

I1 을 **분기보다 먼저** 쓴 이유는 위 문단 그대로다. `_run_worker` 에
`code_research_enabled` 분기를 넣은 **뒤에** 이 테스트를 쓰면, 쓰는 시점에는
이미 플래그 off 경로를 바꿨는지 알 수 없다.
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
                "managed_provider_reference_key": base64.b64encode(bytes(32)).decode(
                    "ascii"
                ),
                "managed_coding_ownership_key": base64.b64encode(b"\x01" * 32).decode(
                    "ascii"
                ),
            },
        )
    )

    assert config.deep_analysis.code_research_enabled is True


def test_code_research_on_docker_requires_no_network() -> None:
    """I3 을 development 경로에서 **실제로** 강제한다.

    프로파일은 레지스트리에서 `DENY_ALL` 이다. 이 테스트를 처음 쓸 때는
    "Docker provider 는 `profile` 을 모르므로 묶지 않으면 컨테이너에 네트워크가
    붙는다" 고 적었다. 앞 절반은 2026-09-23 에 **거짓이 되었고**(Docker
    provider 가 profile 을 스스로 강제한다, `test_docker_profile_evidence.py`),
    뒤 절반은 **처음부터 거짓이었다** -- `build_create_args` 가 33064654
    (2026-07-19)부터 none 이 아닌 값을 거절했다.

    그래도 이 검증을 남긴다(심층 방어): 그 둘은 질문마다 create 시점에
    터지고, 이것은 기동 시점에 터진다.
    """
    from pydantic import ValidationError

    from neos.config.schema import AppConfig

    with pytest.raises(ValidationError) as raised:
        AppConfig.model_validate(
            _config(
                sandbox={"provider": "docker", "docker": {"network_mode": "bridge"}}
            )
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


# ---- I1: 플래그가 꺼져 있으면 이전과 바이트 단위로 같다 (S9) -----------------


def _repo_file(relative: str) -> str:
    import pathlib

    return (pathlib.Path(__file__).resolve().parents[3] / relative).read_text(
        encoding="utf-8"
    )


def test_flag_off_worker_tools_are_exactly_search_and_fetch() -> None:
    """I1 (도구 목록). 플래그 off 경로의 포트는 `DAToolPort` 하나다.

    `ResearchToolPort` 가 기본 경로로 새면 워커의 도구 목록이 플래그와 무관
    하게 달라진다. 이름을 **정확히** 대조하는 이유는 개수만 보면 하나가
    바뀌어도 통과하기 때문이다.
    """
    from neos.workflow.deep_analysis.subagent_adapter import DAToolPort

    async def _unused(*args, **kwargs):
        return []

    port = DAToolPort(_unused, _unused)

    assert tuple(item.name for item in port.definitions()) == ("search", "fetch")


def test_flag_off_worker_prompt_never_names_the_code_research_tools() -> None:
    """I1 (프롬프트). 기존 워커 프롬프트는 J 도구를 모른다.

    프롬프트 전체를 해시로 고정하지 않는 이유: 프롬프트 수정은 표본 경계에서
    **정상적으로** 일어나는 일이라 해시는 J 와 무관한 커밋마다 빨개진다.
    여기서 지키려는 것은 "프롬프트가 안 변한다" 가 아니라 "플래그 off 인데
    J 도구가 이름을 내민다" 가 없다는 것이다.
    """
    prompt = _repo_file("neos/workflow/deep_analysis/prompts/worker_brief.md")

    # 먼저 이 파일을 **정말로 읽었는지** 본다. "없다" 를 단언하는 테스트는 빈
    # 문자열에도 통과한다 -- 경로가 틀리면 `_repo_file` 이 터지지만, 프롬프트가
    # 다른 곳으로 옮겨가고 껍데기만 남으면 조용히 초록이 된다.
    assert "proposed_subquestions" in prompt

    for name in ("fetch.v1", "submit.v1", "check_claims.v1", "execute.v1"):
        assert name not in prompt


# ---- I2: 워커는 원장 쓰기 경로를 갖지 않는다 --------------------------------


#: 워커의 도구가 지나는 모듈. 원장이 여기로 들어오면 자식이 원장을 쓸 수 있고,
#: 그러면 단일 기록자(P2)가 깨진다.
_WORKER_FACING = (
    "neos/workflow/deep_analysis/research_tools.py",
    "neos/workflow/deep_analysis/submission.py",
)

_LEDGER_IMPORTS = (
    "from .ledger import",
    "from neos.workflow.deep_analysis.ledger import",
    "import neos.workflow.deep_analysis.ledger",
)


def _ledger_importers(relatives) -> list[str]:
    found: list[str] = []
    for relative in relatives:
        text = _repo_file(relative)
        for needle in _LEDGER_IMPORTS:
            if needle in text:
                found.append(f"{relative}: {needle}")
    return found


def test_worker_facing_modules_do_not_import_the_ledger() -> None:
    """I2 (import 쪽). `tests/subagent/test_import_law.py` 와 같은 규율이다."""
    assert _ledger_importers(_WORKER_FACING) == []


def test_the_ledger_detector_would_actually_catch_an_import() -> None:
    """가드는 양방향이다 -- 잡지 못하는 검출기는 초록이어도 아무 말을 안 한다.

    위 테스트는 **찾지 못할 문자열을 찾는** 모양이라, 검출기가 고장 나도
    영원히 초록이다. 그래서 원장을 실제로 쓰는 층에 같은 검출기를 겨눠
    걸리는 것을 본다. `orchestrator.py` 가 원장을 임포트하지 않게 되는 날이
    오면 이 테스트가 빨개지고, 그때는 위 목록이 아니라 이 앵커를 고친다.
    """
    caught = _ledger_importers(("neos/workflow/deep_analysis/orchestrator.py",))

    assert caught != []


def test_the_research_port_is_not_given_a_ledger() -> None:
    """I2 (주입 쪽). 포트는 `EvidenceStore` 프로토콜만 받는다.

    집합을 **정확히** 대조한다: 인자가 하나 늘면 그것이 원장으로 가는 문인지
    여기서 한 번 생각하게 된다.
    """
    import inspect

    from neos.workflow.deep_analysis.research_tools import ResearchToolPort

    parameters = set(inspect.signature(ResearchToolPort.__init__).parameters)

    # `grader` 는 2026-09-20 에 `check_claims.v1` 과 함께 늘었고, 이 단언이
    # 빨개져서 한 번 멈춰 세웠다 -- 가드가 노린 그 순간이다. 채점기는 원장을
    # **읽기만** 한다(`deterministic.py` 의 유일한 원장 호출은 `get_blob`),
    # 그리고 포트는 채점기를 받지 원장을 받지 않는다.
    assert parameters == {
        "self",
        "fetch_fn",
        "store",
        "sandbox",
        "cap_bytes",
        "grader",
    }
