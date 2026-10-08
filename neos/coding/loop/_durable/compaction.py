"""Transcript budget and compaction for the durable loop.

Three escalating responses to a transcript that no longer fits:

1. `_compact` -- shrink old tool results to refs, then drop the oldest turns.
   Runs after every turn and tool result; free when under budget.
2. `_compact_after_prompt_too_long` -- the provider said no. Force (1), then
   try one LLM summary of the prefix (`_maybe_llm_compact`).
3. `_head_drop_after_prompt_too_long` -- the summary did not save us. Drop
   one turn per retry until the retry budget in the model-turn path runs out.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import replace
from uuid import uuid4

from neos.coding.model.base import (
    CanonicalMessage,
    ModelCompleted,
    ModelLimits,
    ModelRequest,
    TextContent,
    TextDelta,
    ToolResultContent,
    ToolUseContent,
    strip_thinking,
)
from neos.coding.loop.hooks import (
    invoke_post_compact,
    invoke_pre_compact,
)
from neos.coding.prompts.official import COMPACTION_SUMMARY_INSTRUCTION
from neos.coding.loop._durable import artifact_refs
from neos.coding.loop._durable.codec import (
    _estimated_tokens,
    _message_to_mapping,
    _serialized_bytes,
    _transcript_digest,
)
from neos.coding.loop._durable.state import AgentLoopState, CodingLoopFailure
from neos.coding.loop._durable.transcript import (
    _append_user_text,
    _has_open_tool_pair,
    _last_tool_use_index,
    _successful_read_paths,
    _tool_use_names,
)

logger = logging.getLogger("neos.coding.loop.durable")

_SUMMARY_TAGS = re.compile(r"<summary>(.*?)</summary>", re.DOTALL)
_COMPACTED_NOTICE = "Prior transcript compacted; kept tool pairs."
_LEGACY_SUMMARY_SYSTEM = "Summarize prior coding context as facts only. <= 200 words."
_SUMMARY_INPUT_CHARS = 12_000


def extract_preserved_summary(text: str, stop_reason: str) -> str | None:
    """보존 요약 응답에서 다음 컨텍스트에 실을 요약을 꺼낸다 (P-05).

    공식 지시는 요약을 `<summary></summary>` 로 감싸라고 한다. 반환값이
    `None` 이거나 비면 이 LLM 컴팩션은 실패로 센다 -- 호출부가 원래 transcript
    를 그대로 두고 다음 단계(헤드 드롭 등)로 넘어간다. 반환한 문자열은
    `inject_previous_summary` 로 매 턴 system 프롬프트에 실린다.

    stop_reason 은 "end_turn" 이면 끝까지 쓴 것이고 "max_tokens" 면 상한에서
    잘린 것이다.

    위험은 형식이 아니라 **불완전성**이다. 잘린 요약은 여섯 항목의 뒤쪽 --
    미해결·약속(5)과 구체값(6) -- 을 잃은 채 "완전한 요약" 처럼 매 턴 실린다.
    그것은 조용한 실패다. 버리면 헤드 드롭으로 넘어가는 시끄러운 실패가 된다.

    - 태그 쌍이 온전하다 → 안쪽. 닫는 태그 뒤에서 잘렸어도 요약은 완전하다
    - 태그 쌍 없이 잘렸다 → 버린다
    - 태그 없이 끝까지 썼다 → 전체. 형식을 어겼을 뿐 내용은 완전하다
    """
    match = _SUMMARY_TAGS.search(text)
    if match is not None:
        return match.group(1).strip()
    if stop_reason == "max_tokens":
        logger.warning(
            "compaction summary cut at its ceiling without a closing tag; "
            "discarding it (chars=%d)",
            len(text),
        )
        return None
    return text.strip()


def _drop_oldest_prefix_turn(
    remaining: list[CanonicalMessage],
) -> list[CanonicalMessage]:
    """Pop the oldest message, and with an assistant call, its results too."""
    if not remaining:
        return remaining
    first = remaining.pop(0)
    if first.role != "assistant":
        return remaining
    use_ids = {
        item.tool_call_id
        for item in first.content
        if isinstance(item, ToolUseContent)
    }
    if not use_ids:
        return remaining
    while remaining and remaining[0].role == "tool":
        result_ids = {
            item.tool_call_id
            for item in remaining[0].content
            if isinstance(item, ToolResultContent)
        }
        if result_ids and not result_ids <= use_ids:
            break
        remaining.pop(0)
    return remaining


def _split_head(
    messages,
) -> tuple[tuple[CanonicalMessage, ...], list[CanonicalMessage]]:
    """The task seed (a leading user message) is never dropped."""
    remaining = list(messages)
    if remaining and remaining[0].role == "user":
        return (remaining.pop(0),), remaining
    return (), remaining


class CompactionMixin:
    # Pure primitives, reachable through the loop because tests drive them
    # there. The implementations live in `artifact_refs` and `codec`.
    _compact_ref_path = staticmethod(artifact_refs._compact_ref_path)
    _maybe_ref_latest_tool_result = staticmethod(
        artifact_refs._maybe_ref_latest_tool_result
    )
    _shrink_old_tool_results = staticmethod(artifact_refs._shrink_old_tool_results)
    _expand_artifact_refs = staticmethod(artifact_refs._expand_artifact_refs)
    _drop_oldest_prefix_turn = staticmethod(_drop_oldest_prefix_turn)
    _serialized_bytes = staticmethod(_serialized_bytes)
    _estimated_tokens = staticmethod(_estimated_tokens)
    _digest = staticmethod(_transcript_digest)

    async def _compact_after_prompt_too_long(self, state: AgentLoopState) -> AgentLoopState:
        before = state.transcript
        pre = await invoke_pre_compact(self._hooks, before)
        if pre:
            before = _append_user_text(before, pre)
        bodies = dict(state.compacted_bodies)
        after = self._compact(before, force=True, bodies=bodies)
        after, attempts, summary = await self._maybe_llm_compact(state, after)
        if after != before:
            await self._hooks.compact(before, after)
        post = await invoke_post_compact(self._hooks, before, after)
        if post:
            after = _append_user_text(after, post)
        preview = self._recent_read_preview(state)
        if preview:
            after = _append_user_text(after, preview)
        return replace(
            state,
            transcript=after,
            transcript_digest=self._digest(after),
            prompt_compact_retries=state.prompt_compact_retries + 1,
            llm_compact_attempts=attempts,
            compacted_bodies=bodies,
            instructions_loaded=False,
            summary=summary,
            revealed_tools=state.revealed_tools
            | self._catalog.revealed_from(before),
        )

    def _recent_read_preview(self, state: AgentLoopState) -> str:
        paths = self._recent_read_paths(state, limit=5)
        if not paths:
            return ""
        listed = "\n".join(f"- {path}" for path in paths)
        return f"Recently read files (re-read if needed):\n{listed}"

    @staticmethod
    def _recent_read_paths(state: AgentLoopState, *, limit: int) -> tuple[str, ...]:
        # Most recent last, each path once.
        ordered = list(dict.fromkeys(reversed(_successful_read_paths(state.transcript))))
        ordered.reverse()
        if not ordered:
            ordered = sorted(str(path) for path in state.read_paths if path)
        return tuple(ordered[-limit:])

    def _head_drop_after_prompt_too_long(self, state: AgentLoopState) -> AgentLoopState:
        head, remaining = _split_head(state.transcript)
        after = head + tuple(_drop_oldest_prefix_turn(remaining))
        return replace(
            state,
            transcript=after,
            transcript_digest=self._digest(after),
            prompt_compact_retries=state.prompt_compact_retries + 1,
            revealed_tools=state.revealed_tools
            | self._catalog.revealed_from(state.transcript),
        )

    def _compaction_request(self, prompt: str) -> tuple[ModelRequest, bool]:
        """The summary request, and whether it asks for the preserving format."""
        preserving = self._config.compaction_preserving_summary
        if preserving:
            # P-05. 공식 지시는 "길어지더라도 완전하게" 를 요구한다 -- 상한도
            # 시간도 예전 값(512 · 30초)으로는 지킬 수 없다.
            system = COMPACTION_SUMMARY_INSTRUCTION
            limits = ModelLimits(
                self._config.compaction_summary_max_tokens,
                self._config.timeout_sec,
                # 같은 모델, 같은 사고량. 옛 요약(512 토큰)에는 싣지 않는다 --
                # 그 상한 안에서 사고량을 올리면 요약이 사고에 잘려 나간다.
                effort=self._config.effort,
            )
        else:
            system = _LEGACY_SUMMARY_SYSTEM
            limits = ModelLimits(512, min(self._config.timeout_sec, 30))
        request = ModelRequest(
            system=system,
            messages=(CanonicalMessage("user", (TextContent(prompt),)),),
            tools=(),
            model=self._config.model,
            limits=limits,
            task_id="compact",
            run_id="compact",
            turn_id=f"compact_{uuid4().hex}",
        )
        return request, preserving

    async def _maybe_llm_compact(
        self, state: AgentLoopState, transcript: tuple[CanonicalMessage, ...]
    ) -> tuple[tuple[CanonicalMessage, ...], int, str]:
        attempts = state.llm_compact_attempts
        previous = (state.summary or "").strip()
        if attempts >= 1 or len(transcript) < 3:
            return transcript, attempts, previous
        head = transcript[0]
        tail_start = _last_tool_use_index(transcript)
        if tail_start is None:
            tail_start = len(transcript)
        prefix = transcript[1:tail_start]
        if not prefix:
            return transcript, attempts, previous
        # Signatures are opaque base64-like bytes: no value to the summarizer.
        blob = json.dumps(
            [_message_to_mapping(item) for item in strip_thinking(prefix)],
            ensure_ascii=False,
        )[:_SUMMARY_INPUT_CHARS]
        prompt = f"Summarize this transcript prefix:\n{blob}"
        if previous:
            prompt = f"Previous summary:\n{previous}\n\n{prompt}"
        request, preserving = self._compaction_request(prompt)
        parts: list[str] = []
        stop_reason = ""
        try:
            async for event in self._model.stream(request):
                if isinstance(event, TextDelta):
                    parts.append(event.text)
                elif isinstance(event, ModelCompleted):
                    stop_reason = event.stop_reason
        except Exception:
            return transcript, attempts + 1, previous
        text = "".join(parts).strip()
        summary = (
            extract_preserved_summary(text, stop_reason) if preserving else text
        )
        if not summary:
            return transcript, attempts + 1, previous
        compacted = (head,) + transcript[tail_start:]
        return compacted, attempts + 1, summary

    async def _compact_with_hook(
        self, transcript, *, preserve_tools: bool = False, bodies=None
    ):
        before = tuple(transcript)
        pre = await invoke_pre_compact(self._hooks, before)
        open_pair = preserve_tools or _has_open_tool_pair(before)
        # A note between a tool call and its result would split the pair.
        if pre and not open_pair:
            before = _append_user_text(before, pre)
        after = self._compact(before, preserve_tools=preserve_tools, bodies=bodies)
        if after != before:
            await self._hooks.compact(before, after)
        post = await invoke_post_compact(self._hooks, before, after)
        if post and not (open_pair or _has_open_tool_pair(after)):
            after = _append_user_text(after, post)
        return after

    def _over_budget(self, transcript) -> bool:
        return (
            len(transcript) > self._config.max_transcript_messages
            or self._over_bytes(transcript)
            or _estimated_tokens(transcript) > self._transcript_token_limit()
        )

    def _over_bytes(self, transcript) -> bool:
        return _serialized_bytes(transcript) > self._config.max_transcript_bytes

    def _compact(
        self,
        transcript,
        *,
        preserve_tools: bool = False,
        force: bool = False,
        bodies: dict[str, str] | None = None,
    ):
        del preserve_tools
        transcript = tuple(transcript)
        if not force and not self._over_budget(transcript):
            return transcript
        # Stage 1: shrink old results. The newest tool exchange stays whole.
        active_start = _last_tool_use_index(transcript)
        if active_start is None:
            prefix, active = transcript, ()
        else:
            prefix, active = transcript[:active_start], transcript[active_start:]
        stored = bodies if bodies is not None else {}
        tool_names = _tool_use_names(prefix)
        prefix = tuple(
            artifact_refs._shrink_old_tool_results(message, stored, tool_names)
            for message in prefix
        )
        candidate = prefix + active
        if not force and not self._over_budget(candidate):
            return candidate
        # Stage 2: drop the oldest turns behind a notice.
        notice = CanonicalMessage("user", (TextContent(_COMPACTED_NOTICE),))
        head, remaining = _split_head(prefix)
        if force and remaining:
            remaining = _drop_oldest_prefix_turn(remaining)
        while remaining and self._over_budget(
            head + (notice,) + tuple(remaining) + active
        ):
            remaining = _drop_oldest_prefix_turn(remaining)
        if remaining:
            candidate = head + (notice,) + tuple(remaining) + active
        elif active:
            candidate = head + (notice,) + active
        elif head:
            candidate = head
        else:
            candidate = (notice,)
        if not self._over_budget(candidate) or not self._over_bytes(candidate):
            return candidate
        return self._require_transcript_fit(candidate)

    def _require_transcript_fit(self, transcript):
        if self._over_bytes(transcript):
            raise CodingLoopFailure(
                "transcript_budget_exceeded", retryable=False
            )
        return tuple(transcript)
