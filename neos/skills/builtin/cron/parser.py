"""자연어 → cron 표현식 파서

Phase 4 (OpenClaw Cron 스케줄 스킬)

한국어/영어 자연어 시간 표현을 cron 표현식으로 변환한다.
LLM 기반 파싱과 규칙 기반 패턴 매칭을 조합하여 사용한다.

cron 형식: "분 시 일 월 요일" (예: "0 9 * * *" = 매일 오전 9시)
"""

import re
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ParsedSchedule:
    """파싱된 스케줄 결과"""
    cron_expression: str
    description: str          # 사람이 읽기 쉬운 설명 (예: "매일 오전 9시")
    timezone: str = "UTC"
    confidence: float = 1.0   # 파싱 신뢰도 (0.0~1.0)


# 요일 매핑 (한국어 + 영어)
_WEEKDAY_MAP = {
    "월": "1", "월요일": "1", "monday": "1", "mon": "1",
    "화": "2", "화요일": "2", "tuesday": "2", "tue": "2",
    "수": "3", "수요일": "3", "wednesday": "3", "wed": "3",
    "목": "4", "목요일": "4", "thursday": "4", "thu": "4",
    "금": "5", "금요일": "5", "friday": "5", "fri": "5",
    "토": "6", "토요일": "6", "saturday": "6", "sat": "6",
    "일": "0", "일요일": "0", "sunday": "0", "sun": "0",
}

# 시간 표현 패턴 (한국어/영어)
_TIME_PATTERNS = [
    # 매일 HH시 MM분
    (
        r"매일\s+(?:오전|오후)?\s*(\d{1,2})시(?:\s*(\d{1,2})분)?",
        "_parse_daily_time_ko",
    ),
    # 매주 요일 HH시
    (
        r"매주\s+([가-힣]+요일?)\s+(?:오전|오후)?\s*(\d{1,2})시",
        "_parse_weekly_time_ko",
    ),
    # 매시간
    (r"매시간|매\s*시간마다|hourly", "_parse_hourly"),
    # 매 N분마다
    (r"매\s*(\d+)분마다|every\s+(\d+)\s+minutes?", "_parse_every_n_minutes"),
    # 매일 every day at HH:MM
    (
        r"every\s+day\s+at\s+(\d{1,2})(?::(\d{2}))?(?:\s*(am|pm))?",
        "_parse_daily_time_en",
    ),
    # every week on weekday at HH
    (
        r"every\s+([a-z]+day)\s+at\s+(\d{1,2})(?::(\d{2}))?(?:\s*(am|pm))?",
        "_parse_weekly_time_en",
    ),
]


def parse_schedule(natural_language: str, default_timezone: str = "UTC") -> Optional[ParsedSchedule]:
    """자연어 입력을 cron 표현식으로 변환.

    규칙 기반 패턴을 순서대로 시도하며, 매칭되지 않으면 None 반환.

    Args:
        natural_language: 사용자 입력 (예: "매일 오전 9시 TSLA 주가 분석해줘")
        default_timezone: 기본 타임존

    Returns:
        ParsedSchedule 또는 None
    """
    text = natural_language.lower().strip()

    for pattern, handler_name in _TIME_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            handler = globals().get(handler_name)
            if handler:
                result = handler(match, text, default_timezone)
                if result:
                    logger.debug(
                        "Parsed schedule '%s' → %s (handler=%s)",
                        natural_language[:50],
                        result.cron_expression,
                        handler_name,
                    )
                    return result

    logger.debug("Could not parse schedule from: %s", natural_language[:80])
    return None


def _parse_daily_time_ko(match: re.Match, text: str, tz: str) -> Optional[ParsedSchedule]:
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)

    if "오후" in text and hour < 12:
        hour += 12
    elif "오전" in text and hour == 12:
        hour = 0

    hour = max(0, min(23, hour))
    minute = max(0, min(59, minute))

    return ParsedSchedule(
        cron_expression=f"{minute} {hour} * * *",
        description=f"매일 {'오전' if hour < 12 else '오후'} {hour if hour <= 12 else hour - 12}시{''.join([f' {minute}분' if minute else ''])}",
        timezone=tz,
    )


def _normalize_weekday(raw: str) -> str:
    """요일 문자열 정규화: "월요일" → "월", "tuesday" → "tuesday".

    rstrip("일") 방식의 취약성을 제거하고 명시적 접미사 제거로 대체한다.
    "일요일" → "일요" → "일" (rstrip 방식은 "일" 단독 입력 시 빈 문자열 반환)
    """
    for suffix in ("요일", "요"):
        if raw.endswith(suffix):
            return raw[: -len(suffix)]
    return raw


def _parse_weekly_time_ko(match: re.Match, text: str, tz: str) -> Optional[ParsedSchedule]:
    raw = match.group(1).lower()
    key = _normalize_weekday(raw)
    weekday = _WEEKDAY_MAP.get(key) or _WEEKDAY_MAP.get(raw)
    if not weekday:
        return None
    weekday_label = key

    hour = int(match.group(2))
    if "오후" in text and hour < 12:
        hour += 12
    hour = max(0, min(23, hour))

    return ParsedSchedule(
        cron_expression=f"0 {hour} * * {weekday}",
        description=f"매주 {weekday_label} {hour}시",
        timezone=tz,
    )


def _parse_hourly(match: re.Match, text: str, tz: str) -> Optional[ParsedSchedule]:
    return ParsedSchedule(
        cron_expression="0 * * * *",
        description="매시간 정각",
        timezone=tz,
    )


def _parse_every_n_minutes(match: re.Match, text: str, tz: str) -> Optional[ParsedSchedule]:
    n = int(match.group(1) or match.group(2))
    if n <= 0 or n > 59:
        return None
    return ParsedSchedule(
        cron_expression=f"*/{n} * * * *",
        description=f"매 {n}분마다",
        timezone=tz,
        confidence=0.9,
    )


def _parse_daily_time_en(match: re.Match, text: str, tz: str) -> Optional[ParsedSchedule]:
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    ampm = (match.group(3) or "").lower()

    if ampm == "pm" and hour < 12:
        hour += 12
    elif ampm == "am" and hour == 12:
        hour = 0

    hour = max(0, min(23, hour))
    return ParsedSchedule(
        cron_expression=f"{minute} {hour} * * *",
        description=f"every day at {hour:02d}:{minute:02d}",
        timezone=tz,
    )


def _parse_weekly_time_en(match: re.Match, text: str, tz: str) -> Optional[ParsedSchedule]:
    weekday_str = match.group(1).lower()
    weekday = _WEEKDAY_MAP.get(weekday_str)
    if not weekday:
        return None

    hour = int(match.group(2))
    minute = int(match.group(3) or 0)
    ampm = (match.group(4) or "").lower()

    if ampm == "pm" and hour < 12:
        hour += 12
    elif ampm == "am" and hour == 12:
        hour = 0

    return ParsedSchedule(
        cron_expression=f"{minute} {hour} * * {weekday}",
        description=f"every {weekday_str} at {hour:02d}:{minute:02d}",
        timezone=tz,
    )


def validate_cron_expression(expr: str) -> bool:
    """cron 표현식 유효성 검사 (5-field 표준 cron).

    croniter를 사용하여 실제 파싱 가능 여부를 검증한다.
    """
    try:
        from croniter import croniter
        return croniter.is_valid(expr)
    except Exception:
        return False
