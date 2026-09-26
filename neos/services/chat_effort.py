"""채팅 턴의 사고량(effort) 해석 -- 여기 한 곳.

DB 의 사용자 선호를 user 칸에, 설정의 모델별 기본값과 역할 기본값을 아래
칸에 넣고 기존 `resolve_effort` 사슬을 탄다. 두 번째 사슬을 만들지 않는다.

사용자 선호는 `conversation_id` 로 조인해 한 번에 읽는다 -- 소유자 조회를
따로 하면 첨부 없는 턴이 conversations 를 두 번 읽는다 (Fix round 2 Item 2).
"""

from __future__ import annotations

from neos.config.model_config import effort_levels_for
from neos.config.model_routing import EffortResolution, resolve_effort
from neos.config.schema import RoleEffortConfig
from neos.config.settings import settings
from neos.database.repositories.model_preference_repository import (
    ModelPreferenceRepository,
)
from neos.utils.logger import get_logger

logger = get_logger(__name__)


async def resolve_chat_effort(
    model: str, conversation_id: str | None
) -> EffortResolution:
    user_effort: str | None = None
    # 레벨을 선언하지 않은 모델은 조회하지 않는다 -- 게이트가 어차피 거절할
    # 값을 읽느라 턴마다 쿼리를 치르지 않는다.
    if conversation_id and effort_levels_for(model):
        try:
            user_effort = await ModelPreferenceRepository.get_effort_for_conversation(
                conversation_id, model
            )
        except Exception as exc:  # 선호 조회 실패가 턴을 멈추지 않는다
            logger.warning(
                "effort preference lookup failed; continuing without it "
                "(error_type=%s)",
                type(exc).__name__,
            )

    config = settings.config.model_routing.effort
    resolution = _gate_through(model, user_effort, config)
    if resolution.effort is None and resolution.refused:
        logger.warning(
            "effort refused source=%s reason=%s detail=%s",
            resolution.source.value if resolution.source else None,
            resolution.refused,
            resolution.detail,
        )
        # 거절된 칸은 비우고 다음 칸으로. 저장 후 모델이 그 레벨을 잃어도
        # 턴은 계속된다.
        if resolution.source is not None and resolution.source.value == "user":
            resolution = _gate_through(model, None, config)

    source = (
        resolution.source.value
        if resolution.effort is not None and resolution.source is not None
        else "none"
    )
    _count(source)
    logger.info("chat effort model=%s effort=%s source=%s", model, resolution.effort, source)
    return resolution


def _gate_through(
    model: str, user_effort: str | None, config: RoleEffortConfig
) -> EffortResolution:
    return resolve_effort(
        model=model,
        role="everyday",
        supported_levels=effort_levels_for(model),
        user_effort=user_effort,
        model_default=config.models.get(model),
        role_default=config.everyday,
    )


def _count(source: str) -> None:
    """라벨은 출처만 -- 모델 id 를 라벨에 싣지 않는다 (카디널리티)."""
    try:
        from neos.observability.metrics import get_metrics_collector

        get_metrics_collector().chat_effort_resolved_total.labels(source=source).inc()
    except Exception:
        return
