from types import SimpleNamespace
from pathlib import Path
import pytest
from neos.univer.ports import UniverToolPort
from neos.univer.sidecar import InMemorySidecar

pytestmark = pytest.mark.no_db

def _flags(**kwargs):
    base = dict(enabled=True, sheets_enabled=True, docs_enabled=True, formula_enabled=True)
    base.update(kwargs)
    return SimpleNamespace(**base)

@pytest.mark.asyncio
async def test_master_off_disables_inspect(tmp_path: Path) -> None:
    port = UniverToolPort(InMemorySidecar(session_dir=tmp_path), flags=_flags(enabled=False))
    result = await port.execute("univer.inspect.v1", {})
    assert result == {"ok": False, "error": "flag_disabled", "flag": "enabled"}

@pytest.mark.asyncio
async def test_formula_wait_requires_formula_flag(tmp_path: Path) -> None:
    port = UniverToolPort(
        InMemorySidecar(session_dir=tmp_path),
        flags=_flags(formula_enabled=False),
    )
    result = await port.execute("univer.formula_wait.v1", {})
    assert result == {"ok": False, "error": "flag_disabled", "flag": "formula_enabled"}

@pytest.mark.asyncio
async def test_doc_kind_requires_docs_flag(tmp_path: Path) -> None:
    port = UniverToolPort(
        InMemorySidecar(session_dir=tmp_path, kind="doc"),
        flags=_flags(docs_enabled=False),
    )
    result = await port.execute("univer.inspect.v1", {})
    assert result == {"ok": False, "error": "flag_disabled", "flag": "docs_enabled"}
