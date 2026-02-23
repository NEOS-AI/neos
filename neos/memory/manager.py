import json
import logging
from typing import Any, Dict, List, Optional

from neos.config.settings import settings
from neos.memory.base import MemoryItem
from neos.memory.short_term import ShortTermMemory
from neos.memory.long_term import LongTermMemory
from neos.memory.episodic import EpisodicMemory

logger = logging.getLogger(__name__)


class MemoryManager:
    """3계층 메모리 통합 관리자

    Short-term (Redis), Long-term (pgvector), Episodic (PostgreSQL) 메모리를
    통합하여 단일 인터페이스로 제공합니다.

    주요 메서드:
    - build_context(): 워크플로우 시작 시 호출하여 memory_context 생성
    - save_episode(): 워크플로우 완료 시 호출하여 에피소드 저장
    - store_finding(): 연구 중 핵심 발견을 단기 메모리에 저장
    - learn(): 사용자 학습 내용을 장기 메모리에 저장
    """

    def __init__(self):
        # Lazy initialization to avoid import cycles
        self._short_term: Optional[ShortTermMemory] = None
        self._long_term: Optional[LongTermMemory] = None
        self._episodic: Optional[EpisodicMemory] = None
        self._initialized = False

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        from neos.utils.cache import cache_manager
        self._short_term = ShortTermMemory(
            cache_manager,
            ttl=getattr(settings, "MEMORY_SHORT_TERM_TTL", 3600),
        )
        self._long_term = LongTermMemory()
        self._episodic = EpisodicMemory()
        self._initialized = True

    @property
    def short_term(self) -> ShortTermMemory:
        self._ensure_initialized()
        return self._short_term

    @property
    def long_term(self) -> LongTermMemory:
        self._ensure_initialized()
        return self._long_term

    @property
    def episodic(self) -> EpisodicMemory:
        self._ensure_initialized()
        return self._episodic

    async def build_context(
        self,
        user_id: str,
        query: str,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """워크플로우 시작 시 3계층 메모리에서 컨텍스트 수집

        Returns:
            memory_context dict:
                - short_term: 현재 세션 working memory 항목들
                - long_term: 관련 학습된 지식
                - episodic: 관련 과거 연구 에피소드
                - has_context: 메모리 컨텍스트 존재 여부
        """
        self._ensure_initialized()
        max_items = getattr(settings, "MEMORY_MAX_CONTEXT_ITEMS", 10)

        context: Dict[str, Any] = {
            "short_term": [],
            "long_term": [],
            "episodic": [],
            "has_context": False,
        }

        # 1. Short-term: 현재 세션 context
        if session_id:
            self._short_term.set_session(session_id)
        try:
            st_items = await self._short_term.retrieve(user_id, query, limit=max_items)
            context["short_term"] = [item.to_dict() for item in st_items]
        except Exception as e:
            logger.debug(f"Short-term memory context build failed: {e}")

        # 2. Long-term: 관련 학습 지식 (enabled일 때만)
        if getattr(settings, "MEMORY_LONG_TERM_ENABLED", True):
            try:
                lt_items = await self._long_term.retrieve(user_id, query, limit=max_items)
                context["long_term"] = [item.to_dict() for item in lt_items]
            except Exception as e:
                logger.debug(f"Long-term memory context build failed: {e}")

        # 3. Episodic: 관련 과거 연구 (enabled일 때만)
        if getattr(settings, "MEMORY_EPISODIC_ENABLED", True):
            try:
                ep_items = await self._episodic.get_related_episodes(user_id, query, limit=3)
                context["episodic"] = [item.to_dict() for item in ep_items]
            except Exception as e:
                logger.debug(f"Episodic memory context build failed: {e}")

        context["has_context"] = bool(
            context["short_term"] or context["long_term"] or context["episodic"]
        )

        if context["has_context"]:
            logger.info(
                f"Memory context built: "
                f"short_term={len(context['short_term'])}, "
                f"long_term={len(context['long_term'])}, "
                f"episodic={len(context['episodic'])}"
            )

        return context

    async def save_episode(
        self,
        user_id: str,
        session_id: str,
        query: str,
        key_findings: str,
        sources_used: List[Dict[str, Any]],
        quality_score: float,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """워크플로우 완료 시 에피소드 메모리에 저장"""
        if not getattr(settings, "MEMORY_EPISODIC_ENABLED", True):
            return False

        self._ensure_initialized()

        episode_data = {
            "query": query,
            "key_findings": key_findings,
            "sources_used": sources_used,
            "quality_score": quality_score,
        }

        return await self._episodic.store(
            user_id=user_id,
            key=session_id,
            value=episode_data,
            metadata=metadata,
        )

    async def store_finding(
        self,
        user_id: str,
        key: str,
        finding: Any,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """연구 중 핵심 발견을 단기 메모리에 저장"""
        self._ensure_initialized()
        return await self._short_term.store(user_id, key, finding, metadata)

    async def learn(
        self,
        user_id: str,
        key: str,
        knowledge: Any,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """사용자 학습 내용을 장기 메모리에 저장"""
        if not getattr(settings, "MEMORY_LONG_TERM_ENABLED", True):
            return False

        self._ensure_initialized()
        return await self._long_term.store(user_id, key, knowledge, metadata)


# 전역 MemoryManager 인스턴스
memory_manager = MemoryManager()
