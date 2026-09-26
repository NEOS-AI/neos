from __future__ import annotations

import pytest

from neos.coding.model.base import ModelCompleted, ModelUsage, TextDelta
from neos.coding.model.errors import CodingModelError
from neos.subagent.catalog import (
    UNIVER_CRITIC,
    UNIVER_FORMULA,
    UNIVER_READER,
    UNIVER_WRITER,
    SpecRegistry,
    UnknownSpec,
    lookup_spec,
    may_spawn,
)
from neos.subagent.memory import InMemorySubagentStore
from neos.subagent.ports import SystemClock
from neos.subagent.prompts import (
    build_explore_system_prompt,
    build_fsi_system_prompt,
    build_fsi_system_prompt_for,
    build_univer_system_prompt,
    build_univer_system_prompt_for,
)
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

_UNIVER_NAMES = (
    "univer-reader",
    "univer-writer",
    "univer-critic",
    "univer-formula",
)
_CONTROL = frozenset({"spawn_agent.v1", "handoff.v1", "execute.v1"})
_UNIVER_CONSTANTS = {
    "univer-reader": UNIVER_READER,
    "univer-writer": UNIVER_WRITER,
    "univer-critic": UNIVER_CRITIC,
    "univer-formula": UNIVER_FORMULA,
}
_READER_TOOLS = frozenset(
    {
        "univer.inspect.v1",
        "univer.range_get.v1",
        "read_file.v1",
        "search_text.v1",
    }
)
_FORMULA_TOOLS = _READER_TOOLS | frozenset({"univer.formula_wait.v1"})
_WRITER_TOOLS = frozenset(
    {
        "univer.inspect.v1",
        "univer.range_get.v1",
        "univer.range_set.v1",
        "univer.execute_command.v1",
        "univer.save.v1",
        "univer.formula_wait.v1",
        "read_file.v1",
        "write_file.v1",
        "load_skill.v1",
    }
)
_PORT_NAMES = tuple(
    {
        *_READER_TOOLS,
        *_FORMULA_TOOLS,
        *_WRITER_TOOLS,
        "execute.v1",
        "search_text.v1",
    }
)


def test_univer_kebab_names_are_registered() -> None:
    for name in _UNIVER_NAMES:
        spec = lookup_spec(name)
        assert spec.name == name
        assert spec is _UNIVER_CONSTANTS[name]
        assert spec.sandbox_mode is SandboxMode.NONE
        assert spec.can_spawn is False
        assert spec.can_approve is False
        assert spec.one_shot is True
        assert spec.load_project_instructions is False
        assert spec.allowed_tools.isdisjoint(_CONTROL)
        assert may_spawn(spec, 0) is False
        assert not hasattr(spec, "output_schema")


def test_underscore_univer_reader_is_unknown() -> None:
    with pytest.raises(UnknownSpec) as raised:
        lookup_spec("univer_reader")
    assert raised.value.name == "univer_reader"


def test_only_writer_has_write_file() -> None:
    assert "write_file.v1" in lookup_spec("univer-writer").allowed_tools
    for name in ("univer-reader", "univer-critic", "univer-formula"):
        assert "write_file.v1" not in lookup_spec(name).allowed_tools


def test_writer_and_formula_have_formula_wait() -> None:
    assert "univer.formula_wait.v1" in lookup_spec("univer-formula").allowed_tools
    assert "univer.formula_wait.v1" in lookup_spec("univer-writer").allowed_tools
    for name in ("univer-reader", "univer-critic"):
        assert "univer.formula_wait.v1" not in lookup_spec(name).allowed_tools


def test_reader_and_critic_have_no_set_save_wait() -> None:
    forbidden = {
        "univer.range_set.v1",
        "univer.save.v1",
        "univer.formula_wait.v1",
        "write_file.v1",
    }
    for name in ("univer-reader", "univer-critic"):
        assert lookup_spec(name).allowed_tools.isdisjoint(forbidden)


def test_none_have_spawn_handoff_execute() -> None:
    for name in _UNIVER_NAMES:
        assert lookup_spec(name).allowed_tools.isdisjoint(_CONTROL)


def test_univer_allowed_tools_match_templates() -> None:
    assert lookup_spec("univer-reader").allowed_tools == _READER_TOOLS
    assert lookup_spec("univer-formula").allowed_tools == _FORMULA_TOOLS
    assert lookup_spec("univer-writer").allowed_tools == _WRITER_TOOLS
    assert lookup_spec("univer-critic").allowed_tools == _READER_TOOLS


def test_univer_prompt_forbids_spawn_and_is_not_fsi() -> None:
    prompt = build_univer_system_prompt()
    lowered = prompt.lower()
    assert "do not spawn" in lowered
    assert "report only" in lowered
    assert "untrusted" in lowered
    assert "fsi leaf worker" not in lowered
    assert "spawn_agent" not in lowered
    assert "you may call spawn_agent" not in prompt
    assert "you may call spawn_agent" in build_explore_system_prompt().lower()
    assert "FSI leaf worker" in build_fsi_system_prompt()


def test_univer_writer_prompt_starts_with_only_worker_with_write() -> None:
    prompt = build_univer_system_prompt_for(lookup_spec("univer-writer"))
    assert prompt.startswith("You are the ONLY worker with Write.")
    assert "FSI leaf worker" not in prompt
    assert "you may call spawn_agent" not in prompt.lower()


def test_univer_reader_and_formula_prompt_contains_schema_json() -> None:
    for name in ("univer-reader", "univer-formula"):
        prompt = build_univer_system_prompt_for(lookup_spec(name))
        assert "schema-validated JSON" in prompt
        assert "Return only schema-validated JSON; no free text." in prompt
        assert "FSI leaf worker" not in prompt
        assert "you may call spawn_agent" not in prompt.lower()


def test_univer_critic_prompt_does_not_require_json_suffix() -> None:
    prompt = build_univer_system_prompt_for(lookup_spec("univer-critic"))
    assert "ONLY worker with Write" not in prompt
    assert "Return only schema-validated JSON" not in prompt
    assert "FSI leaf worker" not in prompt
    assert "you may call spawn_agent" not in prompt.lower()


def test_reader_and_formula_descriptions_mention_schema_json() -> None:
    assert "schema-validated JSON" in lookup_spec("univer-reader").description
    assert "schema-validated JSON" in lookup_spec("univer-formula").description
    assert "Only worker with Write" in lookup_spec("univer-writer").description


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
        self._names = tuple(names or _PORT_NAMES)
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
        "parent_kind": ParentKind.UNIVER,
        "parent_id": "ct_parent",
        "parent_run_id": "cr_parent",
        "parent_tool_call_id": "toolu_spawn",
        "spec": "univer-reader",
        "briefing": ParentBriefing(goal="Inspect the sheet outline", success="JSON"),
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
async def test_univer_reader_advance_uses_univer_prompt_not_fsi_or_explore() -> None:
    runtime, _store, _tools, model, _events = _runtime([_text("outline extracted")])
    await runtime.advance(
        _ticket(spec="univer-reader", parent_kind=ParentKind.UNIVER)
    )
    expected = build_univer_system_prompt_for(lookup_spec("univer-reader"))
    assert model.requests[0].system == expected
    assert model.requests[0].system != build_fsi_system_prompt_for(
        lookup_spec("fsi-reader")
    )
    assert model.requests[0].system != build_explore_system_prompt()
    assert "FSI leaf worker" not in model.requests[0].system
    assert "spawn_agent" not in model.requests[0].system
    assert "spawn_agent.v1" not in model.requests[0].system
    assert "you may call spawn_agent" not in model.requests[0].system.lower()
