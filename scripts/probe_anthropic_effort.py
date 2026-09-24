"""Anthropic models API 로 모델별 effort 레벨을 읽는다 (일회성 확인 도구).

카탈로그의 `effort_levels` 는 이 출력으로만 채운다. 추측하지 않는다.

    python scripts/probe_anthropic_effort.py claude-sonnet-5 claude-opus-5-5
"""

from __future__ import annotations

import sys

import anthropic

LEVELS = ("low", "medium", "high", "xhigh", "max")


def levels_for(client: anthropic.Anthropic, model: str) -> list[str]:
    info = client.models.retrieve(model)
    effort = info.capabilities.effort
    if not effort.supported:
        return []
    found = []
    for level in LEVELS:
        support = getattr(effort, level, None)
        if support is not None and support.supported:
            found.append(level)
    return found


def main(models: list[str]) -> None:
    client = anthropic.Anthropic()
    for model in models:
        print(f"{model}: {levels_for(client, model)}")


if __name__ == "__main__":
    main(sys.argv[1:])
