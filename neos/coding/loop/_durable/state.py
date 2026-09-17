"""Durable coding loop configuration, persisted state records, and limits."""

from __future__ import annotations

import re
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
_UNCHANGED_PREVIEW = "File unchanged since last read."
_THINK_CLOSED_RE = re.compile(
    r"<(think|thinking|reasoning)\b[^>]*>.*?</\1>",
    re.IGNORECASE | re.DOTALL,
)
_THINK_UNCLOSED_RE = re.compile(
    r"<(think|thinking|reasoning)\b[^>]*>.*\Z",
    re.IGNORECASE | re.DOTALL,
)
_BRIEF_PLACEHOLDER_RE = re.compile(r"<[A-Za-z_][A-Za-z0-9_]*>")
_STUB_GOALS = frozenset({"TODO", "TBD"})


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
    approval_unattended: bool = False
    subagent_enabled: bool = False
    subagent_max_active: int = 1

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


_EPOCH_STAMP = "1970-01-01T00:00:00+00:00"
_STALE_SLACK_SEC = 30.0


@dataclass(frozen=True, slots=True)
class _AppliedPendingCommand:
    transcript: tuple[CanonicalMessage, ...]
    bodies: dict[str, str]
    todos: tuple
    instructions_loaded: bool


_CONTROL_PLANE_TOOLS = frozenset({"subagent_list.v1", "subagent_steer.v1"})


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

    @property
    def has_pending_tool(self) -> bool:
        return self.pending_tool_index < len(self.pending_tool_calls)


@dataclass(frozen=True, slots=True)
class DelegatedSpawn:
    run_id: str
    checkpoint_id: str | None
    step_kind: str
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
