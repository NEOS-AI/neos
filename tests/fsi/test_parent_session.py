from __future__ import annotations

import json
from pathlib import Path

import pytest

from neos.coding.model.base import ModelCompleted, ModelUsage, TextDelta, ToolCallCompleted
from neos.fsi.loop import (
    FlagDisabled,
    cancel_fsi_children,
    make_fsi_runtime,
    overlay_catalog,
    run_parent_spawn,
)
from neos.fsi.ports import FsiSessionPort
from neos.fsi.profile import compile_leaf_spec, load_profile
from neos.subagent.catalog import SpecRegistry, UnknownSpec, lookup_spec
from neos.subagent.types import (
    ModelPin,
    ParentBriefing,
    ParentKind,
    StepKind,
    SubagentStatus,
    SubagentTicket,
)
from tests.fsi.fakes import ScriptedCodingModel
from tests.fsi.test_loop import _VALID_KYC

pytestmark = pytest.mark.no_db

_PROFILES = Path(__file__).resolve().parent / "fixtures" / "profiles"
_LEAF_TEXT = json.dumps(_VALID_KYC)
_LEAVES = (
    "kyc-doc-reader",
    "kyc-rules-engine",
    "kyc-escalator",
)


def _kyc() -> dict[str, object]:
    return dict(load_profile("kyc-screener", profiles_dir=_PROFILES))


def _briefing() -> ParentBriefing:
    return ParentBriefing(
        goal="Extract the KYC packet", success="Name the fields"
    )


def _pin() -> ModelPin:
    return ModelPin(provider="anthropic", model="claude-test")


def _text(text: str = _LEAF_TEXT):
    return (TextDelta(text), ModelCompleted("end_turn", ModelUsage(3, 2)))


def _tool():
    return (
        TextDelta("looking"),
        ToolCallCompleted("call_1", "read_file.v1", {"path": "packet.txt"}),
        ModelCompleted("tool_use", ModelUsage(4, 1)),
    )


def _runtime(tmp_path: Path, *, catalog: SpecRegistry, script=None):
    model = ScriptedCodingModel([_text()] if script is None else script)
    tools = FsiSessionPort(tmp_path, write=False)
    return make_fsi_runtime(model=model, tools=tools, catalog=catalog), model


async def _spawn(
    tmp_path: Path,
    *,
    enabled: bool = True,
    spec: str = "kyc-doc-reader",
    catalog: SpecRegistry | None = None,
    script=None,
):
    profile = _kyc()
    overlay = overlay_catalog(profile)
    runtime, _model = _runtime(
        tmp_path,
        catalog=overlay if catalog is None else catalog,
        script=script,
    )
    folded = await run_parent_spawn(
        runtime=runtime,
        profile=profile,
        spec=spec,
        briefing=_briefing(),
        parent_id="fsi-1",
        parent_run_id="fsi-run",
        parent_tool_call_id="toolu_fsi",
        model=_pin(),
        enabled=enabled,
    )
    return runtime, folded


def test_overlay_catalog_registers_only_profile_leaves() -> None:
    with pytest.raises(UnknownSpec):
        lookup_spec("kyc-doc-reader")
    overlay = overlay_catalog(_kyc())
    for name in _LEAVES:
        overlay.lookup_spec(name)
    with pytest.raises(UnknownSpec) as raised:
        overlay.lookup_spec("explore")
    assert raised.value.name == "explore"
    with pytest.raises(UnknownSpec):
        overlay.lookup_spec("fsi-reader")
    with pytest.raises(UnknownSpec):
        lookup_spec("kyc-doc-reader")
    compiled = overlay.lookup_spec("kyc-doc-reader")
    assert compiled.allowed_tools == compile_leaf_spec(
        _kyc(), "kyc-doc-reader"
    ).allowed_tools
    lookup_spec("explore")
    lookup_spec("fsi-reader")


