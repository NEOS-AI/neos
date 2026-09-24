"""K1b · K4b -- Fable 5.1 의 thinking 바인딩과 progress update 를 실계정에서 확인한다.

    python -m scripts.fable_binding_probe            # 아티팩트: artifacts/fable-k1b/<UTC>/

## 왜 가짜 모델로는 안 되는가

`_guard_thinking_prefix` 와 요청 바이트 동일 테스트는 가짜 모델에서 초록이다.
실제 API 가 thinking 서명을 **무엇에** 묶는지는 API 만 안다. 틀리면 Fable 5.1 로
옮기는 순간 매 요청이 400 이다 -- D94(키 존재만 본 preflight)와 같은 모양.

## 세 단계 (로드맵 §5.5 · 스펙 R-01 · R-04)

1. **NEOS 경로(B).** 응답을 `_completed_turn` 과 같은 모양으로 접고(thinking 을
   **맨 앞**에 모은다, 텍스트를 하나로 합친다) `_to_anthropic_request` 로 그린다.
   `drop_block` 진단 모드에서 매 요청의 `input_transformations` 가 비어야 한다.
2. **원문 재전송(A).** 같은 대화를 API 가 준 블록 순서 그대로 다시 보낸다. B 가
   비지 않았을 때 원인이 NEOS 의 재조립인지 가르는 기준선이다.
3. **음성 대조(C).** 앞부분(system)을 일부러 바꾼다. 여기서 `input_transformations`
   가 **비지 않아야** "비었다"가 의미를 가진다 -- 필드가 아예 안 채워지는 것과
   "문제없음"을 구분하는 유일한 방법이다. 같은 변조를 바인딩 제어 없이 보내면
   스펙은 400 이라고 적었다(C0).

K4b 는 같은 세션에서 본다: `display="updates"` 의 thinking 블록이 비어 있지 않은가,
그리고 `display` 를 **안 보냈을 때** 무엇이 오는가(스펙 `omitted` vs SDK `summarized`).

## 적지 않는 것

키·헤더는 아티팩트에 남기지 않는다. 호출은 12회 안팎이다.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import anthropic

from neos.coding.model.anthropic import _to_anthropic_request
from neos.coding.model.base import (
    CanonicalMessage,
    ModelLimits,
    ModelRequest,
    TextContent,
    ThinkingContent,
    ToolDefinition,
    ToolResultContent,
    ToolUseContent,
)
from neos.utils.anthropic_client import build_async_anthropic

MODEL = "claude-fable-5-1"
BINDING_BETA = "thinking-binding-controls-2026-08-01"
UPDATES_BETA = "thinking-display-updates-2026-08-18"
MAX_TURNS = 10

SYSTEM = (
    "You are a research assistant with access to a small note store.\n\n"
    # 스펙 R-04 의 human-in-the-loop 초안 그대로 -- updates 가 나올 조건을 만든다.
    "Say in one line what you're about to do before you start, and post brief\n"
    "updates as you work. Finish with a short recap that stands alone: what you\n"
    "found, what you changed, and what remains."
)
#: 자율 모드(DA 워커가 늘 이 모드다). 스펙은 updates 가 **긴 도구 체인**에서 텍스트
#: 대신 thinking 으로 나온다고 적었다 -- 대면 프롬프트는 모델이 텍스트로 말하게 만들어
#: 첫 세션(2026-09-24)에서 updates 가 하나도 나오지 않았다.
SYSTEM_AUTONOMOUS = (
    "You are a research assistant working unattended with access to a note store. "
    "No human is watching; finish the task and give the final answer."
)
USER_LONG = (
    "Audit every note in the store: read each one, and report every project with its "
    "most recent launch date, flagging notes that contradict each other."
)
USER = (
    "Which of my notes gives the launch date for Project Heron, and what is the "
    "date? Check every note that looks relevant before answering -- one of them "
    "may be out of date."
)
NOTES = {
    "heron-kickoff": "Project Heron kickoff. Tentative launch: 2026-11-02.",
    "heron-status-oct": "Heron status: launch moved to 2026-11-16 after QA slip.",
    "grocery": "eggs, oat milk, basil",
    "osprey-plan": "Project Osprey launches 2027-01-10.",
    "osprey-risk": "Osprey vendor contract unsigned; launch may slip to 2027-02.",
    "kestrel-brief": "Project Kestrel: launch 2026-12-01, pending legal review.",
    "kestrel-legal": "Legal cleared Kestrel on 2026-10-20; date unchanged.",
    "heron-retro": "Heron retro draft -- written before the QA slip.",
}
#: 사슬 모드. 두 번째 세션에서 모델이 노트 8개를 **한 턴에 병렬로** 읽어 체인이
#: 생기지 않았다(thinking 13 토큰). 다음 노트 이름이 앞 노트 안에만 있으면 병렬이
#: 불가능하다 -- 스펙이 updates 가 나온다고 적은 "긴 도구 체인"을 강제한다.
CHAIN = {
    "start": "Ledger audit, step 1: the Q3 total is 41. Continue at note 'k7f2'.",
    "k7f2": "Step 2: subtract the refund of 6. Continue at note 'q9ad'.",
    "q9ad": "Step 3: add the late invoice of 13. Continue at note 'm3xe'.",
    "m3xe": "Step 4: the refund in step 2 was reversed -- undo it. Continue at note 'z1pp'.",
    "z1pp": "Step 5: apply a 10% fee to the running total, rounding down. Continue at note 'w8hc'.",
    "w8hc": "Step 6: this is the last step. Report the final total and every step's value.",
}
USER_CHAIN = (
    "Follow the ledger audit starting at note 'start' until it ends, then give the "
    "final total with the value after each step."
)
TOOLS = (
    ToolDefinition(
        name="list_notes",
        description="List the names of every note.",
        input_schema={"type": "object", "properties": {}},
    ),
    ToolDefinition(
        name="read_note",
        description="Read one note by name.",
        input_schema={
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    ),
)


def run_tool(name: str, arguments: dict[str, Any]) -> dict[str, object]:
    if CHAIN_MODE:
        if name == "list_notes":
            return {"notes": ["start"], "hint": "other notes are reachable only by name"}
        note = CHAIN.get(str(arguments.get("name", "")))
        return {"text": note} if note else {"error": "no such note"}
    if name == "list_notes":
        return {"notes": sorted(NOTES)}
    if name == "read_note":
        note = NOTES.get(str(arguments.get("name", "")))
        return {"text": note} if note else {"error": "no such note"}
    return {"error": f"unknown tool {name}"}


def thinking_config(*, display: str | None, drop_block: bool) -> dict[str, object]:
    config: dict[str, object] = {"type": "adaptive"}
    if display is not None:
        config["display"] = display
    if drop_block:
        config["block_binding"] = {"prefix_mismatch_behavior": "drop_block"}
    return config


EFFORT = ""
CHAIN_MODE = False
#: B·A·C 가 쓰는 display. `updates` 세 세션 모두 thinking 이 **비어** 있어서, 텍스트가
#: 실린 thinking 을 재전송해도 바인딩이 유지되는지는 `summarized` 로만 볼 수 있었다.
DISPLAY = "updates"


def neos_payload(messages: tuple[CanonicalMessage, ...], system: str) -> dict[str, Any]:
    """코딩 루프가 실제로 보내는 모양. `_to_anthropic_request` 를 그대로 쓴다."""
    return _to_anthropic_request(
        ModelRequest(
            system=system,
            messages=messages,
            tools=TOOLS,
            model=MODEL,
            limits=ModelLimits(max_output_tokens=16000, timeout_sec=300, effort=EFFORT),
            task_id="k1b-probe",
            run_id="k1b-probe",
            turn_id="k1b-probe",
        )
    )


def fold_like_completed_turn(content: list[dict[str, Any]]) -> CanonicalMessage | None:
    """`DurableCodingLoop._completed_turn` 과 같은 접기.

    어댑터는 서명이 있는 `thinking` 블록만 `ThinkingCompleted` 로 올리고, 루프는
    그것을 턴 맨 앞에 두고 텍스트를 하나로 합친 뒤 도구 호출을 붙인다.
    `redacted_thinking` 은 어댑터가 모르는 블록이라 **버려진다** -- 그것도 여기서 재현한다.
    """
    thinking = [
        ThinkingContent(str(block.get("thinking", "")), str(block["signature"]))
        for block in content
        if block.get("type") == "thinking" and block.get("signature")
    ]
    text = "".join(str(b.get("text", "")) for b in content if b.get("type") == "text")
    rest: list[Any] = [TextContent(text)] if text else []
    rest += [
        ToolUseContent(str(b["id"]), str(b["name"]), dict(b.get("input") or {}))
        for b in content
        if b.get("type") == "tool_use"
    ]
    if not rest:
        return None
    return CanonicalMessage("assistant", tuple(thinking + rest))


def find_key(value: Any, key: str) -> list[Any]:
    found: list[Any] = []
    if isinstance(value, dict):
        for k, v in value.items():
            if k == key:
                found.append(v)
            found += find_key(v, key)
    elif isinstance(value, list):
        for item in value:
            found += find_key(item, key)
    return found


def block_shape(content: list[dict[str, Any]]) -> list[dict[str, object]]:
    shape: list[dict[str, object]] = []
    for block in content:
        entry: dict[str, object] = {"type": block.get("type")}
        if block.get("type") == "thinking":
            entry["chars"] = len(str(block.get("thinking", "")))
            entry["signed"] = bool(block.get("signature"))
            entry["preview"] = str(block.get("thinking", ""))[:120]
        elif block.get("type") == "text":
            entry["chars"] = len(str(block.get("text", "")))
        elif block.get("type") == "tool_use":
            entry["name"] = block.get("name")
        shape.append(entry)
    return shape


class Probe:
    def __init__(self, out: Path) -> None:
        self.client = build_async_anthropic()
        self.out = out
        self.log = (out / "calls.jsonl").open("a", encoding="utf-8")

    async def call(
        self,
        label: str,
        payload: dict[str, Any],
        *,
        thinking: dict[str, object],
        betas: set[str],
    ) -> dict[str, Any]:
        payload = dict(payload)
        headers = dict(payload.pop("extra_headers", {}) or {})
        merged = set(filter(None, headers.get("anthropic-beta", "").split(","))) | betas
        headers["anthropic-beta"] = ",".join(sorted(merged))
        record: dict[str, Any] = {
            "label": label,
            "at": datetime.now(UTC).isoformat(),
            "betas": sorted(merged),
            "thinking": thinking,
            "request": {k: v for k, v in payload.items()},
        }
        try:
            raw = await self.client.messages.with_raw_response.create(
                **payload, thinking=thinking, extra_headers=headers
            )
            body = raw.http_response.json()
            record["status"] = raw.http_response.status_code
            record["request_id"] = raw.http_response.headers.get("request-id")
        except anthropic.APIStatusError as error:
            body = {"error": error.body}
            record["status"] = error.status_code
            record["request_id"] = error.response.headers.get("request-id")
        record["response"] = body
        record["input_transformations"] = find_key(body, "input_transformations")
        record["response_keys"] = sorted(body) if isinstance(body, dict) else []
        record["shape"] = block_shape(body.get("content", []) if isinstance(body, dict) else [])
        self.log.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        self.log.flush()
        print(
            f"{label:<28} {record['status']}  transforms={record['input_transformations']!s:<14.60}"
            f" blocks={[b['type'] for b in record['shape']]}"
        )
        return record


async def main(out: Path, *, autonomous: bool, chain: bool) -> dict[str, Any]:
    global SYSTEM, USER, CHAIN_MODE
    if autonomous:
        SYSTEM, USER = SYSTEM_AUTONOMOUS, USER_LONG
    if chain:
        SYSTEM, USER, CHAIN_MODE = SYSTEM_AUTONOMOUS, USER_CHAIN, True
    probe = Probe(out)
    both = {BINDING_BETA, UPDATES_BETA}
    updates = thinking_config(display=DISPLAY, drop_block=True)

    # ── 1. NEOS 경로로 대화를 끝까지 몬다 ──────────────────────────────────
    neos: tuple[CanonicalMessage, ...] = (CanonicalMessage("user", (TextContent(USER),)),)
    raw: list[dict[str, Any]] = [{"role": "user", "content": [{"type": "text", "text": USER}]}]
    turns: list[dict[str, Any]] = []
    for turn in range(MAX_TURNS):
        record = await probe.call(
            f"B.turn{turn}", neos_payload(neos, SYSTEM), thinking=updates, betas=both
        )
        turns.append(record)
        if record["status"] != 200:
            break
        content = record["response"]["content"]
        folded = fold_like_completed_turn(content)
        if folded is None:
            break
        neos += (folded,)
        raw.append({"role": "assistant", "content": content})
        calls = [b for b in content if b.get("type") == "tool_use"]
        if not calls:
            break
        results = [(c["id"], run_tool(c["name"], c.get("input") or {})) for c in calls]
        neos += (
            CanonicalMessage(
                "tool",
                tuple(ToolResultContent(cid, "ok", result) for cid, result in results),
            ),
        )
        raw.append(
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": cid,
                        "content": json.dumps(result, separators=(",", ":")),
                        "is_error": False,
                    }
                    for cid, result in results
                ],
            }
        )

    # 마지막 턴이 도구를 부르지 않았다면 대화가 assistant 로 끝난다. 재전송하려면
    # user 턴이 하나 더 있어야 한다 -- 두 경로에 **같은** 문장을 붙인다.
    follow_up = "Thanks. In one sentence: which note was out of date?"
    if raw[-1]["role"] == "assistant":
        raw.append({"role": "user", "content": [{"type": "text", "text": follow_up}]})
        neos += (CanonicalMessage("user", (TextContent(follow_up),)),)
        turns.append(
            await probe.call("B.follow_up", neos_payload(neos, SYSTEM), thinking=updates, betas=both)
        )

    # ── 2. 원문 순서 그대로 재전송 ───────────────────────────────────────────
    raw_payload = neos_payload((), SYSTEM)
    raw_payload["messages"] = raw
    replay = await probe.call("A.raw_replay", raw_payload, thinking=updates, betas=both)

    # ── 3. 음성 대조: 앞부분을 바꾼다 ────────────────────────────────────────
    altered = SYSTEM + "\nAlways answer in English."
    control = await probe.call(
        "C.altered_system.drop_block", neos_payload(neos, altered), thinking=updates, betas=both
    )
    control_default = await probe.call(
        "C0.altered_system.default",
        neos_payload(neos, altered),
        thinking=thinking_config(display="updates", drop_block=False),
        betas={UPDATES_BETA},
    )

    # ── K4b: display 를 안 보냈을 때 ─────────────────────────────────────────
    first = (CanonicalMessage("user", (TextContent(USER),)),)
    no_display = await probe.call(
        "K4b.display_unset", neos_payload(first, SYSTEM),
        thinking=thinking_config(display=None, drop_block=False), betas=set(),
    )

    # `updates` 를 서버가 **값으로 검사하는가** -- 모르는 값이 200 이면 updates 의 200 은
    # 아무것도 증명하지 않는다.
    bogus = await probe.call(
        "K4b.display_bogus", neos_payload(first, SYSTEM),
        thinking=thinking_config(display="not-a-mode", drop_block=False), betas={UPDATES_BETA},
    )

    def thinking_blocks(record: dict[str, Any]) -> list[dict[str, object]]:
        return [b for b in record["shape"] if b["type"] in {"thinking", "redacted_thinking"}]

    def interleaved(record: dict[str, Any]) -> bool:
        """thinking 이 text·tool_use **뒤에** 오는 블록이 있는가 = 맨 앞 모음이 순서를 바꾼다."""
        seen_other = False
        for block in record["shape"]:
            if block["type"] in {"thinking", "redacted_thinking"}:
                if seen_other:
                    return True
            else:
                seen_other = True
        return False

    summary = {
        "model": MODEL,
        "mode": "chain" if chain else ("autonomous" if autonomous else "attended"),
        "effort": EFFORT or None,
        "display": DISPLAY,
        "measured_at": datetime.now(UTC).isoformat(),
        "B_neos_path": [
            {
                "label": t["label"],
                "status": t["status"],
                "input_transformations": t["input_transformations"],
                "blocks": [b["type"] for b in t["shape"]],
                "thinking_interleaved": interleaved(t),
            }
            for t in turns
        ],
        "A_raw_replay": {
            "status": replay["status"],
            "input_transformations": replay["input_transformations"],
        },
        "C_control_drop_block": {
            "status": control["status"],
            "input_transformations": control["input_transformations"],
        },
        "C0_control_default": {
            "status": control_default["status"],
            "error": control_default["response"].get("error"),
        },
        "K4b": {
            "updates_thinking_blocks": [thinking_blocks(t) for t in turns],
            "display_unset_status": no_display["status"],
            "display_unset_thinking_blocks": thinking_blocks(no_display),
            "display_bogus_status": bogus["status"],
            "display_bogus_error": bogus["response"].get("error"),
        },
        "redacted_thinking_seen": any(
            b["type"] == "redacted_thinking" for t in turns for b in t["shape"]
        ),
    }
    (out / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--autonomous", action="store_true", help="자율 모드 + 긴 과제")
    parser.add_argument("--chain", action="store_true", help="자율 모드 + 순차 사슬(병렬 불가)")
    parser.add_argument("--display", default="updates", choices=["updates", "summarized", "omitted"])
    parser.add_argument("--effort", default="", help="output_config.effort (비우면 보내지 않는다)")
    args = parser.parse_args()
    EFFORT = args.effort
    DISPLAY = args.display
    out = args.out or Path("artifacts") / "fable-k1b" / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out.mkdir(parents=True, exist_ok=True)
    result = asyncio.run(main(out, autonomous=args.autonomous, chain=args.chain))
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str)[:6000])
    print(f"\n→ {out}")
