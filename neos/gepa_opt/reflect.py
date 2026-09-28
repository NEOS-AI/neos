"""Reflection prompt render and fenced proposal parse. No model client."""

from __future__ import annotations

import json
import re

REFLECTION_TEMPLATE = """I provided an assistant with the following instructions to perform a task for me:
```
<curr_param>
```

The following are examples of different task inputs provided to the assistant along with the assistant's response for each of them, and some feedback on how the assistant's response could be better:
```
<side_info>
```

Your task is to write a new instruction for the assistant.

Read the inputs carefully and identify the input format and infer detailed task description about the task I wish to solve with the assistant.

Read all the assistant responses and the corresponding feedback. Identify all niche and domain specific factual information about the task and include it in the instruction, as a lot of it may not be available to the assistant in the future. The assistant may have utilized a generalizable strategy to solve the task, if so, include that in the instruction as well.

Provide the new instructions within ``` blocks."""

_SIDE_INFO_CAP_BYTES = 8192
_LEADING_LANG = re.compile(r"^\S*\n")
_LEADING_FENCE = re.compile(r"^```[ \t]*\S*[ \t]*\n")


class ParseSkip:
    """Sentinel for truncated reflection output. Not an exception."""


def render_reflection(curr_param: str, side_info: dict) -> str:
    """Substitute the current parameter, then the sorted side-info JSON."""
    rendered = REFLECTION_TEMPLATE.replace("<curr_param>", curr_param)
    rendered = rendered.replace("<side_info>", json.dumps(side_info, sort_keys=True))
    return rendered


def parse_proposal(text: str, finish_reason: str | None) -> str | ParseSkip:
    """Return the fenced proposal, a salvaged body, or ParseSkip if truncated."""
    start = text.find("```")
    end = text.rfind("```")
    if start != -1 and start + 3 < end:
        inner = _LEADING_LANG.sub("", text[start + 3 : end], count=1)
        return inner.strip()
    if finish_reason in {"length", "max_tokens"} or _unclosed_think(text):
        return ParseSkip()
    cleaned = text.strip()
    cleaned = _LEADING_FENCE.sub("", cleaned, count=1)
    if "\n" in cleaned:
        head, last = cleaned.rsplit("\n", 1)
        if last.strip() == "```":
            cleaned = head
    elif cleaned.strip() == "```":
        cleaned = ""
    return cleaned.strip()


def cap_side_info(payload: dict) -> dict:
    """Drop the payload when its sorted JSON encoding exceeds 8192 UTF-8 bytes."""
    encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
    if len(encoded) > _SIDE_INFO_CAP_BYTES:
        return {"truncated": True}
    return payload


def _unclosed_think(text: str) -> bool:
    return text.lstrip().startswith("<think>") and "</think>" not in text
