from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class MemoryItem:
    """메모리 저장 항목"""
    key: str
    content: Any
    metadata: Dict[str, Any] = field(default_factory=dict)
    score: float = 0.0  # retrieval relevance score
    created_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "content": self.content,
            "metadata": self.metadata,
            "score": self.score,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class MemoryStore(ABC):
    """메모리 저장소 추상 베이스 클래스

    3계층 메모리 아키텍처의 공통 인터페이스를 정의합니다:
    - ShortTermMemory: Redis 기반, 세션 스코프 TTL
    - LongTermMemory: PostgreSQL + pgvector, 영구 저장
    - EpisodicMemory: PostgreSQL, 연구 세션 히스토리
    """

    @abstractmethod
    async def store(
        self,
        user_id: str,
        key: str,
        value: Any,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """메모리에 항목 저장

        Args:
            user_id: 사용자 ID
            key: 메모리 키 (주제, 카테고리 등)
            value: 저장할 값
            metadata: 추가 메타데이터

        Returns:
            저장 성공 여부
        """
        ...

    @abstractmethod
    async def retrieve(
        self,
        user_id: str,
        query: str,
        limit: int = 5,
    ) -> List[MemoryItem]:
        """메모리에서 관련 항목 검색

        Args:
            user_id: 사용자 ID
            query: 검색 쿼리
            limit: 최대 반환 개수

        Returns:
            관련 MemoryItem 리스트 (score 내림차순)
        """
        ...

    @abstractmethod
    async def delete(self, user_id: str, key: str) -> bool:
        """메모리에서 항목 삭제

        Args:
            user_id: 사용자 ID
            key: 삭제할 키

        Returns:
            삭제 성공 여부
        """
        ...
