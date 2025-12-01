"""Skill types enumeration"""

from enum import Enum


class SkillType(Enum):
    """스킬 타입 열거형

    스킬의 주요 카테고리를 정의합니다.
    """

    # 문서 처리 스킬
    DOCUMENT = "document"

    # 데이터 분석 스킬
    DATA_ANALYSIS = "data_analysis"

    # API 통합 스킬
    API_INTEGRATION = "api_integration"

    # 코드 생성/분석 스킬
    CODE = "code"

    # 리서치 스킬
    RESEARCH = "research"

    # 컨텐츠 생성 스킬
    CONTENT_GENERATION = "content_generation"

    # 데이터베이스 스킬
    DATABASE = "database"

    # 커스텀 스킬
    CUSTOM = "custom"

    def __str__(self) -> str:
        return self.value