@pytest.mark.asyncio
async def test_disabled_flag_raises_and_store_stays_empty(tmp_path: Path) -> None:
    with pytest.raises(FlagDisabled):
        await _spawn(tmp_path, enabled=False)
    runtime, _model = _runtime(tmp_path, catalog=overlay_catalog(_kyc()), script=[])
    with pytest.raises(FlagDisabled):
        await run_parent_spawn(
            runtime=runtime,
            profile=_kyc(),
            spec="kyc-doc-reader",
            briefing=_briefing(),
            parent_id="fsi-1",
            parent_run_id="fsi-run",
            parent_tool_call_id="toolu_fsi",
            model=_pin(),
            enabled=False,
        )
    assert runtime._store._runs == {}


@pytest.mark.asyncio
async def test_unknown_spec_is_fail_closed(tmp_path: Path) -> None:
    runtime, _model = _runtime(tmp_path, catalog=overlay_catalog(_kyc()), script=[])
    with pytest.raises(UnknownSpec) as raised:
        await run_parent_spawn(
            runtime=runtime,
            profile=_kyc(),
            spec="session-reader",
            briefing=_briefing(),
            parent_id="fsi-1",
            parent_run_id="fsi-run",
            parent_tool_call_id="toolu_fsi",
            model=_pin(),
            enabled=True,
        )
    assert raised.value.name == "session-reader"
    assert runtime._store._runs == {}


@pytest.mark.asyncio
async def test_module_spec_not_in_overlay_is_unknown(tmp_path: Path) -> None:
    runtime, _model = _runtime(tmp_path, catalog=SpecRegistry(), script=[])
    lookup_spec("explore")
    with pytest.raises(UnknownSpec) as raised:
        await run_parent_spawn(
            runtime=runtime,
            profile=_kyc(),
            spec="explore",
            briefing=_briefing(),
            parent_id="fsi-1",
            parent_run_id="fsi-run",
            parent_tool_call_id="toolu_fsi",
            model=_pin(),
            enabled=True,
        )
    assert raised.value.name == "explore"
    assert runtime._store._runs == {}
    with pytest.raises(UnknownSpec):
        lookup_spec("kyc-doc-reader")


@pytest.mark.asyncio
async def test_parent_spawn_kyc_doc_reader_folds_schema(tmp_path: Path) -> None:
    runtime, folded = await _spawn(tmp_path)
    assert runtime._stepper._nested_spawn is None
    assert folded.summary == _LEAF_TEXT
    record = await runtime._store.get(folded.run_id)
    assert record.parent_kind is ParentKind.FSI
    assert record.parent_kind.value == "fsi"
    assert record.spec == "kyc-doc-reader"
    with pytest.raises(UnknownSpec):
        lookup_spec("kyc-doc-reader")


@pytest.mark.asyncio
async def test_cancel_fsi_children_when_disabled(tmp_path: Path) -> None:
    runtime, _model = _runtime(tmp_path, catalog=overlay_catalog(_kyc()), script=[])
    snaps = await cancel_fsi_children(runtime, "fsi-1", enabled=False)
    assert snaps == []
    snaps_on = await cancel_fsi_children(runtime, "fsi-1", enabled=True)
    assert snaps_on == []


@pytest.mark.asyncio
async def test_cancel_fsi_children_kills_continuing_child(tmp_path: Path) -> None:
    overlay = overlay_catalog(_kyc())
    runtime, _model = _runtime(tmp_path, catalog=overlay, script=[_tool()])
    ticket = SubagentTicket(
        parent_kind=ParentKind.FSI,
        parent_id="fsi-1",
        parent_run_id="fsi-run",
        parent_tool_call_id="toolu_fsi",
        spec="kyc-doc-reader",
        briefing=_briefing(),
        model=_pin(),
    )
    outcome = await runtime.advance(ticket)
    assert outcome.kind is StepKind.CONTINUING
    skipped = await cancel_fsi_children(runtime, "fsi-1", enabled=True)
    assert skipped == []
    live = await runtime._store.get(outcome.run_id)
    assert live.status is SubagentStatus.RUNNING
    snaps = await cancel_fsi_children(runtime, "fsi-1", enabled=False)
    assert len(snaps) == 1
    assert snaps[0].run_id == outcome.run_id
    assert snaps[0].status is SubagentStatus.KILLED
    assert snaps[0].error_code == "flag_disabled"
