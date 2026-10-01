"""Durable coding loop configuration, persisted state records, and limits."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from neos.coding.model.base import (
    CanonicalMessage,
    ToolCallCompleted,
)


STOP_RETRY_LIMIT = 2
EMPTY_RETRY_LIMIT = 1
STALL_DENY_AFTER = 3
COMPACT_REF_THRESHOLD_BYTES = 4096
DEFAULT_MAX_TRANSCRIPT_TOKENS = 80_000


class CodingLoopFailure(RuntimeError):
    def __init__(self, code: str, *, retryable: bool) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable


class CodingLoopWaitingApproval(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CodingLoopConfig:
    model: str
    system: str
    provider: str = "anthropic"
    max_output_tokens: int = 4096
    timeout_sec: float = 120
    tool_claim_ttl_sec: float = 30
    max_turns: int = 40
    max_tools: int = 100
    max_consecutive_tool_errors: int = 5
    max_total_tokens: int = 1_000_000
    max_cost_micros: int = 100_000_000
    input_cost_micros_per_million: int = 0
    output_cost_micros_per_million: int = 0
    cache_write_cost_micros_per_million: int = 0
    cache_read_cost_micros_per_million: int = 0
    context_window: int | None = None
    input_limit: int | None = None
    thinking_budget: int = 0
    #: 해석된 사고량(K5 ④). 빈 문자열 = 보내지 않는다 -- 요청 바이트가 이전과
    #: 같다. 해석과 게이트는 `resolve_coding_effort` 가 했다.
    effort: str = ""
    max_transcript_messages: int = 100
    max_transcript_bytes: int = 1_048_576
    max_transcript_tokens: int = DEFAULT_MAX_TRANSCRIPT_TOKENS
    max_text_delta_bytes: int = 16_384
    max_public_text_bytes: int = 1_048_576
    approval_ttl_sec: float = 900
    approval_mode: str = "manual"
    approval_deny_tools: frozenset[str] = frozenset()
    approval_allow_tools: frozenset[str] = frozenset()
    approval_always_allow: frozenset[str] = frozenset()
    approval_user_only_extra: frozenset[tuple[str, ...]] = frozenset()
    approval_unattended: bool = False
    # P-05. 끄면 LLM 컴팩션 요청이 예전과 바이트가 같다.
    compaction_preserving_summary: bool = False
    compaction_summary_max_tokens: int = 4096
    subagent_enabled: bool = False
    subagent_max_active: int = 1
    # K3. Off is park/fold: `spawn_agent.v1` holds its tool result until the
    # child folds. On is immediate return + safe-point append. Turning this on
    # is a sample boundary for the coding agent's numbers (roadmap §5.3), so it
    # stays off until A1/A2 say otherwise.
    subagent_async_spawn: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "subagent_max_active",
            min(4, max(1, self.subagent_max_active)),
        )
        numeric = (
            self.max_output_tokens,
            self.timeout_sec,
            self.tool_claim_ttl_sec,
            self.max_turns,
            self.max_tools,
            self.max_consecutive_tool_errors,
            self.max_total_tokens,
            self.max_cost_micros,
            self.max_transcript_messages,
            self.max_transcript_bytes,
            self.max_transcript_tokens,
            self.max_text_delta_bytes,
            self.max_public_text_bytes,
            self.approval_ttl_sec,
        )
        if not self.model or not self.system or any(value <= 0 for value in numeric):
            raise ValueError("coding loop configuration limits must be positive")
        if not self.provider:
            raise ValueError("coding loop provider is required")
        if not (
            self.max_text_delta_bytes
            <= self.max_public_text_bytes
            <= self.max_transcript_bytes
        ):
            raise ValueError("coding public text byte limits are invalid")
        if (
            self.input_cost_micros_per_million < 0
            or self.output_cost_micros_per_million < 0
            or self.cache_write_cost_micros_per_million < 0
            or self.cache_read_cost_micros_per_million < 0
        ):
            raise ValueError("coding model prices cannot be negative")
        if self.context_window is not None and self.context_window <= 0:
            raise ValueError("coding loop configuration limits must be positive")
        if self.input_limit is not None and self.input_limit <= 0:
            raise ValueError("coding loop configuration limits must be positive")
        if self.thinking_budget < 0:
            raise ValueError("coding loop configuration limits must be positive")


# `_CONTROL_PLANE_TOOLS` 는 여기 없다 -- 레지스트리가 도구 정체성의 주인이고,
# 사본을 두면 도구가 늘 때 한쪽만 고쳐진다(실제로 그럴 뻔했다: K3 가
# `await_subagent.v1` 을 레지스트리에만 더했을 때 루프는 못 봤다).


@dataclass(frozen=True, slots=True)
class ActiveChildRef:
    run_id: str
    checkpoint_id: str | None
    tool_call_id: str
    last_advanced_at: str  # UTC datetime.isoformat() from self._clock()
    rolled_input_tokens: int = 0
    rolled_output_tokens: int = 0
    pending_steer: str = ""
    spec: str = "explore"
    spawn_depth: int = 0
    worktree_repo: str = ""
    worktree_path: str = ""
    worktree_branch: str = ""
    worktree_base_sha: str = ""
    #: 이 자식의 보고서가 부모에게 **어떻게** 도착하는가.
    #:
    #: ``"tool_result"`` (park, 기본값): `spawn_agent.v1` 호출이 아직 pending
    #: 이고 fold 가 그 도구 결과가 된다. ``"user_message"`` (K3 비동기): 도구
    #: 결과는 spawn 때 이미 썼고 fold 는 다음 safe point 에 user 메시지로
    #: append 된다.
    #:
    #: 기본값이 park 인 것은 **옛 체크포인트를 위해서**다 -- 이 키가 없는
    #: 체크포인트는 전부 park 로 복원되어야 한다.
    delivery: str = "tool_result"

    @property
    def detached(self) -> bool:
        return self.delivery == "user_message"


@dataclass(frozen=True, slots=True)
class AgentLoopState:
    transcript: tuple[CanonicalMessage, ...]
    turn_count: int
    tool_count: int
    consecutive_tool_errors: int
    pending_tool_calls: tuple[ToolCallCompleted, ...]
    pending_tool_index: int
    transcript_digest: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_micros: int = 0
    terminal_pending: bool = False
    read_paths: frozenset[str] = frozenset()
    pending_instruction: str | None = None
    todos: tuple[Mapping[str, object], ...] = ()
    phase: str = "implement"
    instructions_loaded: bool = False
    prompt_compact_retries: int = 0
    output_token_escalations: int = 0
    llm_compact_attempts: int = 0
    summary: str = ""
    revealed_tools: frozenset[str] = frozenset()
    allowed_tools: frozenset[str] = frozenset()
    approved_always: frozenset[str] = frozenset()
    hook_retry_count: int = 0
    compacted_bodies: Mapping[str, str] = field(default_factory=dict)
    stop_retry_count: int = 0
    read_stamps: Mapping[str, Mapping[str, object]] = field(default_factory=dict)
    empty_retry_count: int = 0
    last_error_signature: str = ""
    last_error_count: int = 0
    last_success_signature: str = ""
    last_success_result_hash: str = ""
    last_success_count: int = 0
    verdict: str | None = None
    critical_files: tuple[str, ...] = ()
    active_child_run_id: str | None = None
    active_child_checkpoint_id: str | None = None
    active_child_tool_call_id: str | None = None
    active_children: tuple[ActiveChildRef, ...] = ()
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0
    last_prompt_tokens: int = 0
    # What the last model request carried: message count, and a digest of
    # system + tools + those messages. See `_guard_thinking_prefix`.
    sent_prefix_count: int = 0
    sent_prefix_digest: str = ""
    #: 태스크 소유자의 승인 규칙(트랙 Q2). **체크포인트에 싣지 않는다** -- `run()` 이 매
    #: 단계 새로 읽어 채운다(`codec._dump_loop_state` 에 없는 것이 의도다). 실행 중에
    #: 더한 block 이 다음 단계부터 걸리게.
    user_rules: tuple = ()

    @property
    def has_pending_tool(self) -> bool:
        return self.pending_tool_index < len(self.pending_tool_calls)


@dataclass(frozen=True, slots=True)
class DelegatedSpawn:
    run_id: str
    checkpoint_id: str | None
    step_kind: str
    #: 이 park 이 갱신할 `ActiveChildRef` 의 호출 id. 비어 있으면 park 을 일으킨
    #: 호출의 id 를 쓴다(기존 동작).
    #:
    #: `await_subagent.v1` 때문에 필요하다: 기다리는 호출의 id 는 자식을 띄운
    #: spawn 호출의 id 와 **다르므로**, 그대로 두면 한 run 에 ref 가 둘 생긴다.
    tool_call_id: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    spec: str = "explore"
    spawn_depth: int = 0
    worktree_repo: str = ""
    worktree_path: str = ""
    worktree_branch: str = ""
    worktree_base_sha: str = ""


@dataclass(frozen=True, slots=True)
class SpawnWork:
    kind: str
    call: ToolCallCompleted | None
    child: ActiveChildRef | None
