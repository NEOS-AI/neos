"""Transcript budget, compaction, and artifact-ref handling for the durable loop."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Mapping
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
from neos.coding.sandbox.paths import normalize_workspace_path
from neos.coding.loop._durable.state import (
    AgentLoopState,
    COMPACT_REF_THRESHOLD_BYTES,
    CodingLoopFailure,
)
from neos.coding.loop._durable.support import (
    _has_open_tool_pair,
    _is_unchanged_stub,
    _looks_like_file_read,
    _message_to_mapping,
    _tool_result_bytes,
    _tool_use_names,
    _unchanged_stub_content,
)

logger = logging.getLogger("neos.coding.loop.durable")

_SUMMARY_TAGS = re.compile(r"<summary>(.*?)</summary>", re.DOTALL)


def _ref_tool_result(
    item: ToolResultContent,
    bodies: dict[str, str],
    *,
    tool_name: str = "",
) -> ToolResultContent:
    payload = dict(item.content)
    payload_text = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    digest = hashlib.sha256(payload_text.encode("utf-8")).hexdigest()
    preview_source = payload.get("preview")
    if not isinstance(preview_source, str) or not preview_source:
        preview_source = payload_text
    shrunk: dict[str, object] = {
        "compacted": True,
        "sha256": digest,
        "preview": preview_source[:200],
    }
    if _is_unchanged_stub(payload):
        shrunk["unchanged"] = True
    path = CompactionMixin._compact_ref_path(payload)
    if tool_name != "read_file.v1":
        bodies[digest] = payload_text
    if path is None:
        path = f"artifact://{digest}"
    shrunk["path"] = path
    return ToolResultContent(item.tool_call_id, item.status, shrunk)



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


class CompactionMixin:
    async def _compact_after_prompt_too_long(self, state: AgentLoopState) -> AgentLoopState:
        before = state.transcript
        pre = await invoke_pre_compact(self._hooks, before)
        if pre:
            before = self._append_user_meta(before, pre)
        bodies = dict(state.compacted_bodies)
        after = self._compact(before, force=True, bodies=bodies)
        after, attempts, summary = await self._maybe_llm_compact(state, after)
        if after != before:
            await self._hooks.compact(before, after)
        post = await invoke_post_compact(self._hooks, before, after)
        if post:
            after = self._append_user_meta(after, post)
        preview = self._recent_read_preview(state)
        if preview:
            after = self._append_user_meta(after, preview)
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
            | self._revealed_from_transcript(before),
        )

    def _recent_read_preview(self, state: AgentLoopState) -> str:
        paths = self._recent_read_paths(state, limit=5)
        if not paths:
            return ""
        listed = "\n".join(f"- {path}" for path in paths)
        return f"Recently read files (re-read if needed):\n{listed}"

    @staticmethod
    def _recent_read_paths(state: AgentLoopState, *, limit: int) -> tuple[str, ...]:
        pending: dict[str, str] = {}
        ordered: list[str] = []
        for message in state.transcript:
            for item in message.content:
                if isinstance(item, ToolUseContent) and item.name == "read_file.v1":
                    raw_path = item.input.get("path")
                    if raw_path:
                        pending[item.tool_call_id] = str(
                            normalize_workspace_path(str(raw_path))
                        )
                elif isinstance(item, ToolResultContent) and item.status == "ok":
                    path = pending.get(item.tool_call_id)
                    if not path:
                        continue
                    if path in ordered:
                        ordered.remove(path)
                    ordered.append(path)
        if not ordered:
            ordered = sorted(str(path) for path in state.read_paths if path)
        return tuple(ordered[-limit:])

    def _head_drop_after_prompt_too_long(self, state: AgentLoopState) -> AgentLoopState:
        remaining = list(state.transcript)
        head: tuple[CanonicalMessage, ...] = ()
        if remaining and remaining[0].role == "user":
            head = (remaining.pop(0),)
        remaining = self._drop_oldest_prefix_turn(remaining)
        after = head + tuple(remaining)
        return replace(
            state,
            transcript=after,
            transcript_digest=self._digest(after),
            prompt_compact_retries=state.prompt_compact_retries + 1,
            revealed_tools=state.revealed_tools
            | self._revealed_from_transcript(state.transcript),
        )

    async def _maybe_llm_compact(
        self, state: AgentLoopState, transcript: tuple[CanonicalMessage, ...]
    ) -> tuple[tuple[CanonicalMessage, ...], int, str]:
        attempts = state.llm_compact_attempts
        previous = (state.summary or "").strip()
        if attempts >= 1 or len(transcript) < 3:
            return transcript, attempts, previous
        head = transcript[0]
        tail_start = next(
            (
                index
                for index in range(len(transcript) - 1, -1, -1)
                if transcript[index].role == "assistant"
                and any(
                    isinstance(item, ToolUseContent)
                    for item in transcript[index].content
                )
            ),
            len(transcript),
        )
        prefix = transcript[1:tail_start]
        if not prefix:
            return transcript, attempts, previous
        # Signatures are opaque base64-like bytes: no value to the summarizer.
        blob = json.dumps(
            [_message_to_mapping(item) for item in strip_thinking(prefix)],
            ensure_ascii=False,
        )[:12_000]
        prompt = f"Summarize this transcript prefix:\n{blob}"
        if previous:
            prompt = f"Previous summary:\n{previous}\n\n{prompt}"
        preserving = self._config.compaction_preserving_summary
        if preserving:
            # P-05. 공식 지시는 "길어지더라도 완전하게" 를 요구한다 -- 상한도
            # 시간도 예전 값(512 · 30초)으로는 지킬 수 없다.
            system = COMPACTION_SUMMARY_INSTRUCTION
            limits = ModelLimits(
                self._config.compaction_summary_max_tokens,
                self._config.timeout_sec,
            )
        else:
            system = "Summarize prior coding context as facts only. <= 200 words."
            limits = ModelLimits(512, min(self._config.timeout_sec, 30))
        request = ModelRequest(
            system=system,
            messages=(
                CanonicalMessage(
                    "user",
                    (TextContent(prompt),),
                ),
            ),
            tools=(),
            model=self._config.model,
            limits=limits,
            task_id="compact",
            run_id="compact",
            turn_id=f"compact_{uuid4().hex}",
        )
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
        if pre and not open_pair:
            before = self._append_user_meta(before, pre)
        after = self._compact(before, preserve_tools=preserve_tools, bodies=bodies)
        if after != before:
            await self._hooks.compact(before, after)
        post = await invoke_post_compact(self._hooks, before, after)
        if post and not (open_pair or _has_open_tool_pair(after)):
            after = self._append_user_meta(after, post)
        return after

    def _over_budget(self, transcript) -> bool:
        return (
            len(transcript) > self._config.max_transcript_messages
            or self._serialized_bytes(transcript)
            > self._config.max_transcript_bytes
            or self._estimated_tokens(transcript)
            > self._transcript_token_limit()
        )

    def _over_bytes(self, transcript) -> bool:
        return (
            self._serialized_bytes(transcript) > self._config.max_transcript_bytes
        )

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
        active_start = next(
            (
                index
                for index in range(len(transcript) - 1, -1, -1)
                if transcript[index].role == "assistant"
                and any(
                    isinstance(item, ToolUseContent)
                    for item in transcript[index].content
                )
            ),
            None,
        )
        if active_start is None:
            prefix = transcript
            active: tuple[CanonicalMessage, ...] = ()
        else:
            prefix = transcript[:active_start]
            active = transcript[active_start:]
        stored = bodies if bodies is not None else {}
        tool_names = _tool_use_names(prefix)
        prefix = tuple(
            self._shrink_old_tool_results(message, stored, tool_names)
            for message in prefix
        )
        candidate = prefix + active
        if not force and not self._over_budget(candidate):
            return candidate
        notice = CanonicalMessage(
            "user",
            (TextContent("Prior transcript compacted; kept tool pairs."),),
        )
        head: tuple[CanonicalMessage, ...] = ()
        remaining = list(prefix)
        if remaining and remaining[0].role == "user":
            head = (remaining.pop(0),)
        if force and remaining:
            remaining = self._drop_oldest_prefix_turn(remaining)
        while remaining and self._over_budget(
            head + (notice,) + tuple(remaining) + active
        ):
            remaining = self._drop_oldest_prefix_turn(remaining)
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
        if self._serialized_bytes(transcript) > self._config.max_transcript_bytes:
            raise CodingLoopFailure(
                "transcript_budget_exceeded", retryable=False
            )
        return tuple(transcript)

    @staticmethod
    def _drop_oldest_prefix_turn(
        remaining: list[CanonicalMessage],
    ) -> list[CanonicalMessage]:
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

    @staticmethod
    def _expand_artifact_refs(transcript, bodies: Mapping[str, str]):
        if not bodies:
            return transcript
        expanded = []
        for message in transcript:
            items = []
            changed = False
            for item in message.content:
                if (
                    isinstance(item, ToolResultContent)
                    and item.content.get("compacted")
                ):
                    if _is_unchanged_stub(item.content):
                        items.append(item)
                        continue
                    digest = item.content.get("sha256")
                    raw = bodies.get(str(digest or ""))
                    if raw:
                        try:
                            restored = json.loads(raw)
                        except json.JSONDecodeError:
                            restored = None
                        if isinstance(restored, dict):
                            payload = (
                                _unchanged_stub_content(restored, item.content)
                                if _is_unchanged_stub(restored)
                                else restored
                            )
                            items.append(
                                ToolResultContent(
                                    item.tool_call_id, item.status, payload
                                )
                            )
                            changed = True
                            continue
                items.append(item)
            expanded.append(
                CanonicalMessage(message.role, tuple(items)) if changed else message
            )
        return tuple(expanded)

    @staticmethod
    def _compact_ref_path(content: Mapping[str, object]) -> str | None:
        raw = content.get("path")
        if isinstance(raw, str) and raw:
            return raw
        entries = content.get("entries")
        if isinstance(entries, (list, tuple)):
            for entry in entries:
                if isinstance(entry, Mapping):
                    path = entry.get("path")
                    if isinstance(path, str) and path:
                        return path
        return None

    @staticmethod
    def _maybe_ref_latest_tool_result(
        transcript: tuple[CanonicalMessage, ...],
        *,
        tool_name: str,
        bodies: dict[str, str],
    ) -> tuple[CanonicalMessage, ...]:
        if not transcript:
            return transcript
        last = transcript[-1]
        if last.role != "tool":
            return transcript
        content = []
        changed = False
        for item in last.content:
            if (
                isinstance(item, ToolResultContent)
                and not item.content.get("compacted")
                and not _is_unchanged_stub(item.content)
                and _tool_result_bytes(item.content) >= COMPACT_REF_THRESHOLD_BYTES
            ):
                content.append(_ref_tool_result(item, bodies, tool_name=tool_name))
                changed = True
            else:
                content.append(item)
        if not changed:
            return transcript
        return transcript[:-1] + (CanonicalMessage(last.role, tuple(content)),)

    @staticmethod
    def _shrink_old_tool_results(
        message: CanonicalMessage,
        bodies: dict[str, str],
        tool_names: Mapping[str, str] | None = None,
    ) -> CanonicalMessage:
        names = tool_names or {}
        content = []
        changed = False
        for item in message.content:
            if isinstance(item, ToolResultContent) and not item.content.get(
                "compacted"
            ):
                name = names.get(item.tool_call_id)
                if (
                    name == "read_file.v1"
                    or _is_unchanged_stub(item.content)
                    or (name is None and _looks_like_file_read(item.content))
                ):
                    content.append(item)
                    continue
                content.append(_ref_tool_result(item, bodies))
                changed = True
            else:
                content.append(item)
        if not changed:
            return message
        return CanonicalMessage(message.role, tuple(content))

    @staticmethod
    def _serialized_text(transcript) -> str:
        return json.dumps(
            [_message_to_mapping(item) for item in transcript],
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )

    @staticmethod
    def _serialized_bytes(transcript) -> int:
        return len(CompactionMixin._serialized_text(transcript).encode("utf-8"))

    @staticmethod
    def _estimated_tokens(transcript) -> int:
        return (len(CompactionMixin._serialized_text(transcript)) + 3) // 4

    @staticmethod
    def _digest(transcript):
        payload = json.dumps(
            [_message_to_mapping(item) for item in transcript],
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return hashlib.sha256(payload.encode()).hexdigest()
