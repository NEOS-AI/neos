"""자연어 → cron 표현식 파서

Phase 4 (OpenClaw Cron 스케줄 스킬)

한국어/영어 자연어 시간 표현을 cron 표현식으로 변환한다.
규칙 기반 패턴 매칭을 1단계로 시도하고, 실패 시 LLM(Haiku)에 위임하는
2단계 파싱 구조를 사용한다.

cron 형식: "분 시 일 월 요일" (예: "0 9 * * *" = 매일 오전 9시)
"""

import json
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
    # 평일 HH시 (한국어)
    (
        r"평일\s*(?:마다|에|만)?\s+(?:오전|오후)?\s*(\d{1,2})시(?:\s*(\d{1,2})분)?",
        "_parse_weekday_time_ko",
    ),
    # 평일마다 (시간 없이) — 오전 9시 기본
    (r"평일\s*(?:마다|에|만)", "_parse_weekday_default_ko"),
    # 주말 HH시 (한국어)
    (
        r"주말\s*(?:마다|에|만)?\s+(?:오전|오후)?\s*(\d{1,2})시(?:\s*(\d{1,2})분)?",
        "_parse_weekend_time_ko",
    ),
    # 매달 N일 HH시
    (
        r"매달\s*(\d{1,2})일\s+(?:오전|오후)?\s*(\d{1,2})시",
        "_parse_monthly_day_ko",
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
    # every weekday at HH
    (
        r"every\s+weekday\s+at\s+(\d{1,2})(?::(\d{2}))?(?:\s*(am|pm))?",
        "_parse_weekday_time_en",
    ),
    # every weekend at HH
    (
        r"every\s+weekend\s+at\s+(\d{1,2})(?::(\d{2}))?(?:\s*(am|pm))?",
        "_parse_weekend_time_en",
    ),
    # every week on weekday at HH
    (
        r"every\s+([a-z]+day)\s+at\s+(\d{1,2})(?::(\d{2}))?(?:\s*(am|pm))?",
        "_parse_weekly_time_en",
    ),
    # every month on day N at HH
    (
        r"every\s+month\s+on\s+(?:the\s+)?(\d{1,2})(?:st|nd|rd|th)?\s+at\s+(\d{1,2})(?::(\d{2}))?(?:\s*(am|pm))?",
        "_parse_monthly_day_en",
    ),
]


def _rule_based_parse(natural_language: str, default_timezone: str = "UTC") -> Optional[ParsedSchedule]:
    """규칙 기반 패턴 매칭으로 자연어 → cron 변환 시도.

    매칭되지 않으면 None 반환.
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
                        "Rule-based parse '%s' → %s (handler=%s)",
                        natural_language[:50],
                        result.cron_expression,
                        handler_name,
                    )
                    return result

    return None


async def _llm_based_parse(natural_language: str, default_timezone: str = "UTC") -> Optional[ParsedSchedule]:
    """LLM(Haiku)을 사용하여 복잡한 자연어 표현을 cron으로 변환.

    규칙 기반 파서가 처리하지 못한 표현(격주, 매달 첫째 월요일 등)을 처리한다.
    LLM 응답을 JSON으로 파싱하고 validate_cron_expression()으로 환각을 방어한다.
    """
    from neos.config.settings import settings
    from neos.utils.llm_factory import LLMFactory

    prompt = f"""Convert the following natural language schedule expression to a standard 5-field cron expression.

Natural language: "{natural_language}"
Timezone context: {default_timezone}

Respond ONLY with a JSON object in this exact format (no markdown, no explanation):
{{"cron_expression": "<min> <hour> <dom> <month> <dow>", "description": "<human readable description in the same language as input>", "confidence": <0.0 to 1.0>}}

