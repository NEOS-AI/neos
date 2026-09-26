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
async def test_load_skill_korea_weather_returns_instruction_body() -> None:
    session = FakeSession()
    session.error = SandboxTimeout("load_skill must not touch the sandbox")
    result = await SandboxToolExecutor(10, 10).execute(
        session, call("load_skill.v1", {"name": "korea-weather"})
    )

    assert (result.status, result.reason_code) == ("ok", "ok")
    assert session.called is None
    text = json.dumps(result.to_mapping())
    assert "k-skill-proxy" in text
    assert "k-skill:cli-stub" not in text


@pytest.mark.asyncio
async def test_load_skill_still_denies_foreign_and_excluded_names() -> None:
    session = FakeSession()
    session.error = SandboxTimeout("load_skill must not touch the sandbox")
    executor = SandboxToolExecutor(10, 10)
    for name in (
        "pdf",
        "xlsx-author",
        "univer-sheets-headless",
        "k-skill-setup",
        "k-skill-cleaner",
    ):
        result = await executor.execute(session, call("load_skill.v1", {"name": name}))
        assert (result.status, result.reason_code) == ("denied", "unknown_skill")
    assert session.called is None
