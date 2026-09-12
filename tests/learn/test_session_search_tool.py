from __future__ import annotations

import ast
from pathlib import Path

import pytest

from neos.config.schema import AppConfig
from neos.learn.session_search_tool import (
    SEARCH_USER_SESSIONS_TOOL,
    handle_search_user_sessions,
    list_chat_research_tools,
)

pytestmark = pytest.mark.no_db

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_session_search_tool_default_off() -> None:
    config = AppConfig()
    assert config.learn.session_search_tool is False
    assert config.learn.coding_lessons is False


def test_session_search_tool_omitted_when_flag_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from neos.config.settings import settings

    monkeypatch.setattr(settings.config.learn, "session_search_tool", False)
    assert list_chat_research_tools() == []


def test_session_search_tool_listed_when_flag_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from neos.config.settings import settings

    monkeypatch.setattr(settings.config.learn, "session_search_tool", True)
    tools = list_chat_research_tools()
    assert tools == [SEARCH_USER_SESSIONS_TOOL]
    assert "user_id" not in tools[0]["input_schema"]["properties"]
    assert "query" in tools[0]["input_schema"]["required"]


def test_system_prompt_builder_includes_tool_only_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from neos.api.services.chat_system_prompt_builder import SystemPromptBuilder
    from neos.config.settings import settings

    monkeypatch.setattr(settings.config.learn, "session_search_tool", False)
    _, off_tools = SystemPromptBuilder().with_session_search().build()
    assert not any(tool["name"] == "search_user_sessions" for tool in off_tools)

    monkeypatch.setattr(settings.config.learn, "session_search_tool", True)
    _, on_tools = SystemPromptBuilder().with_session_search().build()
    assert any(tool["name"] == "search_user_sessions" for tool in on_tools)


@pytest.mark.asyncio
async def test_handler_requires_user_id() -> None:
    with pytest.raises(ValueError, match="user_id is required"):
        await handle_search_user_sessions({"query": "rate limit"}, user_id="")


