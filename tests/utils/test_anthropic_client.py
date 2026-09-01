"""Anthropic 클라이언트를 한 곳에서 짓는다 -- 그리고 워크스페이스를 싣는다.

identity-linked API 키는 `anthropic-workspace-id` 헤더 없이는 **모든 요청이
400** 이다. 그 헤더를 안 보내던 시절 저장소에는 `AsyncAnthropic(...)` 생성
지점이 아홉 곳 있었고, 아홉 곳을 각자 고치는 것이 이 저장소가 CA12 로 이미
추적 중인 드리프트다.

여기서 고정하는 것은 둘이다: 워크스페이스가 **없을 때 지금과 완전히 같을 것**,
있을 때 **API 가 이름 붙인 그 헤더**로 갈 것.
"""

from types import SimpleNamespace

import pytest

import neos.utils.anthropic_client as ac


pytestmark = pytest.mark.no_db


HEADER = "anthropic-workspace-id"


def test_no_workspace_id_sends_no_extra_header():
    """설정이 비면 헤더를 만들지 않는다.

    빈 문자열 헤더를 보내는 것과 안 보내는 것은 다르다 -- 전자는 identity 가
    아닌 키에 대해 새 실패를 만든다. 이 변경이 기존 배포에 무해하다는 주장이
    전부 이 단언 위에 서 있다.
    """
    assert ac.anthropic_default_headers(workspace_id=None) == {}
    assert ac.anthropic_default_headers(workspace_id="") == {}
    assert ac.anthropic_default_headers(workspace_id="   ") == {}


def test_workspace_id_uses_the_header_name_the_api_names():
    """이름을 틀리면 조용히 무시되고 400 은 그대로다.

    API 가 오류 문구에서 부른 이름을 그대로 쓴다 -- 추측하지 않는다.
    """
    assert ac.anthropic_default_headers(workspace_id="wrkspc_x") == {
        HEADER: "wrkspc_x"
    }


def test_the_workspace_id_is_trimmed():
    """`.env` 에서 온 값은 공백을 달고 오기 쉽다."""
    assert ac.anthropic_default_headers(workspace_id=" wrkspc_x\n") == {
        HEADER: "wrkspc_x"
    }


def test_the_workspace_id_falls_back_to_settings(monkeypatch):
    monkeypatch.setattr(
        ac,
        "settings",
        SimpleNamespace(
            ANTHROPIC_API_KEY="sk-ant-fake",
            ANTHROPIC_WORKSPACE_ID="wrkspc_from_settings",
        ),
    )

    assert ac.anthropic_default_headers() == {HEADER: "wrkspc_from_settings"}


def test_a_missing_settings_attribute_is_not_an_error(monkeypatch):
    """설정에 그 이름이 아예 없어도 죽지 않는다.

    `Settings.__getattr__` 는 모르는 이름에 `AttributeError` 를 낸다. 클라이언트
    생성이 그것으로 죽으면 워크스페이스를 안 쓰는 배포가 이 변경 하나로
    통째로 멈춘다.
    """
    monkeypatch.setattr(ac, "settings", SimpleNamespace())

    assert ac.anthropic_default_headers() == {}


def test_caller_headers_are_kept_and_the_workspace_is_added(monkeypatch):
    """호출자가 이미 헤더를 갖고 있으면 지우지 않는다."""
    monkeypatch.setattr(ac, "settings", SimpleNamespace())

    merged = ac.anthropic_default_headers(
        workspace_id="wrkspc_x", extra={"x-trace": "abc"}
    )

    assert merged == {HEADER: "wrkspc_x", "x-trace": "abc"}


class _FakeAsyncAnthropic:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


def test_build_omits_default_headers_entirely_when_there_is_no_workspace(
    monkeypatch,
):
    """빈 dict 도 넘기지 않는다 -- 넘기면 SDK 기본값을 덮을 위험이 남는다."""
    monkeypatch.setattr(ac, "AsyncAnthropic", _FakeAsyncAnthropic)
    monkeypatch.setattr(
        ac, "settings", SimpleNamespace(ANTHROPIC_API_KEY="sk-ant-fake")
    )

    client = ac.build_async_anthropic()

    assert client.kwargs == {"api_key": "sk-ant-fake"}


def test_build_passes_the_workspace_header_through(monkeypatch):
    monkeypatch.setattr(ac, "AsyncAnthropic", _FakeAsyncAnthropic)
    monkeypatch.setattr(
        ac,
        "settings",
        SimpleNamespace(
            ANTHROPIC_API_KEY="sk-ant-fake", ANTHROPIC_WORKSPACE_ID="wrkspc_x"
        ),
    )

    client = ac.build_async_anthropic()

    assert client.kwargs["api_key"] == "sk-ant-fake"
    assert client.kwargs["default_headers"] == {HEADER: "wrkspc_x"}


def test_an_explicit_api_key_wins_over_settings(monkeypatch):
    """`neos/coding/runtime.py` 는 자기 시크릿 원천에서 키를 가져온다.

    관리형 샌드박스는 런마다 다른 키를 쓸 수 있으므로 팩토리가 전역 설정을
    강제하면 그 경로가 조용히 틀린 키로 돈다.
    """
    monkeypatch.setattr(ac, "AsyncAnthropic", _FakeAsyncAnthropic)
    monkeypatch.setattr(
        ac,
        "settings",
        SimpleNamespace(
            ANTHROPIC_API_KEY="sk-ant-global", ANTHROPIC_WORKSPACE_ID="wrkspc_x"
        ),
    )

    client = ac.build_async_anthropic(api_key="sk-ant-caller")

    assert client.kwargs["api_key"] == "sk-ant-caller"
    # 워크스페이스는 계정 사실이라 키를 바꿔도 따라온다.
    assert client.kwargs["default_headers"] == {HEADER: "wrkspc_x"}


def test_no_module_builds_its_own_anthropic_client():
    """팩토리를 우회하는 열 번째 사본이 생기면 여기서 빨개진다.

    이 항목이 존재하는 이유가 사본이 아홉 개였다는 것이다. 헤더 하나를 아홉
    곳에 적는 것은 §7 CA12 가 추적 중인 드리프트와 같은 모양이고, 그 드리프트는
    **다음 사본이 조용히 추가되기 때문에** 자란다.
    """
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[2] / "neos"
    factory = root / "utils" / "anthropic_client.py"

    offenders = [
        str(path.relative_to(root))
        for path in root.rglob("*.py")
        if path != factory and "AsyncAnthropic(" in path.read_text(encoding="utf-8")
    ]

    assert offenders == [], (
        "이 파일들이 클라이언트를 직접 짓는다 -- "
        "`build_async_anthropic()` 를 쓸 것: " + ", ".join(offenders)
    )
