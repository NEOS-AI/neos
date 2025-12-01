"""Skill execution result"""

from typing import Any, Dict, Optional, List
from dataclasses import dataclass, field
from datetime import datetime
import json


@dataclass
class SkillResult:
    """스킬 실행 결과

    스킬 실행 후 반환되는 표준화된 결과 객체입니다.

    Attributes:
        success: 실행 성공 여부
        data: 실행 결과 데이터
        error: 에러 메시지 (실패시)
        metadata: 메타데이터 (실행 시간, 사용된 리소스 등)
        timestamp: 실행 완료 시간
        skill_name: 실행된 스킬 이름
    """

    success: bool
    data: Any = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)
    skill_name: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리로 변환

        Returns:
            결과를 딕셔너리로 변환한 것
        """
        return {
            "success": self.success,
            "data": self.data,
            "error": self.error,
            "metadata": self.metadata,
            "timestamp": self.timestamp.isoformat(),
            "skill_name": self.skill_name,
        }

    def to_json(self) -> str:
        """JSON 문자열로 변환

        Returns:
            결과를 JSON 문자열로 변환한 것
        """
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    @classmethod
    def success_result(
        cls,
        data: Any,
        skill_name: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> "SkillResult":
        """성공 결과 생성

        Args:
            data: 결과 데이터
            skill_name: 스킬 이름
            metadata: 메타데이터

        Returns:
            성공 결과 객체
        """
        return cls(
            success=True,
            data=data,
            skill_name=skill_name,
            metadata=metadata or {}
        )

    @classmethod
    def error_result(
        cls,
        error: str,
        skill_name: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> "SkillResult":
        """에러 결과 생성

        Args:
            error: 에러 메시지
            skill_name: 스킬 이름
            metadata: 메타데이터

        Returns:
            에러 결과 객체
        """
        return cls(
            success=False,
            error=error,
            skill_name=skill_name,
            metadata=metadata or {}
        )
