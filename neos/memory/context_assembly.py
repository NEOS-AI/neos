"""컨텍스트 조립 엔진 (Phase 3 — OpenClaw Context Engine 분리)

MemoryManager가 반환한 raw memory_context에 대해:
- 토큰 예산 관리 (short_term → long_term → episodic 우선순위)
- 채널별 포맷팅 (api/telegram/discord/slack)
- ROMA 아티팩트 병합

ConversationContextProcessor의 메모리 조회 + 컨텍스트 조립 책임을 분리한 결과물.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# tiktoken 인코딩 (cl100k_base — Claude/GPT-4 계열과 호환)
_ENCODING = None


def _get_encoding():
    """tiktoken 인코딩을 lazy-load 한다 (첫 호출 시 다운로드)."""
    global _ENCODING
    if _ENCODING is None:
        try:
            import tiktoken
            _ENCODING = tiktoken.get_encoding("cl100k_base")
        except ImportError:
            logger.warning(
                "[ContextAssemblyEngine] tiktoken 미설치 — 문자 수 기반 근사값 사용 (토큰 수 ≈ chars/4)"
            )
    return _ENCODING


def _count_tokens(text: str) -> int:
    """텍스트의 토큰 수를 반환한다. tiktoken 미설치 시 근사값 사용."""
    enc = _get_encoding()
    if enc is not None:
        return len(enc.encode(text, disallowed_special=()))
    # fallback: 한국어(1글자 ≈ 2~3토큰)를 고려한 보수적 계수 사용
    # 영문 기준 //4이지만 한국어는 실제 토큰 수를 50~66% 과소평가함
    return len(text) // 2


def _item_to_text(item: Dict[str, Any]) -> str:
    """메모리 아이템 dict를 단일 텍스트로 직렬화한다."""
    if isinstance(item, dict):
        key = item.get("key") or item.get("topic") or ""
        value = item.get("value") or item.get("content") or item.get("summary") or ""
        if key and value:
            return f"{key}: {value}"
        return str(value or key or item)
    return str(item)


@dataclass
class AssembledContext:
    """컨텍스트 조립 결과."""
    raw: Dict[str, Any]           # MemoryManager.build_context() 원본 반환값
    trimmed: Dict[str, Any]       # 토큰 예산 적용 후 각 tier별 아이템 리스트
    formatted: str                # 채널별 포맷팅된 LLM 프롬프트용 문자열
    token_estimate: int           # formatted 문자열의 추정 토큰 수
    channel_type: str             # "api" | "telegram" | "discord" | "slack"
    metadata: Dict[str, Any] = field(default_factory=dict)


class ContextAssemblyEngine:
    """
    메모리 컨텍스트 조립 엔진

    MemoryManager.build_context()가 반환한 raw context를 받아
    토큰 예산·채널 포맷에 맞게 가공한다.

    MemoryManager는 데이터 저장/검색 책임만 유지하고,
    이 클래스가 '무엇을, 얼마나, 어떤 형식으로 모델에 넘길지'를 결정한다.
    """

    async def assemble(
        self,
        user_id: str,
        query: str,
        memory_context: Dict[str, Any],
        channel_type: str = "api",
        max_tokens: int = 8000,
        recursive_results: Optional[Dict[str, Any]] = None,
    ) -> AssembledContext:
        """
        메모리 컨텍스트를 토큰 예산·채널 포맷에 맞게 조립한다.

        Args:
            user_id: 사용자 식별자 (로깅용)
            query: 현재 쿼리 (맥락 참고용)
            memory_context: MemoryManager.build_context() 반환값
                {short_term: [...], long_term: [...], episodic: [...], has_context: bool}
            channel_type: 출력 채널 ("api", "telegram", "discord", "slack")
            max_tokens: 최대 허용 토큰 수
            recursive_results: ROMA/HyperDeep 재귀 결과 (있으면 episodic에 병합)

        Returns:
            AssembledContext
        """
        if not memory_context or not memory_context.get("has_context"):
            return AssembledContext(
                raw=memory_context or {},
                trimmed={"short_term": [], "long_term": [], "episodic": []},
                formatted="",
                token_estimate=0,
                channel_type=channel_type,
            )

        # ROMA 결과 병합
        if recursive_results:
            memory_context = self.merge_roma_artifacts(memory_context, recursive_results)

        # 토큰 예산 적용
        trimmed = self.apply_token_budget(memory_context, max_tokens)

        # 채널별 포맷팅
        formatted = self.format_for_channel(trimmed, channel_type)
        token_estimate = _count_tokens(formatted)

        logger.debug(
            f"[ContextAssemblyEngine] assembled: channel={channel_type}, "
            f"tokens≈{token_estimate}, "
            f"short_term={len(trimmed.get('short_term', []))}, "
            f"long_term={len(trimmed.get('long_term', []))}, "
            f"episodic={len(trimmed.get('episodic', []))}"
        )

        return AssembledContext(
            raw=memory_context,
            trimmed=trimmed,
            formatted=formatted,
            token_estimate=token_estimate,
            channel_type=channel_type,
            metadata={
                "user_id": user_id,
                "query_length": len(query),
                "max_tokens": max_tokens,
                "has_roma_artifacts": recursive_results is not None,
            },
        )

    def apply_token_budget(
        self, context: Dict[str, Any], max_tokens: int
    ) -> Dict[str, Any]:
        """
        토큰 예산을 초과하는 경우 우선순위 순으로 트리밍한다.

        우선순위: short_term(50%) > long_term(30%) > episodic(20%)
        각 tier 내부에서는 앞쪽(최신·고관련도) 아이템이 유지된다.

        Args:
            context: {short_term, long_term, episodic} 딕셔너리
            max_tokens: 전체 허용 토큰 예산

        Returns:
            트리밍 후 같은 구조의 딕셔너리
        """
        from neos.config.settings import settings

        st_budget = int(max_tokens * settings.CONTEXT_SHORT_TERM_RATIO)
        lt_budget = int(max_tokens * settings.CONTEXT_LONG_TERM_RATIO)
        ep_budget = int(max_tokens * settings.CONTEXT_EPISODIC_RATIO)

        result: Dict[str, Any] = {}
        for tier, budget in [
            ("short_term", st_budget),
            ("long_term", lt_budget),
            ("episodic", ep_budget),
        ]:
            items = context.get(tier, [])
            result[tier] = self._trim_tier(items, budget)

        return result

    def _trim_tier(
        self, items: List[Dict[str, Any]], token_budget: int
    ) -> List[Dict[str, Any]]:
        """단일 tier의 아이템 리스트를 토큰 예산 이하로 트리밍한다."""
        if not items:
            return []

        kept: List[Dict[str, Any]] = []
        used = 0
        for item in items:
            text = _item_to_text(item)
            cost = _count_tokens(text)
            if used + cost > token_budget:
                break
            kept.append(item)
            used += cost

        return kept

    def format_for_channel(
        self, context: Dict[str, Any], channel_type: str
    ) -> str:
        """
        채널 특성에 맞게 컨텍스트를 포맷한다.

        - api: 마크다운 완전 지원, 길이 제한 없음
        - telegram: 일반 텍스트, 4096자 제한 (메시지 분할 없이 단일 문자열)
        - discord: 마크다운 지원, 2000자 제한
        - slack: mrkdwn 형식, 3000자 권장

        Args:
            context: 트리밍된 {short_term, long_term, episodic} 딕셔너리
            channel_type: 채널 유형

        Returns:
            포맷된 문자열
        """
        if channel_type == "api":
            return self._format_api(context)
        elif channel_type == "telegram":
            return self._format_telegram(context)
        elif channel_type == "discord":
            return self._format_discord(context)
        elif channel_type == "slack":
            return self._format_slack(context)
        else:
            return self._format_api(context)

    def _format_api(self, context: Dict[str, Any]) -> str:
        """API(기본) 채널용 마크다운 포맷."""
        parts: List[str] = []

        short_term = context.get("short_term", [])
        if short_term:
            parts.append("### 현재 세션 컨텍스트")
            for item in short_term:
                parts.append(f"- {_item_to_text(item)}")

        long_term = context.get("long_term", [])
        if long_term:
            parts.append("### 학습된 지식")
            for item in long_term:
                parts.append(f"- {_item_to_text(item)}")

        episodic = context.get("episodic", [])
        if episodic:
            parts.append("### 관련 과거 연구")
            for item in episodic:
                parts.append(f"- {_item_to_text(item)}")

        return "\n".join(parts)

    def _format_telegram(self, context: Dict[str, Any]) -> str:
        """Telegram 채널용 일반 텍스트 포맷 (4096자 제한 의식)."""
        parts: List[str] = []

        for tier, label in [
            ("short_term", "[현재 세션]"),
            ("long_term", "[학습 지식]"),
            ("episodic", "[과거 연구]"),
        ]:
            items = context.get(tier, [])
            if items:
                parts.append(label)
                for item in items:
                    parts.append(f"• {_item_to_text(item)}")

        result = "\n".join(parts)
        # Telegram 단일 메시지 안전 길이
        if len(result) > 3800:
            result = result[:3797] + "..."
        return result

    def _format_discord(self, context: Dict[str, Any]) -> str:
        """Discord 채널용 마크다운 포맷 (2000자 제한)."""
        result = self._format_api(context)
        if len(result) > 1900:
            result = result[:1897] + "..."
        return result

    def _format_slack(self, context: Dict[str, Any]) -> str:
        """Slack 채널용 mrkdwn 포맷."""
        parts: List[str] = []

        for tier, label in [
            ("short_term", "*현재 세션*"),
            ("long_term", "*학습 지식*"),
            ("episodic", "*과거 연구*"),
        ]:
            items = context.get(tier, [])
            if items:
                parts.append(label)
                for item in items:
                    parts.append(f"• {_item_to_text(item)}")

        result = "\n".join(parts)
        if len(result) > 2900:
            result = result[:2897] + "..."
        return result

    def merge_roma_artifacts(
        self,
        context: Dict[str, Any],
        recursive_results: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        ROMA/HyperDeep 재귀 연구 결과를 episodic 컨텍스트에 병합한다.

        recursive_results에서 태스크 트리 요약을 추출해 episodic 앞쪽에 삽입.
        기존 episodic 아이템들은 뒤로 밀린다(최신 ROMA 결과 우선).

        Args:
            context: MemoryManager.build_context() 반환값
            recursive_results: RecursiveOrchestrator 실행 결과 dict

        Returns:
            업데이트된 context dict (shallow copy)
        """
        if not recursive_results:
            return context

        # 재귀 결과에서 요약 추출
        summary = recursive_results.get("final_response") or recursive_results.get("summary", "")
        if not summary:
            return context

        roma_item = {
            "key": "recursive_research_result",
            "value": summary[:500] + ("..." if len(summary) > 500 else ""),
            "source": "ROMA",
        }

        updated = dict(context)
        updated["episodic"] = [roma_item] + list(context.get("episodic", []))
        return updated
