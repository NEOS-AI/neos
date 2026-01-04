"""Multi-Hop Search Data Models

멀티홉 검색을 위한 데이터 구조 정의
"""

from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from enum import Enum

from neos.workflow.state import SearchResult


# ============================================================================
# Enums
# ============================================================================

class QuestionType(str, Enum):
    """서브질문 유형"""
    FACTUAL = "factual"              # 사실 확인: "아이폰을 만든 회사는?"
    RELATIONAL = "relational"        # 관계 추론: "X의 CEO는?"
    COMPARATIVE = "comparative"      # 비교: "A와 B의 차이는?"
    TEMPORAL = "temporal"            # 시간적: "X 이전에 한 일은?"
    SPATIAL = "spatial"              # 공간적: "X의 위치는?"


class HopStatus(str, Enum):
    """Hop 실행 상태"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


# ============================================================================
# Core Data Structures
# ============================================================================

@dataclass
class SubQuestion:
    """분해된 서브질문

    멀티홉 검색의 각 단계를 나타내는 질문

    Attributes:
        id: 질문 고유 ID (예: "q1", "q2")
        query: 실행할 쿼리 (예: "아이폰을 만든 회사는?")
        query_template: 템플릿 형식의 쿼리 (예: "{q1.answer}의 CEO는?")
        depends_on: 의존하는 질문 ID 리스트
        question_type: 질문 유형
        reasoning: 이 질문이 왜 필요한지 설명
        expected_answer_type: 예상 답변 유형 (entity, yes/no, number 등)
    """
    id: str
    query: str
    query_template: str
    depends_on: List[str] = field(default_factory=list)
    question_type: QuestionType = QuestionType.FACTUAL
    reasoning: str = ""
    expected_answer_type: str = "entity"

    def is_executable(self, completed_ids: set) -> bool:
        """이 질문이 실행 가능한지 확인

        모든 의존 질문이 완료되었을 때만 실행 가능
        """
        return all(dep_id in completed_ids for dep_id in self.depends_on)


@dataclass
class HopResult:
    """단일 Hop의 실행 결과

    Attributes:
        question_id: 실행한 질문 ID
        query_executed: 실제 실행된 쿼리 (템플릿에 답변 주입 후)
        answer: 추출된 답변
        confidence: 답변 신뢰도 (0.0 ~ 1.0)
        sources: 검색 결과 소스들
        reasoning: 어떻게 이 답변에 도달했는지 설명
        status: 실행 상태
        error_message: 실패 시 에러 메시지
        execution_time: 실행 시간 (초)
        intermediate_results: 중간 처리 결과 (디버깅용)
    """
    question_id: str
    query_executed: str
    answer: str
    confidence: float
    sources: List[SearchResult]
    reasoning: str = ""
    status: HopStatus = HopStatus.COMPLETED
    error_message: Optional[str] = None
    execution_time: float = 0.0
    intermediate_results: Dict[str, Any] = field(default_factory=dict)

    def is_successful(self) -> bool:
        """성공적으로 완료되었는지 확인"""
        return (
            self.status == HopStatus.COMPLETED
            and self.confidence >= 0.5
            and self.answer
        )


@dataclass
class ReasoningChain:
    """추론 체인 (여러 Hop의 시퀀스)

    Attributes:
        original_query: 원본 사용자 질문
        sub_questions: 분해된 서브질문들
        hop_results: 각 hop의 실행 결과
        execution_order: 실행 순서 (위상 정렬 결과)
    """
    original_query: str
    sub_questions: List[SubQuestion]
    hop_results: List[HopResult] = field(default_factory=list)
    execution_order: List[str] = field(default_factory=list)

    def get_completed_question_ids(self) -> set:
        """완료된 질문 ID 집합 반환"""
        return {
            result.question_id
            for result in self.hop_results
            if result.is_successful()
        }

    def get_answer_for_question(self, question_id: str) -> Optional[str]:
        """특정 질문의 답변 반환"""
        for result in self.hop_results:
            if result.question_id == question_id and result.is_successful():
                return result.answer
        return None

    def get_next_executable_questions(self) -> List[SubQuestion]:
        """다음에 실행 가능한 질문들 반환 (병렬 실행 가능)"""
        completed_ids = self.get_completed_question_ids()
        in_progress_ids = {
            result.question_id
            for result in self.hop_results
            if result.status == HopStatus.IN_PROGRESS
        }

        return [
            q for q in self.sub_questions
            if q.id not in completed_ids
            and q.id not in in_progress_ids
            and q.is_executable(completed_ids)
        ]


@dataclass
class MultiHopResult:
    """멀티홉 검색의 최종 결과

    Attributes:
        original_query: 원본 사용자 질문
        final_answer: 최종 통합 답변
        reasoning_chain: 추론 체인 (모든 hop 포함)
        total_confidence: 전체 신뢰도 (각 hop 신뢰도의 조화평균)
        reasoning_trace: 추론 과정 시각화 문자열
        total_sources: 모든 hop에서 사용된 소스 수
        total_execution_time: 전체 실행 시간
        metadata: 추가 메타데이터
    """
    original_query: str
    final_answer: str
    reasoning_chain: ReasoningChain
    total_confidence: float
    reasoning_trace: str = ""
    total_sources: int = 0
    total_execution_time: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def get_all_sources(self) -> List[SearchResult]:
        """모든 hop의 소스를 하나의 리스트로 반환"""
        all_sources = []
        seen_urls = set()

        for hop_result in self.reasoning_chain.hop_results:
            for source in hop_result.sources:
                # 중복 제거 (같은 URL은 한 번만)
                if source.url and source.url not in seen_urls:
                    all_sources.append(source)
                    seen_urls.add(source.url)

        return all_sources

    def get_hop_count(self) -> int:
        """실행된 hop 수 반환"""
        return len(self.reasoning_chain.hop_results)

    def get_success_rate(self) -> float:
        """성공한 hop의 비율 반환"""
        if not self.reasoning_chain.hop_results:
            return 0.0

        successful_hops = sum(
            1 for result in self.reasoning_chain.hop_results
            if result.is_successful()
        )
        return successful_hops / len(self.reasoning_chain.hop_results)


# ============================================================================
# Configuration
# ============================================================================

@dataclass
class MultiHopConfig:
    """멀티홉 검색 설정

    Attributes:
        max_hops: 최대 hop 수
        min_answer_confidence: 답변 신뢰도 최소 임계값
        enable_parallel_hops: 독립적인 서브질문 병렬 실행 허용
        reuse_intermediate_results: 중간 결과 캐싱 및 재사용
        max_retries_per_hop: hop 실패 시 최대 재시도 횟수
        timeout_per_hop: 각 hop의 최대 실행 시간 (초)
        enable_alternative_paths: 실패 시 대체 경로 탐색
    """
    max_hops: int = 5
    min_answer_confidence: float = 0.7
    enable_parallel_hops: bool = True
    reuse_intermediate_results: bool = True
    max_retries_per_hop: int = 2
    timeout_per_hop: int = 60
    enable_alternative_paths: bool = False
