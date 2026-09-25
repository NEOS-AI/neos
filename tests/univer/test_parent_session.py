from __future__ import annotations

import json
from pathlib import Path

import pytest

from neos.coding.model.base import ModelCompleted, ModelUsage, TextDelta
from neos.subagent.catalog import SpecRegistry, UnknownSpec, lookup_spec
from neos.subagent.types import ModelPin, ParentBriefing, ParentKind
from neos.univer.loop import (
    FlagDisabled,
    make_univer_runtime,
    overlay_catalog,
    run_parent_spawn,
)
from neos.univer.profile import compile_leaf_spec, load_profile
from tests.univer.fakes import ScriptedCodingModel
from tests.univer.test_loop import _VALID_READER

pytestmark = pytest.mark.no_db

_PROFILES = Path(__file__).resolve().parents[2] / "skills" / "univer" / "profiles"
_LEAF_TEXT = json.dumps(_VALID_READER)
_LEAVES = (
    "univer-reader",
    "univer-formula",
    "univer-writer",
    "univer-critic",
)


class _EmptyPort:
    def definitions(self):
        return ()

    async def execute(self, name, input):
        return {"ok": False, "error": "tool_not_allowed"}


def _office() -> dict[str, object]:
    return dict(load_profile("office-session", profiles_dir=_PROFILES))


def _briefing() -> ParentBriefing:
    return ParentBriefing(
        goal="Inspect the sheet outline", success="Return schema JSON"
    )


def _pin() -> ModelPin:
    return ModelPin(provider="anthropic", model="claude-test")


def _text(text: str = _LEAF_TEXT):
    return (TextDelta(text), ModelCompleted("end_turn", ModelUsage(3, 2)))


def _runtime(*, catalog: SpecRegistry, script=None):
    model = ScriptedCodingModel([_text()] if script is None else script)
    return make_univer_runtime(model=model, tools=_EmptyPort(), catalog=catalog), model


async def _spawn(
    *,
    enabled: bool = True,
    spec: str = "univer-reader",
    catalog: SpecRegistry | None = None,
    script=None,
):
    profile = _office()
    overlay = overlay_catalog(profile)
    runtime, _model = _runtime(
        catalog=overlay if catalog is None else catalog, script=script
    )
    folded = await run_parent_spawn(
        runtime=runtime,
        profile=profile,
        spec=spec,
        briefing=_briefing(),
        parent_id="office-1",
        parent_run_id="office-run",
        parent_tool_call_id="toolu_office",
        model=_pin(),
        enabled=enabled,
    )
    return runtime, folded


def test_overlay_catalog_registers_only_profile_leaves() -> None:
    module = lookup_spec("univer-reader")
    overlay = overlay_catalog(_office())
    for name in _LEAVES:
        overlay.lookup_spec(name)
    with pytest.raises(UnknownSpec) as raised:
        overlay.lookup_spec("explore")
    assert raised.value.name == "explore"
    assert lookup_spec("univer-reader") is module
    compiled = overlay.lookup_spec("univer-reader")
    assert compiled is not module
    assert compiled.allowed_tools == compile_leaf_spec(
        _office(), "univer-reader"
    ).allowed_tools
    lookup_spec("explore")


@pytest.mark.asyncio
async def test_disabled_flag_raises_and_store_stays_empty() -> None:
    with pytest.raises(FlagDisabled):
        await _spawn(enabled=False)
    runtime, _model = _runtime(catalog=overlay_catalog(_office()), script=[])
    with pytest.raises(FlagDisabled):
        await run_parent_spawn(
            runtime=runtime,
            profile=_office(),
            spec="univer-reader",
            briefing=_briefing(),
            parent_id="office-1",
            parent_run_id="office-run",
            parent_tool_call_id="toolu_office",
            model=_pin(),
            enabled=False,
        )
    assert runtime._store._runs == {}


@pytest.mark.asyncio
async def test_unknown_spec_is_fail_closed() -> None:
    runtime, _model = _runtime(catalog=overlay_catalog(_office()), script=[])
    with pytest.raises(UnknownSpec) as raised:
        await run_parent_spawn(
            runtime=runtime,
            profile=_office(),
            spec="session-reader",
            briefing=_briefing(),
            parent_id="office-1",
            parent_run_id="office-run",
            parent_tool_call_id="toolu_office",
            model=_pin(),
            enabled=True,
        )
    assert raised.value.name == "session-reader"
    assert runtime._store._runs == {}


@pytest.mark.asyncio
async def test_module_spec_not_in_overlay_is_unknown() -> None:
    runtime, _model = _runtime(catalog=SpecRegistry(), script=[])
    lookup_spec("explore")
    with pytest.raises(UnknownSpec) as raised:
        await run_parent_spawn(
            runtime=runtime,
            profile=_office(),
            spec="explore",
            briefing=_briefing(),
            parent_id="office-1",
            parent_run_id="office-run",
            parent_tool_call_id="toolu_office",
            model=_pin(),
            enabled=True,
        )
    assert raised.value.name == "explore"
    assert runtime._store._runs == {}


@pytest.mark.asyncio
async def test_parent_spawn_univer_reader_folds_schema_00() -> None:
    runtime, folded = await _spawn()
    assert runtime._stepper._nested_spawn is None
    assert folded.summary == _LEAF_TEXT
    record = await runtime._store.get(folded.run_id)
    assert record.parent_kind is ParentKind.UNIVER
    assert record.parent_kind.value == "univer"
    assert record.spec == "univer-reader"
    lookup_spec("univer-reader")
