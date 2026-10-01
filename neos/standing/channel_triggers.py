"""채널 원천 트리거 -- 트랙 Q4b (docs/Q2_Q4B_RULES_CHANNEL_TRIGGERS_DESIGN_261001.md §3).

지정한 채널의 메시지가 에이전트의 background 태스크가 된다. 어댑터(slack · discord ·
telegram)는 대화 게이트(`evaluate_channel_gate`)를 부르기 **직전에**
`observe_channel_message` 를 부른다.

- **대화 경로와 독립이다(결정 D5).** 트리거는 부작용으로만 돈다. 대화 게이트의 판정은
  그대로다 -- 멘션이 있으면 대화 응답도 받고, 없으면(require_mention) 대화는 버려진다.
  트리거가 실패해도 대화는 영향을 받지 않는다.
- **발신자(결정 D4):** 소유자에게 매핑된 사람(`channels.principals`) 또는 트리거의
  `allowed_senders`. 봇·NEOS 자신은 언제나 아니다 -- 에이전트끼리 서로 깨우는 고리를 막는다.
- **운영자의 채널 정책은 트리거에도 걸린다.** `ignored_channels` 에 있거나
  `allowed_channels` 밖의 채널은 트리거도 보지 않는다(좁히기만).
- 본문은 메시지를 JSON 으로 감싼 것이고 `fire_trigger` 가 untrusted 로 감싼다. 필터는 그
  JSON 의 경로로 건다(예: `{"path": "thread_id", "equals": null}` -- 스레드 답글 제외).
- 같은 메시지는 태스크 하나다: 배달 id = `{channel_id}:{message_id}`.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from neos.api.channels.authz import ChannelGatePolicy, GateContext
from neos.api.channels.inbound_idempotency import ChannelInboundIdempotencyStore
from neos.api.channels.principals import resolve_channel_principal
from neos.standing.budget import AgentBudgetEnvelope
from neos.standing.store import StandingAgentStore
from neos.standing.tasks import TaskOpener
from neos.standing.triggers import StandingTrigger, TriggerFiring, TriggerStore, fire_trigger

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ChannelInbound:
    channel_type: str
    channel_id: str
    platform_user_id: str
    message_id: str
    text: str
    thread_id: str | None = None


def channel_admitted(ctx: GateContext, policy: ChannelGatePolicy) -> bool:
    """대화 게이트 중 **채널**과 **발신자 종류**에 관한 것만. 멘션·allowed_users 는 대화의
    규칙이라 보지 않는다 -- 트리거의 발신자 규칙은 따로다."""
    if ctx.is_bot or ctx.is_self:
        return False
    if ctx.channel_id in policy.ignored_channels:
        return False
    return not policy.allowed_channels or ctx.channel_id in policy.allowed_channels


def sender_admitted(trigger: StandingTrigger, inbound: ChannelInbound, channels: Any) -> bool:
    channel = trigger.channel
    if channel is None:
        return False
    # 빈 발신자 id 는 따로 막지 않는다: 허용 목록은 빈 id 를 받지 않고(`parse_allowed_senders`)
    # principals 도 빈 id 를 매핑하지 않는다(`resolve_channel_principal`).
    if inbound.platform_user_id in channel.allowed_senders:
        return True
    owner = resolve_channel_principal(
        platform=inbound.channel_type,
        platform_user_id=inbound.platform_user_id,
        channels=channels,
    )
    return owner is not None and owner == trigger.owner_id


def channel_body(inbound: ChannelInbound) -> bytes:
    return json.dumps(
        {
            "channel_type": inbound.channel_type,
            "channel_id": inbound.channel_id,
            "sender": inbound.platform_user_id,
            "thread_id": inbound.thread_id,
            "text": inbound.text,
        },
        ensure_ascii=False,
    ).encode()


async def fire_channel_triggers(
    inbound: ChannelInbound,
    *,
    agents: StandingAgentStore,
    triggers: TriggerStore,
    coding: TaskOpener,
    idempotency: ChannelInboundIdempotencyStore,
    channels: Any,
    envelope: AgentBudgetEnvelope | None = None,
) -> list[tuple[str, TriggerFiring]]:
    """이 채널의 트리거 중 발신자가 허락된 것마다 한 번. (trigger_id, 결과) 목록."""
    results = []
    for trigger in await triggers.list_for_channel(inbound.channel_type, inbound.channel_id):
        if not sender_admitted(trigger, inbound, channels):
            continue
        firing = await fire_trigger(
            agents,
            coding,
            idempotency,
            trigger,
            delivery_id=f"{inbound.channel_id}:{inbound.message_id}",
            body=channel_body(inbound),
            envelope=envelope,
        )
        results.append((trigger.trigger_id, firing))
    return results


async def observe_channel_message(
    ctx: GateContext, *, message_id: str, thread_id: str | None = None
) -> None:
    """어댑터가 대화 게이트 직전에 부른다. **무엇이 일어나도 던지지 않는다.**

    `standing_agents.enabled` 와 `standing_agents.triggers.enabled` 가 둘 다 켜져야 돈다.
    """
    try:
        from neos.config.settings import settings

        config = settings.config
        if not (config.standing_agents.enabled and config.standing_agents.triggers.enabled):
            return
        if not message_id or not ctx.text.strip():
            return
        from neos.api.channels.authz import resolve_channel_policy

        if not channel_admitted(ctx, resolve_channel_policy(ctx.channel_type, config.channels)):
            return
        from neos.api.channels.inbound_idempotency import PostgresChannelInboundIdempotencyStore
        from neos.coding.runtime import coding_service
        from neos.database.connection import db_manager
        from neos.standing.budget import build_agent_envelope
        from neos.standing.store import PostgresStandingAgentStore
        from neos.standing.triggers import PostgresTriggerStore

        results = await fire_channel_triggers(
            ChannelInbound(
                channel_type=ctx.channel_type,
                channel_id=ctx.channel_id,
                platform_user_id=ctx.platform_user_id,
                message_id=message_id,
                text=ctx.text,
                thread_id=thread_id,
            ),
            agents=PostgresStandingAgentStore(db_manager.get_session),
            triggers=PostgresTriggerStore(db_manager.get_session),
            coding=coding_service,
            idempotency=PostgresChannelInboundIdempotencyStore(db_manager.get_session),
            channels=config.channels,
            envelope=build_agent_envelope(config.standing_agents, db_manager.get_session),
        )
        for trigger_id, firing in results:
            logger.info(
                "standing channel trigger trigger_id=%s status=%s reason=%s task_id=%s",
                trigger_id, firing.status, firing.reason, firing.task_id,
            )
    except Exception:  # noqa: BLE001 -- 트리거는 대화를 막지 못한다
        logger.warning("standing channel trigger failed", exc_info=True)
