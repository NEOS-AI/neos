"""The durable coding loop: one model turn or one tool call per delivery.

Each `run` restores state from the last checkpoint, advances exactly one step,
and commits a checkpoint before yielding the event that ends it. The concerns
live in `neos.coding.loop._durable`:

- `model_turn`   -- prepare, stream, and settle one model turn
- `tools`        -- the gate chain one pending tool call passes through
- `transitions`  -- how a turn or a tool result changes loop state
- `spawn` · `spawn_claims` · `spawn_results` -- parent-mediated subagents
- `compaction` · `artifact_refs` -- keeping the transcript inside budget
- `checkpoint` · `codec` -- restoring and dumping state
- `tool_catalog` -- which tools the model is offered

This module keeps assembly, approval, and the hook calls whose timeout tests
patch here. Import the loop's public names from this module, not from
`_durable`.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from neos.coding.domain.approvals import (
    ApprovalGate,
    ApprovalMode,
    ApprovalPolicyOutcome,
    evaluate_approval,
)
from neos.coding.bridge.catalog import is_device_tool
from neos.coding.domain.events import CodingEvent
from neos.coding.domain.phases import CodingCheckpoint
from neos.coding.hooks import CodingHookPort, NullCodingHooks, post_tool_prevented
from neos.coding.loop.base import LoopDependencies, LoopInput
from neos.coding.model.base import CodingModel
from neos.coding.redact import redact_sensitive, strip_binary_payloads
from neos.coding.sandbox.bindings import SandboxBindingService
from neos.coding.sandbox.observability import CodingToolAuditEvent, NullCodingAuditSink
from neos.coding.tools.executor import SandboxToolExecutor
from neos.coding.tools.registry import CodingToolRegistry, ToolRisk
from neos.config.model_identity import usable_window_tokens
from neos.jev.gate import evaluate_approval_with_jev
from neos.coding.loop._durable.checkpoint import CheckpointMixin
from neos.coding.loop._durable.children import _select_spawn_work as _select_spawn_work
from neos.coding.loop._durable.compaction import CompactionMixin
from neos.coding.loop._durable.hook_decisions import (
    PreToolDecision,
    parse_pre_tool_decision,
)
from neos.coding.loop._durable.model_turn import (
    THINKING_PREVIEW_CHARS as THINKING_PREVIEW_CHARS,
    ModelTurnMixin,
    _request_fingerprint as _request_fingerprint,
)
from neos.coding.loop._durable.spawn import SubagentSpawnMixin
from neos.coding.loop._durable.spawn_claims import SpawnClaimsMixin
from neos.coding.loop._durable.state import (
    COMPACT_REF_THRESHOLD_BYTES as COMPACT_REF_THRESHOLD_BYTES,
    DEFAULT_MAX_TRANSCRIPT_TOKENS as DEFAULT_MAX_TRANSCRIPT_TOKENS,
    EMPTY_RETRY_LIMIT as EMPTY_RETRY_LIMIT,
    STALL_DENY_AFTER as STALL_DENY_AFTER,
    STOP_RETRY_LIMIT as STOP_RETRY_LIMIT,
    ActiveChildRef as ActiveChildRef,
    AgentLoopState as AgentLoopState,
    CodingLoopConfig as CodingLoopConfig,
    CodingLoopFailure as CodingLoopFailure,
    CodingLoopWaitingApproval as CodingLoopWaitingApproval,
    CodingLoopWaitingUser as CodingLoopWaitingUser,
    DelegatedSpawn as DelegatedSpawn,
    SpawnWork as SpawnWork,
)
from neos.coding.loop._durable.tool_catalog import ToolCatalogMixin
from neos.coding.loop._durable.tools import ToolExecutionMixin
from neos.coding.loop._durable.transcript import (
    _uniquify_tool_calls as _uniquify_tool_calls,
)
from neos.coding.loop._durable.transitions import TurnTransitionsMixin
from neos.coding.loop._durable.usage import check_usage_budgets, price_tokens
from neos.coding.loop._durable.worktree import (
    _session_on_workspace as _session_on_workspace,
)


# Read by `_pre_tool_decision` and `_execute_validated` on the core class.
# Keep both readers in this module: tests monkeypatch it on this module object.
PRE_TOOL_HOOK_TIMEOUT_SEC = 5.0


class DurableCodingLoop(
    ModelTurnMixin,
    ToolExecutionMixin,
    SubagentSpawnMixin,
    SpawnClaimsMixin,
    TurnTransitionsMixin,
    CompactionMixin,
    CheckpointMixin,
    ToolCatalogMixin,
):
    def __init__(
        self,
        *,
        model: CodingModel,
        tools: CodingToolRegistry,
        executor: SandboxToolExecutor,
        bindings: SandboxBindingService,
        config: CodingLoopConfig,
        metrics=None,
        audit=None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        approval_evaluator: Callable[..., ApprovalPolicyOutcome] = evaluate_approval,
        hooks: CodingHookPort | None = None,
        subagents=None,
        jev=None,
        monitor=None,
        envelope=None,
        user_rules=None,
        secrets=None,
        browser=None,
        device_bridge=None,
        asks=None,
    ) -> None:
        # Fields are set only here, and mixins read them through `self` on every
        # use, never a copy -- so a new instance with other arguments is the
        # whole of "the same loop, reconfigured".
        self._model = model
        self._tools = tools
        self._executor = executor
        self._bindings = bindings
        self._config = config
        self._metrics = metrics
        self._audit = audit or NullCodingAuditSink()
        self._clock = clock
        self._approval_evaluator = approval_evaluator
        self._hooks = hooks or NullCodingHooks()
        self._subagents = subagents
        # `None` 이 off 다. 루프는 설정을 읽지 않는다 -- 조립하는 쪽이 정한다.
        self._jev = jev
        # 궤적 감시자(트랙 Q5). 섀도 -- 원장에 판정을 남길 뿐 행동을 바꾸지 않는다.
        self._monitor = monitor
        # 상시 에이전트 예산 봉투(트랙 Q10a). 섀도 -- 넘으면 `budget.judged` 를 남길 뿐이다.
        self._envelope = envelope
        # 사용자 승인 규칙(트랙 Q2)의 원천. `None` 이 off 다.
        self._user_rules = user_rules
        # 사용자 비밀 금고(트랙 Q6). `None` 이 off 다 -- 참조는 문자 그대로 간다.
        self._secrets = secrets
        # 에이전트 브라우저 세션들(트랙 Q14a). `None` 이 off 다.
        self._browser = browser
        # 사용자 기기 브리지(트랙 Q16a, `DeviceBridgeService`). `None` 이 off 다.
        self._device_bridge = device_bridge
        # 묻고 기다리기(트랙 Q9, `neos.standing.asks.AgentAsks`). `None` 이 off 다 -- 에이전트
        # autonomous 태스크의 `ask_user.v1` 도 지금처럼 무인 DENY 로 접힌다.
        self._asks = asks

    async def run(
        self,
        input: LoopInput,
        checkpoint: CodingCheckpoint | None,
        deps: LoopDependencies,
    ) -> AsyncIterator[CodingEvent]:
        lease = deps.lease
        if lease is None:
            raise RuntimeError("real coding loop requires an execution lease")
        state = await self._with_user_rules(input, self._restore(input, checkpoint))
        if self._browser is not None:
            # 트랙 Q14a: 쉬었거나 오래 산 세션을 닫고, 끝난 태스크의 세션은 지금 닫는다.
            await self._browser.sweep()
            if state.terminal_pending:
                await self._browser.close(input.task_id)
        state = await self._with_device_bridge(input, state)
        if state.terminal_pending:
            return
        if state.consecutive_tool_errors >= self._config.max_consecutive_tool_errors:
            raise CodingLoopFailure("tool_error_budget_exceeded", retryable=False)
        bound = await self._bindings.resolve(lease)
        if state.has_pending_tool:
            async for event in self._advance_one_tool(input, state, bound, deps):
                yield event
            return
        async for event in self._advance_one_model_turn(input, state, bound, deps):
            yield event

    async def _commit_model(
        self,
        input,
        bound,
        deps,
        state: AgentLoopState,
        payload: Mapping[str, Any],
        *,
        event_type: str = "model.completed",
    ):
        """Commit `state` as a model-step checkpoint. Every such commit goes here."""
        return await deps.repository.commit_model_checkpoint(
            lease=deps.lease,
            event_type=event_type,
            event_payload=payload,
            loop_state=self._dump_state(input, state),
            workspace_revision=str(bound.binding.workspace_revision),
            now=self._clock(),
        )

    # -- approval ----------------------------------------------------------

    def _approval_gate(
        self,
        state: AgentLoopState,
        *,
        unattended: bool = False,
        read_only_ceiling: bool = False,
    ) -> ApprovalGate:
        """`unattended=True` 는 좁히기만 한다 -- 설정이 이미 unattended 면 그대로다.

        자식(CHILD-GATE)은 승인할 사람에게 닿을 수 없으므로 늘 이것으로 판정한다.
        """
        try:
            mode = ApprovalMode(self._config.approval_mode)
        except ValueError:
            mode = ApprovalMode.MANUAL
        return ApprovalGate(
            mode=mode,
            deny_tools=frozenset(self._config.approval_deny_tools),
            allow_tools=frozenset(self._config.approval_allow_tools),
            always_allow=frozenset(self._config.approval_always_allow),
            user_only_extra=frozenset(self._config.approval_user_only_extra),
            approved_always=state.approved_always,
            current_phase=state.phase,
            unattended=self._config.approval_unattended or unattended,
            read_only_ceiling=read_only_ceiling,
            user_rules=state.user_rules,
            secret_broker=self._secrets is not None,
            device_unattended=bool(
                getattr(state.device_bridge, "allow_unattended", False)
            ),
        )

    async def _with_user_rules(self, input: LoopInput, state: AgentLoopState) -> AgentLoopState:
        """소유자의 규칙을 이 단계의 상태에 싣는다(트랙 Q2). 저장은 하지 않는다.

        읽지 못하면 이 단계는 재시도 가능한 실패다 -- 규칙 없이 판정하면 사용자의
        block 이 조용히 빠진다.
        """
        source = self._user_rules
        owner_id = getattr(input, "owner_id", None)
        if source is None or not owner_id:
            return state
        try:
            rules = await source.list_for_user(owner_id)
        except Exception as error:  # noqa: BLE001 -- 원인과 상관없이 닫는다
            raise CodingLoopFailure("user_rules_unavailable", retryable=True) from error
        return replace(state, user_rules=tuple(rules))

    async def _with_device_bridge(
        self, input: LoopInput, state: AgentLoopState
    ) -> AgentLoopState:
        """소유자의 연결된 브리지를 이 단계의 상태에 싣는다(트랙 Q16a). 저장은 하지 않는다.

        아무도 보지 않는 런이고 브리지가 무인 읽기를 허락하지 않았으면 싣지 않는다 --
        도구가 보이지 않는다(B7). 쓰기·명령 도구는 아무도 보지 않는 런에 늘 보이지 않는다(Q16b BW4 · Q16c BC6).
        이름으로 불러도 게이트가 같은 함수로 거절한다.
        읽지 못하면 브리지가 없는 것이다(서비스가 그렇게 돌려준다 -- 좁히는 쪽).
        """
        source = self._device_bridge
        if source is None:
            return state
        from neos.coding.bridge.catalog import DEVICE_TOOLS, device_unattended_refused
        from neos.coding.loop._durable.tools import _unattended

        view = await source.view(getattr(input, "owner_id", None))
        unattended = self._config.approval_unattended or _unattended(input)
        if view is not None and device_unattended_refused(
            DEVICE_TOOLS["read_file"].tool.name,
            unattended=unattended,
            allowed=view.allow_unattended,
        ):
            view = None
        if view is not None:
            refused = frozenset(
                name
                for name in view.tools
                if name in DEVICE_TOOLS
                and device_unattended_refused(
                    DEVICE_TOOLS[name].tool.name,
                    unattended=unattended,
                    allowed=view.allow_unattended,
                )
            )
            if refused:
                view = replace(view, tools=view.tools - refused)
        return replace(state, device_bridge=view)

    def _evaluate_static_call(
        self,
        validated,
        state: AgentLoopState,
        *,
        unattended: bool = False,
        read_only_ceiling: bool = False,
    ) -> ApprovalPolicyOutcome:
        """주입된 평가기로 내는 판정. Jev 가 꺼져 있을 때의 유일한 경로다."""
        gate = self._approval_gate(
            state, unattended=unattended, read_only_ceiling=read_only_ceiling
        )
        try:
            return self._approval_evaluator(validated, gate)
        except TypeError:
            return self._approval_evaluator(validated)

    async def _evaluate_call(
        self,
        validated,
        state: AgentLoopState,
        deps=None,
        task_id: str | None = None,
        tool_call_id: str | None = None,
        *,
        unattended: bool = False,
        read_only_ceiling: bool = False,
    ) -> ApprovalPolicyOutcome:
        """정적 판정에 Jev 밴딩을 얹는다. 꺼져 있으면 정적 판정 그대로다.

        이벤트는 **부르는 쪽이 아니라 여기서** 단다. 판정이 만들어지는 자리와
        그 판정을 기록하는 자리가 갈라지면, 호출부 하나가 기록을 빠뜨려도
        아무것도 빨개지지 않는다 -- 이 저장소의 전례가 정확히 그것이다.

        `event_type=kind` 는 이 파일에 한 번만 있어야 한다:
        `tests/coding/test_event_kinds.py` 가 경로와 이름으로 이 자리를 짚는다.
        """
        if self._jev is None:
            return self._evaluate_static_call(
                validated,
                state,
                unattended=unattended,
                read_only_ceiling=read_only_ceiling,
            )

        decision = await evaluate_approval_with_jev(
            validated,
            self._approval_gate(
                state, unattended=unattended, read_only_ceiling=read_only_ceiling
            ),
            scorer=self._jev.scorer,
            thresholds=self._jev.thresholds,
            enforce=self._jev.enforce,
            static_evaluator=lambda call, _gate: self._evaluate_static_call(
                call,
                state,
                unattended=unattended,
                read_only_ceiling=read_only_ceiling,
            ),
        )
        if decision.event is not None and deps is not None and task_id is not None:
            payload = dict(decision.event)
            kind = payload.pop("kind")
            await deps.events.append(
                task_id=task_id,
                event_type=kind,
                payload={
                    **payload,
                    "tool": validated.name,
                    "tool_call_id": tool_call_id,
                },
                tool_call_id=tool_call_id,
            )
        return decision.outcome

    def _jev_blocks_speculation(self) -> bool:
        return self._jev is not None and self._jev.enforce

    @staticmethod
    def _with_answers(validated, answers) -> Any:
        """`ask_user.v1` 의 답을 **검증 뒤에** 입력에 싣는다 -- 답이 들어가는 유일한 길이다.

        스키마(`_AskUserInput`, `extra="forbid"`)에는 `answers` 가 없어서 모델은 답을
        지어낼 수 없다. 승인 카드의 답(Q9-2)과 채널의 답(Q9)이 같은 함수를 지난다 --
        사본이 둘이면 고침이 한쪽에만 도착한다.
        """
        if validated.name != "ask_user.v1":
            return validated
        if not isinstance(answers, (list, tuple)):
            return validated
        merged = dict(validated.input)
        merged["answers"] = [str(item) for item in answers]
        return replace(validated, input=merged)

    # -- hooks around execution --------------------------------------------

    async def _pre_tool_decision(self, validated) -> PreToolDecision:
        try:
            raw = await asyncio.wait_for(
                self._hooks.pre_tool(validated),
                timeout=PRE_TOOL_HOOK_TIMEOUT_SEC,
            )
        except TimeoutError:
            return "deny", "hook_timeout", None
        except Exception:
            return "deny", "hook_error", None
        return parse_pre_tool_decision(raw)

    async def close_task_browser(self, task_id: str) -> None:
        """실패·취소로 끝난 태스크의 브라우저 세션을 지금 닫는다 (트랙 Q14b X5).

        run service 의 실패·취소 자리가 부른다. 이 프로세스의 세션만 닿는다 -- 다른
        워커가 들고 있는 세션은 그 프로세스의 `sweep` 이 닫는다. 꺼져 있으면 아무 일도 없다.
        """
        if self._browser is not None:
            await self._browser.close(task_id)

    def _secret_lookup(self, owner_id):
        """소유자의 금고를 이 호출에만 묶는다 (트랙 Q6). 소유자가 없으면 풀 금고도 없다."""
        source = self._secrets
        if source is None:
            return None
        if not owner_id:

            async def nobody(names):
                from neos.coding.secrets import SecretNotFound

                raise SecretNotFound(sorted(names)[0] if names else "")

            return nobody

        async def lookup(names):
            return await source.resolve(owner_id, names)

        return lookup

    async def _execute_validated(
        self,
        bound,
        deps,
        validated,
        *,
        known_reads,
        known_stamps,
        prefetched=None,
        owner_id=None,
        task_id=None,
        unattended=False,
    ):
        try:
            if prefetched is not None:
                executed = prefetched
            elif self._device_bridge is not None and is_device_tool(validated.name):
                # 트랙 Q16a: 샌드박스가 아니라 소유자의 기기다. 실행기를 거치지 않는다.
                executed = await self._device_bridge.execute(
                    owner_id,
                    validated,
                    unattended=unattended,
                    revision=str(bound.binding.workspace_revision),
                )
            else:
                lookup = self._secret_lookup(owner_id)
                extra = {"secrets": lookup} if lookup is not None else {}
                if self._browser is not None and task_id:
                    # 이 태스크의 세션에만 닿는 손잡이(트랙 Q14a). 부모의 이 자리만 넘긴다.
                    extra["browser"] = self._browser.bind(task_id)
                executed = await self._executor.execute(
                    bound.session,
                    validated,
                    known_reads=known_reads,
                    known_stamps=known_stamps,
                    **extra,
                )
        except asyncio.CancelledError:
            raise
        except Exception as error:
            # A read-only failure is a failure; anything else may have
            # changed the workspace before it failed.
            code = (
                "tool_outcome_unknown"
                if validated.risk is not ToolRisk.READ_ONLY
                else "tool_execution_failed"
            )
            await self._audit.emit(
                CodingToolAuditEvent.from_result(
                    provider=bound.binding.provider,
                    tool=validated.name,
                    operation="execute",
                    outcome="error",
                    error_code=code,
                )
            )
            raise CodingLoopFailure(
                code, retryable=validated.risk is ToolRisk.READ_ONLY
            ) from error
        result = strip_binary_payloads(dict(executed.to_mapping()))
        rewritten = None
        try:
            rewritten = await asyncio.wait_for(
                self._hooks.post_tool(validated, result),
                timeout=PRE_TOOL_HOOK_TIMEOUT_SEC,
            )
        except Exception:
            pass
        if post_tool_prevented(rewritten):
            redacted = dict(redact_sensitive(result))
            redacted["_post_tool_prevent"] = True
            return redacted
        if isinstance(rewritten, Mapping):
            result = dict(rewritten)
        return redact_sensitive(result)

    # -- budgets and windows -----------------------------------------------

    def _price_tokens(
        self,
        input_tokens: int,
        output_tokens: int,
        *,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
    ) -> int:
        return price_tokens(
            self._config,
            input_tokens,
            output_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_write_tokens=cache_write_tokens,
        )

    def _check_usage_budgets(self, state):
        check_usage_budgets(self._config, state)

    async def _enforce_usage_budgets_after_child_spend(
        self, state, deps, bound, input, *, except_tool_call_id: str | None = None
    ) -> None:
        # Production returns on first phase.completed; a post-yield check never runs.
        try:
            self._check_usage_budgets(state)
        except CodingLoopFailure as error:
            await self.fail_all_live_spawn_claims(
                state,
                deps,
                bound,
                reason=error.code,
                task_id=input.task_id,
                except_tool_call_id=except_tool_call_id,
            )
            raise

    def _transcript_token_limit(self) -> int:
        usable = usable_window_tokens(
            context_window=self._config.context_window,
            max_output_tokens=self._config.max_output_tokens,
            input_limit=self._config.input_limit,
            thinking_budget=self._config.thinking_budget,
        )
        if usable is None:
            return self._config.max_transcript_tokens
        return usable

    def _parent_headroom_chars(self, state: AgentLoopState) -> int:
        remaining = max(
            0, self._transcript_token_limit() - max(0, state.last_prompt_tokens)
        )
        return remaining * 4

    def _utc_stamp(self) -> str:
        return self._clock().astimezone(UTC).isoformat()
