"""채널 게이트웨이 (Phase 1 — OpenClaw Channel Gateway)

외부 채널 어댑터로부터 ChannelMessage를 받아 NEOS 워크플로우를 직접 실행하고
최종 응답을 반환한다. HTTP 호출 없이 같은 프로세스 내에서 함수를 직접 호출한다.

채널별 circuit_breaker를 독립적으로 유지하여 특정 채널 장애가 다른 채널에
전파되지 않도록 격리한다.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    from neos.workflow.graph import MultiAgentWorkflow

from .base import ChannelMessage

logger = logging.getLogger(__name__)


class ChannelGateway:
    """
    채널 어댑터 → NEOS 워크플로우 라우팅 게이트웨이

    - 채널별 독립 circuit_breaker 유지
    - multi_agent_workflow.execute_workflow() 직접 호출 (HTTP 우회)
    - channel_source를 초기 state에 포함하여 워크플로우 시작 시점에 올바르게 기록
    """

    def __init__(self, workflow: "MultiAgentWorkflow") -> None:
        self._workflow = workflow
        # 채널별 async circuit_breaker (lazy init)
        self._breakers: Dict[str, Any] = {}

    def _get_breaker(self, channel_type: str):
        """채널 유형별 async circuit_breaker를 lazy-init하여 반환한다."""
        if channel_type not in self._breakers:
            try:
                from neos.workflow.utils.circuit_breaker import (
                    CircuitBreaker,
                    CircuitBreakerConfig,
                )
                self._breakers[channel_type] = CircuitBreaker(
                    name=f"channel_{channel_type}",
                    config=CircuitBreakerConfig(
                        failure_threshold=3,
                        timeout_seconds=60.0,
                        half_open_max_calls=1,
                    ),
                )
            except Exception as e:
                logger.warning(
                    f"[ChannelGateway] circuit_breaker init failed for {channel_type}: {e} — skipping"
                )
                self._breakers[channel_type] = None
        return self._breakers[channel_type]

    async def dispatch(self, message: ChannelMessage) -> str:
        """
        ChannelMessage를 받아 NEOS 워크플로우를 실행하고 최종 응답 텍스트를 반환한다.

        Args:
            message: 정규화된 채널 메시지

        Returns:
            LLM이 생성한 최종 응답 텍스트. 실패 시 에러 메시지 반환.
        """
        logger.info(
            f"[ChannelGateway] dispatch: channel={message.channel_type}, "
            f"user={message.user_id}, session={message.session_id}"
        )

        breaker = self._get_breaker(message.channel_type)

        try:
            if breaker is not None:
                response = await breaker.call(self._run_workflow, message)
            else:
                response = await self._run_workflow(message)
        except Exception as e:
            logger.error(
                f"[ChannelGateway] Workflow execution failed for channel={message.channel_type}: {e}"
            )
            response = "죄송합니다. 요청을 처리하는 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요."

        return response

    async def _run_workflow(self, message: ChannelMessage) -> str:
        """
        multi_agent_workflow.execute_workflow()를 직접 호출한다.

        channel_type / channel_id를 초기 상태에 포함시켜 워크플로우 전체에서
        채널 정보를 활용할 수 있게 한다 (Phase 3 ContextAssemblyEngine 연동).
        """
        from neos.config.settings import settings

        workflow_input: Dict[str, Any] = {
            "user_id": message.user_id,
            "session_id": message.session_id,
            "query": message.text,           # execute_workflow(graph.py)가 필수로 읽는 키
            "original_query": message.text,
            # Phase 3 state 필드: 채널 정보 전달
            "channel_type": message.channel_type,
            "channel_id": message.channel_id,
            # channel_source를 초기 state에 직접 포함하여 INSERT 시점에 올바르게 기록
            "channel_source": message.channel_type,
            # 채널 요청은 히스토리 컨텍스트 활성화 (세션 기반 대화 지원)
            "enable_history_context": True,
            "execution_start": datetime.utcnow(),
            "execution_steps": [],
            "errors": [],
            "structured_errors": [],
            "required_agents": [],
            "search_results": [],
            "analysis_results": [],
            "generation_results": [],
            "retry_count": 0,
        }

        # 워크플로우 실행 (checkpointer 사용 — 세션 지속성 보장)
        result = await self._workflow.execute_workflow(
            workflow_input,
            use_checkpointer=True,
        )

        final_response = result.get("final_response") or ""
        if not final_response:
            final_response = "응답을 생성하지 못했습니다. 다시 시도해주세요."

        return final_response
