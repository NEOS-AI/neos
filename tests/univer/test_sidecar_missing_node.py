from __future__ import annotations

from pathlib import Path

import pytest

from neos.univer.ports import UniverToolPort
from neos.univer.sidecar import SidecarClient, node_binary

pytestmark = pytest.mark.no_db

_SIDECAR_TOOLS = (
    "univer.inspect.v1",
    "univer.range_get.v1",
    "univer.range_set.v1",
    "univer.execute_command.v1",
    "univer.formula_wait.v1",
    "univer.save.v1",
)


def _names(port: UniverToolPort) -> tuple[str, ...]:
    names: list[str] = []
    for item in port.definitions():
        names.append(item if isinstance(item, str) else item.name)
    return tuple(names)


def test_node_binary_is_path_or_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("neos.univer.sidecar.shutil.which", lambda _name: None)
    assert node_binary() is None
    monkeypatch.setattr(
        "neos.univer.sidecar.shutil.which", lambda _name: "/usr/bin/node"
    )
    found = node_binary()
    assert found == Path("/usr/bin/node")


def test_schema_import_is_not_skipped_when_node_missing() -> None:
    from neos.univer.schemas import READER_SCHEMAS, validate_child_fold

    assert "univer-reader" in READER_SCHEMAS
    folded = validate_child_fold("univer-critic", "free text")
    assert folded == {"text": "free text"}


@pytest.mark.asyncio
async def test_definitions_include_tools_when_node_missing() -> None:
    port = UniverToolPort(SidecarClient(node=None))
    assert _names(port) == _SIDECAR_TOOLS


@pytest.mark.asyncio
async def test_inspect_is_node_missing_never_ok() -> None:
    port = UniverToolPort(SidecarClient(node=None))
    result = await port.execute("univer.inspect.v1", {})
    assert result == {"ok": False, "error": "node_missing"}
    assert result.get("ok") is not True


@pytest.mark.asyncio
async def test_all_rpc_tools_fail_closed_without_node() -> None:
    port = UniverToolPort(SidecarClient(node=None))
    for name in _SIDECAR_TOOLS:
        if name == "univer.execute_command.v1":
            payload: dict[str, object] = {"id": "sheet.command.set-range-values"}
        else:
            payload = {}
        result = await port.execute(name, payload)
        assert result["ok"] is False
        assert result["error"] == "node_missing"


@pytest.mark.asyncio
async def test_execute_never_raises() -> None:
    port = UniverToolPort(SidecarClient(node=None))
    result = await port.execute("univer.save.v1", {"path": object()})  # type: ignore[dict-item]
    assert result["ok"] is False
    assert "error" in result
