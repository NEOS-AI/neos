from __future__ import annotations

import pytest

from neos.coding.model.base import ModelCompleted, ModelUsage, TextDelta
from neos.coding.model.errors import CodingModelError
from neos.subagent.catalog import (
    FSI_CRITIC,
    FSI_MODELER,
    FSI_PULLER,
    FSI_READER,
    FSI_WRITER,
    SpecRegistry,
    UnknownSpec,
    lookup_spec,
    may_spawn,
)
from neos.subagent.memory import InMemorySubagentStore
from neos.subagent.metrics import record_subagent_event
from neos.subagent.ports import SystemClock
from neos.subagent.prompts import build_explore_system_prompt, build_fsi_system_prompt
from neos.subagent.runtime import SubagentRuntime
from neos.subagent.stepper import ChildStepper
from neos.subagent.types import (
    ModelPin,
    ParentBriefing,
    ParentKind,
    SandboxMode,
    SubagentTicket,
)

pytestmark = pytest.mark.no_db

_FSI_NAMES = (
    "fsi-reader",
    "fsi-writer",
    "fsi-critic",
    "fsi-puller",
    "fsi-modeler",
)
_CONTROL = frozenset({"spawn_agent.v1", "handoff.v1"})
_FSI_CONSTANTS = {
    "fsi-reader": FSI_READER,
    "fsi-writer": FSI_WRITER,
    "fsi-critic": FSI_CRITIC,
    "fsi-puller": FSI_PULLER,
    "fsi-modeler": FSI_MODELER,
}


def test_fsi_kebab_names_are_registered() -> None:
    for name in _FSI_NAMES:
        spec = lookup_spec(name)
        assert spec.name == name
        assert spec is _FSI_CONSTANTS[name]
        assert spec.sandbox_mode is SandboxMode.NONE
        assert spec.can_spawn is False
        assert spec.can_approve is False
        assert spec.one_shot is True
        assert spec.load_project_instructions is False
        assert spec.allowed_tools.isdisjoint(_CONTROL)
        assert may_spawn(spec, 0) is False
        assert not hasattr(spec, "output_schema")


def test_underscore_fsi_reader_is_unknown() -> None:
    with pytest.raises(UnknownSpec) as raised:
        lookup_spec("fsi_reader")
    assert raised.value.name == "fsi_reader"


def test_only_writer_has_write_file() -> None:
    assert "write_file.v1" in lookup_spec("fsi-writer").allowed_tools
    for name in ("fsi-reader", "fsi-critic", "fsi-puller", "fsi-modeler"):
        assert "write_file.v1" not in lookup_spec(name).allowed_tools


def test_only_modeler_template_has_execute() -> None:
    assert "execute.v1" in lookup_spec("fsi-modeler").allowed_tools
    for name in ("fsi-reader", "fsi-writer", "fsi-critic", "fsi-puller"):
        assert "execute.v1" not in lookup_spec(name).allowed_tools


def test_fsi_allowed_tools_match_templates() -> None:
    assert lookup_spec("fsi-reader").allowed_tools == frozenset(
        {"read_file.v1", "search_text.v1"}
    )
    assert lookup_spec("fsi-writer").allowed_tools == frozenset(
        {"read_file.v1", "write_file.v1", "edit_file.v1", "load_skill.v1"}
    )
    assert lookup_spec("fsi-critic").allowed_tools == frozenset(
        {"read_file.v1", "search_text.v1"}
    )
    assert lookup_spec("fsi-puller").allowed_tools == frozenset(
        {"read_file.v1", "search_text.v1"}
    )
    assert lookup_spec("fsi-modeler").allowed_tools == frozenset(
        {"read_file.v1", "search_text.v1", "execute.v1"}
    )


def test_fsi_prompt_forbids_spawn() -> None:
    prompt = build_fsi_system_prompt()
    lowered = prompt.lower()
    assert "do not spawn" in lowered
    assert "report only" in lowered
    assert "untrusted" in lowered
    assert "spawn_agent" not in lowered
    assert "you may call spawn_agent" not in build_fsi_system_prompt()
    assert "you may call spawn_agent" in build_explore_system_prompt().lower()