Rules:
- Use standard cron: minute(0-59) hour(0-23) day-of-month(1-31) month(1-12) day-of-week(0-6, 0=Sunday)
- For "every other week" or "biweekly", note that standard cron cannot express this natively; output the closest approximation and set confidence below 0.7
- For "first Monday of month": use day-of-month range trick if possible, or set confidence below 0.7
- If the expression is ambiguous or cannot be expressed in cron, set confidence to 0.0 and cron_expression to "invalid"
- description should be in Korean if the input is Korean"""

    try:
        llm = LLMFactory.create_llm(
            provider="anthropic",
            model=settings.CRON_LLM_MODEL,
            temperature=0.0,
            max_tokens=200,
        )
        response = await llm.ainvoke(prompt)
        raw_text = response.content if hasattr(response, "content") else str(response)

        # JSON 추출 (LLM이 마크다운 코드블록으로 감쌀 경우 대비)
        json_match = re.search(r'\{[^{}]+\}', raw_text, re.DOTALL)
        if not json_match:
            logger.warning("LLM cron parse: no JSON found in response for '%s'", natural_language[:50])
            return None

        data = json.loads(json_match.group())
        cron_expr = data.get("cron_expression", "").strip()
        description = data.get("description", natural_language[:80]).strip()
        confidence = float(data.get("confidence", 0.5))

        if cron_expr == "invalid" or confidence < 0.3:
            logger.debug("LLM cron parse: low confidence %.2f for '%s'", confidence, natural_language[:50])
            return None

        if not validate_cron_expression(cron_expr):
            logger.warning("LLM returned invalid cron expression '%s' for '%s'", cron_expr, natural_language[:50])
            return None

        logger.debug(
            "LLM-based parse '%s' → %s (confidence=%.2f)",
            natural_language[:50],
            cron_expr,
            confidence,
        )
        return ParsedSchedule(
            cron_expression=cron_expr,
            description=description,
            timezone=default_timezone,
            confidence=confidence,
        )

    except Exception as exc:
        logger.warning("LLM cron parse failed for '%s': %s", natural_language[:50], exc)
        return None


async def parse_schedule(natural_language: str, default_timezone: str = "UTC") -> Optional[ParsedSchedule]:
    """자연어 입력을 cron 표현식으로 변환 (2단계 파싱).

    1단계: 규칙 기반 패턴 매칭 (빠름, 고신뢰도)
    2단계: LLM 기반 파싱 (복잡 표현 처리, settings.CRON_LLM_FALLBACK_ENABLED=true 시)

    Args:
        natural_language: 사용자 입력 (예: "매일 오전 9시 TSLA 주가 분석해줘")
        default_timezone: 기본 타임존

    Returns:
        ParsedSchedule 또는 None
    """
    # 1단계: 규칙 기반
    result = _rule_based_parse(natural_language, default_timezone)
    if result:
        return result

    # 2단계: LLM 폴백
    from neos.config.settings import settings
    if settings.CRON_LLM_FALLBACK_ENABLED:
        logger.debug("Rule-based parse failed, falling back to LLM for: %s", natural_language[:80])
        return await _llm_based_parse(natural_language, default_timezone)

    logger.debug("Could not parse schedule from: %s", natural_language[:80])
    return None


# ---------------------------------------------------------------------------
# 규칙 기반 핸들러
# ---------------------------------------------------------------------------

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
        description=f"매주 {weekday_label}요일 {hour}시",
        timezone=tz,
    )


def _parse_weekday_time_ko(match: re.Match, text: str, tz: str) -> Optional[ParsedSchedule]:
    """평일(월~금) 특정 시간."""
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)

    if "오후" in text and hour < 12:
        hour += 12
    elif "오전" in text and hour == 12:
        hour = 0

    hour = max(0, min(23, hour))
    minute = max(0, min(59, minute))

    return ParsedSchedule(
        cron_expression=f"{minute} {hour} * * 1-5",
        description=f"평일(월~금) {'오전' if hour < 12 else '오후'} {hour if hour <= 12 else hour - 12}시{''.join([f' {minute}분' if minute else ''])}",
        timezone=tz,
    )


def _parse_weekday_default_ko(match: re.Match, text: str, tz: str) -> Optional[ParsedSchedule]:
    """평일마다 — 시간 표현이 없을 때 오전 9시 기본."""
    return ParsedSchedule(
        cron_expression="0 9 * * 1-5",
        description="평일(월~금) 오전 9시",
        timezone=tz,
        confidence=0.8,
    )


def _parse_weekend_time_ko(match: re.Match, text: str, tz: str) -> Optional[ParsedSchedule]:
    """주말(토·일) 특정 시간."""
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)

    if "오후" in text and hour < 12:
        hour += 12
    elif "오전" in text and hour == 12:
        hour = 0

    hour = max(0, min(23, hour))
    minute = max(0, min(59, minute))

    return ParsedSchedule(
        cron_expression=f"{minute} {hour} * * 0,6",
        description=f"주말(토·일) {'오전' if hour < 12 else '오후'} {hour if hour <= 12 else hour - 12}시{''.join([f' {minute}분' if minute else ''])}",
        timezone=tz,
    )


def _parse_monthly_day_ko(match: re.Match, text: str, tz: str) -> Optional[ParsedSchedule]:
    """매달 N일 특정 시간."""
    day = int(match.group(1))
    hour = int(match.group(2))

    if day < 1 or day > 31:
        return None

    if "오후" in text and hour < 12:
        hour += 12
    elif "오전" in text and hour == 12:
        hour = 0

    hour = max(0, min(23, hour))

    return ParsedSchedule(
        cron_expression=f"0 {hour} {day} * *",
        description=f"매달 {day}일 {hour}시",
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


def _parse_weekday_time_en(match: re.Match, text: str, tz: str) -> Optional[ParsedSchedule]:
    """every weekday at HH — 월~금."""
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    ampm = (match.group(3) or "").lower()

    if ampm == "pm" and hour < 12:
        hour += 12
    elif ampm == "am" and hour == 12:
        hour = 0

    hour = max(0, min(23, hour))
    return ParsedSchedule(
        cron_expression=f"{minute} {hour} * * 1-5",
        description=f"every weekday at {hour:02d}:{minute:02d}",
        timezone=tz,
    )


def _parse_weekend_time_en(match: re.Match, text: str, tz: str) -> Optional[ParsedSchedule]:
    """every weekend at HH — 토·일."""
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    ampm = (match.group(3) or "").lower()

    if ampm == "pm" and hour < 12:
        hour += 12
    elif ampm == "am" and hour == 12:
        hour = 0

    hour = max(0, min(23, hour))
    return ParsedSchedule(
        cron_expression=f"{minute} {hour} * * 0,6",
        description=f"every weekend at {hour:02d}:{minute:02d}",
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


def _parse_monthly_day_en(match: re.Match, text: str, tz: str) -> Optional[ParsedSchedule]:
    """every month on the Nth at HH."""
    day = int(match.group(1))
    hour = int(match.group(2))
    minute = int(match.group(3) or 0)
    ampm = (match.group(4) or "").lower()

    if day < 1 or day > 31:
        return None

    if ampm == "pm" and hour < 12:
        hour += 12
    elif ampm == "am" and hour == 12:
        hour = 0

    hour = max(0, min(23, hour))
    return ParsedSchedule(
        cron_expression=f"{minute} {hour} {day} * *",
        description=f"every month on the {day} at {hour:02d}:{minute:02d}",
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
