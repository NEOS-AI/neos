"""CronSkill — 사용자 자연어 요청을 스케줄 태스크로 등록하는 스킬

Phase 4 (OpenClaw Cron 스케줄 스킬)

IntentType.TASK_SCHEDULING으로 분류된 쿼리를 받아
자연어 파싱 → cron 표현식 변환 → DB 저장까지 처리한다.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from neos.skills.base.skill import BaseSkill
from neos.skills.base.result import SkillResult
from neos.skills.base.types import SkillType
from neos.utils.time_utils import utc_now_naive
from .parser import parse_schedule, validate_cron_expression, ParsedSchedule

logger = logging.getLogger(__name__)


class CronSkill(BaseSkill):
    """사용자 반복 태스크 스케줄 등록 스킬.

    사용 예:
        - "매일 오전 9시 TSLA 주가 분석해줘"
        - "매주 월요일 주간 AI 트렌드 리서치해줘"
        - "매시간 환율 변동 체크해줘"

    QueryClassifier가 IntentType.TASK_SCHEDULING을 반환할 때 호출된다.
    """

    def __init__(self):
        super().__init__(
            name="cron",
            skill_type=SkillType.UTILITY,
            description="자연어로 반복 작업을 등록하여 정해진 시간에 자동 실행",
            capabilities=[
                "schedule_task",
                "list_scheduled_tasks",
                "cancel_scheduled_task",
            ],
            version="1.0.0",
        )
        self.is_available = True

    @classmethod
    def get_input_schema(cls) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "사용자 원본 쿼리 (스케줄 시간 + 실행할 작업 포함)",
                },
                "user_id": {"type": "string", "description": "사용자 ID"},
                "channel_type": {
                    "type": "string",
                    "default": "api",
                    "description": "결과 전송 채널 (api | telegram | discord | slack)",
                },
                "channel_id": {
                    "type": "string",
                    "description": "외부 채널 ID (채널 어댑터 사용 시)",
                },
                "timezone": {
                    "type": "string",
                    "default": "UTC",
                    "description": "스케줄 타임존 (예: Asia/Seoul)",
                },
                "cron_expression": {
                    "type": "string",
                    "description": "(선택) 직접 cron 표현식 지정 시 파서 건너뜀",
                },
            },
            "required": ["query", "user_id"],
        }

    async def execute(self, **kwargs) -> SkillResult:
        """스케줄 등록 실행."""
        query: str = kwargs.get("query", "")
        user_id: str = kwargs.get("user_id", "")
        channel_type: str = kwargs.get("channel_type", "api")
        channel_id: Optional[str] = kwargs.get("channel_id")
        tz: str = kwargs.get("timezone", "UTC")
        direct_cron: Optional[str] = kwargs.get("cron_expression")

        if not query or not user_id:
            return SkillResult(
                success=False,
                error="query와 user_id는 필수 입력값입니다.",
                data={},
            )

        # cron 표현식 결정
        if direct_cron:
            if not validate_cron_expression(direct_cron):
                return SkillResult(
                    success=False,
                    error=f"유효하지 않은 cron 표현식: {direct_cron}",
                    data={},
                )
            schedule = ParsedSchedule(
                cron_expression=direct_cron,
                description=f"커스텀 스케줄: {direct_cron}",
                timezone=tz,
            )
        else:
            schedule = parse_schedule(query, default_timezone=tz)
            if not schedule:
                return SkillResult(
                    success=False,
                    error=(
                        "스케줄 시간을 파싱하지 못했습니다. "
                        "'매일 오전 9시 ...', '매주 월요일 ...' 형식으로 입력해 주세요."
                    ),
                    data={"raw_query": query},
                )

        # 실행 쿼리 추출 (시간 표현 제거)
        task_query = _extract_task_query(query)

        # DB 저장
        task_record = await _save_scheduled_task(
            user_id=user_id,
            title=query[:500],
            query=task_query,
            cron_expression=schedule.cron_expression,
            timezone=schedule.timezone,
            channel_type=channel_type,
            channel_id=channel_id,
        )

        return SkillResult(
            success=True,
            data={
                "task_id": str(task_record["id"]),
                "cron_expression": schedule.cron_expression,
                "description": schedule.description,
                "next_run_at": task_record["next_run_at"].isoformat(),
                "message": (
                    f"스케줄이 등록되었습니다. "
                    f"{schedule.description}에 자동으로 실행됩니다."
                ),
            },
            metadata={
                "confidence": schedule.confidence,
                "channel_type": channel_type,
            },
        )


def _extract_task_query(full_query: str) -> str:
    """원본 쿼리에서 시간 표현을 제거하여 실제 실행 쿼리만 추출.

    예: "매일 오전 9시 TSLA 주가 분석해줘" → "TSLA 주가 분석해줘"
    """
    import re
    # 시간 표현 제거 패턴들
    time_patterns = [
        r"매일\s+(?:오전|오후)?\s*\d{1,2}시(?:\s*\d{1,2}분)?",
        r"매주\s+[가-힣]+요일?\s+(?:오전|오후)?\s*\d{1,2}시",
        r"매시간",
        r"매\s*\d+분마다",
        r"every\s+day\s+at\s+\d{1,2}(?::\d{2})?(?:\s*(?:am|pm))?",
        r"every\s+[a-z]+day\s+at\s+\d{1,2}(?::\d{2})?(?:\s*(?:am|pm))?",
        r"hourly",
    ]
    result = full_query
    for pattern in time_patterns:
        result = re.sub(pattern, "", result, flags=re.IGNORECASE).strip()
    return result or full_query


async def _save_scheduled_task(
    user_id: str,
    title: str,
    query: str,
    cron_expression: str,
    timezone: str,
    channel_type: str,
    channel_id: Optional[str],
) -> Dict[str, Any]:
    """ScheduledTask를 DB에 저장하고 레코드 정보를 반환."""
    from croniter import croniter
    from neos.database.connection import get_async_session
    from neos.database.models import ScheduledTask

    now = utc_now_naive()  # naive UTC — 폴러와 타임존 통일
    cron = croniter(cron_expression, now)
    next_run_at = cron.get_next(datetime)

    async with get_async_session() as session:
        task = ScheduledTask(
            id=uuid.uuid4(),
            user_id=user_id,
            title=title,
            query=query,
            cron_expression=cron_expression,
            timezone=timezone,
            channel_type=channel_type,
            channel_id=channel_id,
            is_active=True,
            next_run_at=next_run_at,
            run_count=0,
        )
        session.add(task)
        await session.commit()
        await session.refresh(task)

        return {
            "id": task.id,
            "next_run_at": task.next_run_at,
        }