@pytest.mark.asyncio
async def test_handler_rejects_other_user_id_from_tool_args(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: dict[str, object] = {}

    async def fake_search(
        user_id: str,
        query: str,
        *,
        limit: int = 5,
        exclude_conversation_id: str | None = None,
    ):
        called["user_id"] = user_id
        return [{"message_id": "m1", "content": "secret", "user_id": user_id}]

    monkeypatch.setattr(
        "neos.learn.session_search_tool.search_user_sessions", fake_search
    )

    with pytest.raises(ValueError, match="cannot be supplied by the model"):
        await handle_search_user_sessions(
            {"query": "rate limit", "user_id": "other-user"},
            user_id="auth-user",
        )
    assert called == {}


@pytest.mark.asyncio
async def test_handler_uses_authenticated_user_and_returns_snippets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: dict[str, object] = {}

    async def fake_search(
        user_id: str,
        query: str,
        *,
        limit: int = 5,
        exclude_conversation_id: str | None = None,
    ):
        called["user_id"] = user_id
        called["query"] = query
        called["limit"] = limit
        called["exclude_conversation_id"] = exclude_conversation_id
        return [
            {
                "message_id": "m1",
                "conversation_id": "c1",
                "conversation_title": "limits",
                "content": "retry after 429",
                "role": "assistant",
                "similarity_score": 0.91,
                "user_id": user_id,
            }
        ]

    monkeypatch.setattr(
        "neos.learn.session_search_tool.search_user_sessions", fake_search
    )

    result = await handle_search_user_sessions(
        {"query": "rate limit", "limit": 99, "user_id": "auth-user"},
        user_id="auth-user",
    )

    assert called == {
        "user_id": "auth-user",
        "query": "rate limit",
        "limit": 10,
        "exclude_conversation_id": None,
    }
    assert result["type"] == "tool_result"
    assert "summary" not in result
    assert result["snippets"] == [
        {
            "message_id": "m1",
            "conversation_id": "c1",
            "conversation_title": "limits",
            "snippet": "retry after 429",
            "role": "assistant",
            "similarity_score": 0.91,
        }
    ]


@pytest.mark.asyncio
async def test_handler_clips_content_and_hides_cron_subagent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_search(
        user_id: str,
        query: str,
        *,
        limit: int = 5,
        exclude_conversation_id: str | None = None,
    ):
        return [
            {
                "message_id": "m1",
                "conversation_id": "c1",
                "conversation_title": "long",
                "content": "A" * 400,
                "role": "assistant",
                "similarity_score": 0.9,
            },
            {
                "message_id": "m2",
                "conversation_id": "c2",
                "conversation_title": "nightly",
                "content": "cron tick",
                "source": "cron",
                "role": "assistant",
                "similarity_score": 0.8,
            },
            {
                "message_id": "m3",
                "conversation_id": "c3",
                "conversation_title": "child",
                "content": "spawned work",
                "origin": "subagent",
                "role": "assistant",
                "similarity_score": 0.7,
            },
            {
                "message_id": "m4",
                "conversation_id": "c4",
                "conversation_title": "hit",
                "content": "full message body that should not leak",
                "snippet": "short hit",
                "role": "assistant",
                "similarity_score": 0.6,
            },
        ]

    monkeypatch.setattr(
        "neos.learn.session_search_tool.search_user_sessions", fake_search
    )

    result = await handle_search_user_sessions({"query": "rate limit"}, user_id="u1")

    assert "summary" not in result
    snippets = result["snippets"]
    assert [item["message_id"] for item in snippets] == ["m1", "m4"]
    assert snippets[0]["snippet"] == "A" * 240
    assert snippets[1]["snippet"] == "short hit"


@pytest.mark.asyncio
async def test_handler_passes_exclude_conversation_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: dict[str, object] = {}

    async def fake_search(
        user_id: str,
        query: str,
        *,
        limit: int = 5,
        exclude_conversation_id: str | None = None,
    ):
        called["exclude_conversation_id"] = exclude_conversation_id
        return []

    monkeypatch.setattr(
        "neos.learn.session_search_tool.search_user_sessions", fake_search
    )

    await handle_search_user_sessions(
        {"query": "rate limit", "exclude_conversation_id": "from-input"},
        user_id="u1",
        exclude_conversation_id="from-caller",
    )
    assert called["exclude_conversation_id"] == "from-caller"

    await handle_search_user_sessions(
        {"query": "rate limit", "exclude_conversation_id": "from-input"},
        user_id="u1",
    )
    assert called["exclude_conversation_id"] == "from-input"


def _imported_modules(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return modules


def test_session_search_tool_not_imported_by_coding_registry() -> None:
    registry_path = REPO_ROOT / "neos" / "coding" / "tools" / "registry.py"
    source = registry_path.read_text(encoding="utf-8")
    assert "session_search" not in source
    assert "search_user_sessions" not in source
    imported = _imported_modules(registry_path)
    assert not any("session_search" in module for module in imported)
    assert not any(module.startswith("neos.learn") for module in imported)

    from neos.coding.tools.registry import CodingToolRegistry

    names = [
        item.name
        for item in CodingToolRegistry.default(
            command_allowlist=frozenset({"pytest"}),
            max_command_timeout_sec=30,
            max_command_output_bytes=4096,
            max_command_stdin_bytes=8,
            allowed_env_names=frozenset({"PATH"}),
        ).definitions()
    ]
    assert "search_user_sessions" not in names
    assert not any("session_search" in name for name in names)


def test_chat_research_path_lists_session_search_tool() -> None:
    chat_llm = (
        REPO_ROOT / "neos" / "services" / "chat_llm_service.py"
    ).read_text(encoding="utf-8")
    builder = (
        REPO_ROOT / "neos" / "api" / "services" / "chat_system_prompt_builder.py"
    ).read_text(encoding="utf-8")
    assert "list_chat_research_tools" in chat_llm
    assert "search_user_sessions" in chat_llm
    assert "with_session_search" in builder
