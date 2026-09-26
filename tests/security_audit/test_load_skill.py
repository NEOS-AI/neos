from __future__ import annotations

import json

import pytest

from neos.coding.sandbox.base import SandboxTimeout
from neos.coding.tools.executor import SandboxToolExecutor
from neos.coding.tools.registry import ToolRisk, ValidatedToolCall

pytestmark = pytest.mark.no_db


class FakeSession:
    sandbox_id = "sandbox-1"

    def __init__(self) -> None:
        self.called: tuple[str, object] | None = None
        self.error: Exception | None = None

    def _raise(self) -> None:
        if self.error is not None:
            raise self.error


def call(name: str, payload: dict[str, object]) -> ValidatedToolCall:
    return ValidatedToolCall(name, payload, ToolRisk.READ_ONLY)


@pytest.mark.asyncio
async def test_load_skill_security_audit_returns_pack_body_not_index() -> None:
    session = FakeSession()
    session.error = SandboxTimeout("load_skill must not touch the sandbox")
    result = await SandboxToolExecutor(10, 10).execute(
        session, call("load_skill.v1", {"name": "security-audit"})
    )

    assert (result.status, result.reason_code) == ("ok", "ok")
    assert session.called is None
    text = json.dumps(result.to_mapping())
    assert "Operating modes" in text
    assert "Full audit mode" in text
    assert "Do not dump companion leaves into this prompt" not in text


@pytest.mark.asyncio
async def test_load_skill_security_audit_reference_reconnaissance() -> None:
    session = FakeSession()
    session.error = SandboxTimeout("load_skill must not touch the sandbox")
    result = await SandboxToolExecutor(10, 10).execute(
        session,
        call(
            "load_skill.v1",
            {"name": "security-audit", "reference": "RECONNAISSANCE.md"},
        ),
    )

    assert (result.status, result.reason_code) == ("ok", "ok")
    text = json.dumps(result.to_mapping())
    assert "Phase 1" in text
    assert "coverage-ledger.json" in text


@pytest.mark.asyncio
async def test_load_skill_still_denies_foreign_and_companion_names() -> None:
    session = FakeSession()
    session.error = SandboxTimeout("load_skill must not touch the sandbox")
    executor = SandboxToolExecutor(10, 10)
    for name in (
        "pdf",
        "xlsx-author",
        "univer-sheets-headless",
        "k-skill-setup",
        "k-skill-cleaner",
        "HUNTING",
        "RECONNAISSANCE",
    ):
        result = await executor.execute(session, call("load_skill.v1", {"name": name}))
        assert (result.status, result.reason_code) == ("denied", "unknown_skill")
    assert session.called is None


@pytest.mark.asyncio
async def test_load_skill_korea_weather_still_hits_k_skill() -> None:
    session = FakeSession()
    session.error = SandboxTimeout("load_skill must not touch the sandbox")
    result = await SandboxToolExecutor(10, 10).execute(
        session, call("load_skill.v1", {"name": "korea-weather"})
    )

    assert (result.status, result.reason_code) == ("ok", "ok")
    text = json.dumps(result.to_mapping())
    assert "k-skill-proxy" in text
