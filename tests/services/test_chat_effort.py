import pytest

from neos.config.model_routing import ResolutionSource
from neos.services import chat_effort

pytestmark = pytest.mark.no_db

MODEL = "claude-opus-5-5"


@pytest.fixture
def levels(monkeypatch):
    monkeypatch.setattr(chat_effort, "effort_levels_for", lambda m: ("low", "medium", "high"))


def _stub_db(monkeypatch, value=None, raises=False):
    calls = []

    async def get_effort_for_conversation(conversation_id, model_pin):
        calls.append((conversation_id, model_pin))
        if raises:
            raise RuntimeError("db down")
        return value

    monkeypatch.setattr(
        chat_effort.ModelPreferenceRepository,
        "get_effort_for_conversation",
        get_effort_for_conversation,
    )
    return calls


def _config(monkeypatch, models=None, everyday=None, powerful=None):
    effort = chat_effort.settings.config.model_routing.effort
    monkeypatch.setattr(effort, "models", models or {})
    monkeypatch.setattr(effort, "everyday", everyday)
    monkeypatch.setattr(effort, "powerful", powerful)


@pytest.mark.asyncio
async def test_the_user_preference_wins(monkeypatch, levels) -> None:
    _stub_db(monkeypatch, "low")
    _config(monkeypatch, models={MODEL: "high"})

    r = await chat_effort.resolve_chat_effort(MODEL, "c1")

    assert (r.effort, r.source) == ("low", ResolutionSource.USER)


@pytest.mark.asyncio
async def test_the_model_default_applies_without_a_preference(monkeypatch, levels) -> None:
    _stub_db(monkeypatch, None)
    _config(monkeypatch, models={MODEL: "high"}, everyday="low")

    r = await chat_effort.resolve_chat_effort(MODEL, "c1")

    assert (r.effort, r.source) == ("high", ResolutionSource.MODEL_DEFAULT)


@pytest.mark.asyncio
async def test_a_stale_stored_level_falls_through(monkeypatch, levels) -> None:
    """Review Focus 3: 저장 후 모델이 그 레벨을 잃어도 턴은 계속된다."""
    _stub_db(monkeypatch, "max")
    _config(monkeypatch, models={MODEL: "high"})

    r = await chat_effort.resolve_chat_effort(MODEL, "c1")

    assert r.effort == "high"
    assert r.source is ResolutionSource.MODEL_DEFAULT


@pytest.mark.asyncio
async def test_a_db_failure_does_not_fail_the_turn(monkeypatch, levels) -> None:
    _stub_db(monkeypatch, raises=True)
    _config(monkeypatch, models={MODEL: "medium"})

    r = await chat_effort.resolve_chat_effort(MODEL, "c1")

    assert r.effort == "medium"


@pytest.mark.asyncio
async def test_no_conversation_no_config_sends_nothing(monkeypatch, levels) -> None:
    _stub_db(monkeypatch, "high")
    _config(monkeypatch)

    r = await chat_effort.resolve_chat_effort(MODEL, None)

    assert r.effort is None


@pytest.mark.asyncio
async def test_a_model_without_levels_does_not_query(monkeypatch) -> None:
    """레벨 없는 모델에 대해 턴마다 쿼리를 치르지 않는다."""
    monkeypatch.setattr(chat_effort, "effort_levels_for", lambda m: ())
    calls = _stub_db(monkeypatch, "high")
    _config(monkeypatch)

    r = await chat_effort.resolve_chat_effort("gemini-1.5-pro-latest", "c1")

    assert calls == []
    assert r.effort is None


@pytest.mark.asyncio
async def test_the_source_is_counted(monkeypatch, levels) -> None:
    from neos.observability.metrics import get_metrics_collector

    _stub_db(monkeypatch, None)
    _config(monkeypatch, models={MODEL: "high"})
    counter = get_metrics_collector().chat_effort_resolved_total
    before = counter.labels(source="model_default")._value.get()

    await chat_effort.resolve_chat_effort(MODEL, "c1")

    assert counter.labels(source="model_default")._value.get() == before + 1