class ScriptedCodingModel:
    def __init__(self, script) -> None:
        self.script = [tuple(turn) for turn in script]
        self.requests = []

    async def stream(self, request):
        self.requests.append(request)
        if not self.script:
            raise CodingModelError("model_script_exhausted", retryable=False)
        for event in self.script.pop(0):
            yield event


class FakeToolPort:
    def __init__(self, names=None, results=None) -> None:
        self._names = tuple(names or ("read_file.v1", "search_text.v1", "execute.v1"))
        self.results = results or {}
        self.calls: list[tuple[str, dict]] = []

    def definitions(self):
        return self._names

    async def execute(self, name: str, input):
        self.calls.append((name, dict(input)))
        if name in self.results:
            return self.results[name]
        return {"ok": True, "path": input.get("path", name)}


class RecordingSink:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    async def emit(self, event_type: str, payload) -> None:
        self.events.append((event_type, dict(payload)))


def _ticket(**overrides) -> SubagentTicket:
    payload = {
        "parent_kind": ParentKind.CODING,
        "parent_id": "ct_parent",
        "parent_run_id": "cr_parent",
        "parent_tool_call_id": "toolu_spawn",
        "spec": "explore",
        "briefing": ParentBriefing(goal="Find the login handler", success="Name it"),
        "model": ModelPin(provider="anthropic", model="claude-test"),
    }
    payload.update(overrides)
    return SubagentTicket(**payload)


def _runtime(script, *, tools=None):
    store = InMemorySubagentStore()
    tools = tools or FakeToolPort()
    model = ScriptedCodingModel(script)
    events = RecordingSink()
    runtime = SubagentRuntime(
        store=store,
        catalog=SpecRegistry(),
        stepper=ChildStepper(model=model, tools=tools),
        events=events,
        clock=SystemClock(),
    )
    return runtime, store, tools, model, events


def _text(text: str = "report"):
    return (TextDelta(text), ModelCompleted("end_turn", ModelUsage(3, 2)))


@pytest.mark.asyncio
async def test_fsi_reader_advance_uses_fsi_prompt_not_explore() -> None:
    runtime, _store, _tools, model, _events = _runtime([_text("packet extracted")])
    await runtime.advance(
        _ticket(spec="fsi-reader", parent_kind=ParentKind.FSI)
    )
    assert model.requests[0].system == build_fsi_system_prompt()
    assert "spawn_agent" not in model.requests[0].system
    assert "spawn_agent.v1" not in model.requests[0].system
    assert "you may call spawn_agent" not in model.requests[0].system.lower()


@pytest.mark.asyncio
async def test_explore_advance_still_uses_explore_prompt() -> None:
    runtime, _store, _tools, model, _events = _runtime([_text("handler is login.py")])
    await runtime.advance(_ticket())
    assert model.requests[0].system == build_explore_system_prompt()
    assert "you may call spawn_agent" in model.requests[0].system.lower()


class _Counter:
    def __init__(self) -> None:
        self.labels_seen: list[dict] = []

    def labels(self, **labels):
        self.labels_seen.append(labels)
        return self

    def inc(self, *_args) -> None:
        return None


class _AdvanceMetrics:
    def __init__(self) -> None:
        self.subagent_advance_total = _Counter()


def test_metrics_keep_fsi_reader_spec_label() -> None:
    metrics = _AdvanceMetrics()
    record_subagent_event(
        metrics,
        "subagent.step",
        {"spec": "fsi-reader", "parent_kind": "fsi", "step_kind": "completed"},
    )
    assert any(
        labels.get("spec") == "fsi-reader"
        for labels in metrics.subagent_advance_total.labels_seen
    )


@pytest.mark.parametrize("name", _FSI_NAMES)
def test_metrics_keep_every_fsi_kebab_spec_label(name: str) -> None:
    metrics = _AdvanceMetrics()
    record_subagent_event(
        metrics,
        "subagent.step",
        {"spec": name, "parent_kind": "fsi", "step_kind": "completed"},
    )
    assert any(
        labels.get("spec") == name
        for labels in metrics.subagent_advance_total.labels_seen
    )
