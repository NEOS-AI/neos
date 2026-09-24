"""Worker discovery phase: LLM tool-calling over web_search + selected skills.

수동 tool-calling 루프다. SDK의 client.beta.messages.tool_runner를 쓰지 않는 이유:
tool_runner는 llm.py의 cassette 래핑을 우회해 record/replay 결정성과 D19 golden
게이트를 깨뜨린다.

이 단계는 URL을 모으기만 한다. 수집된 URL은 워커가 fetch.py로 retrieval하고,
DeterministicGrader가 원문 대조로 검증한다(P3).
"""

from __future__ import annotations

import json
from typing import Any

from .llm import call_messages
from .skills_adapter import skill_search

_WEB_TOOL = "search_web"

_DISCOVERY_PROMPT = """You are gathering candidate sources for a research question.

Question:
{brief}

Use the available search tools to find relevant sources. Prefer authoritative,
primary sources. You may call several tools in one turn. When you have enough
candidate sources, stop calling tools and reply with a single word: done.

Do not answer the question itself — only gather sources."""


def _tool_schema(description: str) -> dict[str, Any]:
    return {
        "description": description,
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query.",
                }
            },
            "required": ["query"],
        },
    }


def build_tool_defs(skills: list) -> list[dict[str, Any]]:
    defs: list[dict[str, Any]] = [
        {
            "name": _WEB_TOOL,
            **_tool_schema(
                "General web search. Use for broad or non-academic sources."
            ),
        }
    ]
    for skill in skills:
        defs.append(
            {
                "name": f"search_{skill.name}",
                **_tool_schema(
                    f"Search {skill.name}. {getattr(skill, 'description', '')} "
                    f"Call this when the question is within this source's domain."
                ),
            }
        )
    return defs


async def _dispatch(name, query, limit, skills_by_tool, search_fn, cassette):
    if name == _WEB_TOOL:
        # Worker._search와 동일한 cassette 키 형태를 쓴다 — search_fn을 직접
        # 부르면 이 경로만 녹화에서 빠져 replay 결정성에 구멍이 난다.
        async def produce():
            return await search_fn(query, k=limit)

        if cassette is None:
            return await produce()
        return await cassette.remember(
            "search", {"query": query, "limit": limit}, produce
        )

    skill = skills_by_tool.get(name)
    if skill is None:
        return None
    return await skill_search(skill, query, limit, cassette=cassette)


async def run_discovery(
    brief: str,
    skills: list,
    *,
    search_fn,
    model: str,
    max_tokens: int,
    limit: int,
    client=None,
    cassette=None,
    max_turns: int = 3,
    effort: str | None = None,
) -> tuple[list[dict[str, str]], int]:
    tools = build_tool_defs(skills)
    skills_by_tool = {f"search_{s.name}": s for s in skills}
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": _DISCOVERY_PROMPT.format(brief=brief)}
    ]

    collected: dict[str, dict[str, str]] = {}
    tokens = 0

    for _turn in range(max_turns):
        response = await call_messages(
            model,
            messages,
            tools=tools,
            max_tokens=max_tokens,
            client=client,
            cassette=cassette,
            stage="discovery",
            effort=effort,
        )
        tokens += response.input_tokens + response.output_tokens

        tool_uses = [b for b in response.content if b["type"] == "tool_use"]
        if response.stop_reason != "tool_use" or not tool_uses:
            break

        messages.append({"role": "assistant", "content": response.content})

        # 모든 tool_result는 단일 user 메시지에 담아야 한다 — 쪼개면 모델이
        # 병렬 도구 호출을 그만두도록 학습된다.
        tool_results: list[dict[str, Any]] = []
        for block in tool_uses:
            query = str(block["input"].get("query", ""))
            items = await _dispatch(
                block["name"], query, limit, skills_by_tool, search_fn, cassette
            )
            if items is None:
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block["id"],
                        "content": f"unknown tool: {block['name']}",
                        "is_error": True,
                    }
                )
                continue
            for item in items:
                collected.setdefault(item["url"], item)
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block["id"],
                    "content": json.dumps(
                        [{"url": i["url"], "title": i["title"]} for i in items],
                        ensure_ascii=False,
                    ),
                }
            )
        messages.append({"role": "user", "content": tool_results})

    return list(collected.values()), tokens
