"""쿼리 개선 필요 여부 판단 프로세서

개선이 필요한 쿼리만 QueryRefinementAgent로 전달하여
불필요한 LLM 호출을 방지하고 비용/지연을 최소화합니다.
"""

from typing import Dict, Any
from datetime import datetime
import logging
import re

from ..state import AgentState
from neos.config.settings import settings

logger = logging.getLogger(__name__)


class RefinementChecker:
    """
    쿼리 개선 필요 여부를 빠르게 판단하는 체커

    경량 휴리스틱을 사용하여 빠르게 판단:
    - 오타 가능성 체크 (edit distance, 알려진 단어)
    - 특수문자 과다 사용
    - 참조 표현 존재
    - 길이 및 복잡도
    """

    def __init__(self):
        # 개선이 필요 없는 간단한 대화 패턴
        self.simple_patterns = [
            r"^(안녕|hello|hi|hey|감사|thank|고마워|bye|잘가).*",
            r"^(ok|okay|알겠어|알았어|네|yes)$"
        ]

        # 참조 표현 패턴
        self.reference_patterns = [
            r"\b(그것|그거|이것|이거|저것|저거)\b",
            r"\b(그|이|저)\s+(회사|기업|제품|서비스)\b",
            r"\b(앞서|이전|아까|위에서)\b",
        ]

        # 오타 가능성 지표
        self.typo_indicators = [
            r"[ㄱ-ㅎㅏ-ㅣ]{2,}",  # 자음/모음만 반복 (예: ㅋㅋㅋ)
            r"(.)\1{2,}",  # 동일 문자 3번 이상 반복 (예: !!!)
            r"[!?]{3,}",  # 특수문자 과다
        ]

    async def check(self, state: AgentState) -> Dict[str, Any]:
        """
        쿼리 개선 필요 여부 판단

        Args:
            state: 현재 워크플로우 상태

        Returns:
            업데이트할 상태 필드:
            - needs_refinement: bool (개선 필요 여부)
            - refinement_reasons: List[str] (개선이 필요한 이유들)
        """
        query = state["original_query"]
        logger.info(f"[RefinementChecker] Checking query: {query[:50]}...")

        # 매우 짧은 쿼리는 개선 불필요
        if len(query.strip()) < 5:
            logger.info("[RefinementChecker] Query too short, no refinement needed")
            return {
                "needs_refinement": False,
                "refinement_reasons": [],
                "refinement_check_time_ms": 0
            }

        start_time = datetime.now()
        reasons = []

        # 1. 간단한 대화 패턴 체크
        if self._is_simple_conversation(query):
            logger.info("[RefinementChecker] Simple conversation detected, no refinement needed")
            return {
                "needs_refinement": False,
                "refinement_reasons": [],
                "refinement_check_time_ms": self._get_elapsed_ms(start_time)
            }

        # 2. 참조 표현 체크
        if self._has_references(query):
            reasons.append("reference_resolution")
            logger.debug("[RefinementChecker] Reference expressions detected")

        # 3. 오타 가능성 체크
        if self._has_typo_indicators(query):
            reasons.append("spell_correction")
            logger.debug("[RefinementChecker] Typo indicators detected")

        # 4. 언어 표준화 필요 체크
        if self._needs_normalization(query):
            reasons.append("language_normalization")
            logger.debug("[RefinementChecker] Language normalization needed")

        # 5. TODO: 추가 판단 로직을 여기에 구현하세요
        # 예시:
        # - 쿼리 명확화 필요 여부 (단어 수, 모호한 표현 등)
        # - 특정 도메인 용어 체크
        # - 사용자 설정에 따른 조건부 체크

        needs_refinement = len(reasons) > 0
        elapsed_ms = self._get_elapsed_ms(start_time)

        logger.info(
            f"[RefinementChecker] Refinement {'needed' if needs_refinement else 'not needed'}: "
            f"{reasons} (took {elapsed_ms}ms)"
        )

        return {
            "needs_refinement": needs_refinement,
            "refinement_reasons": reasons,
            "refinement_check_time_ms": elapsed_ms
        }

    def _is_simple_conversation(self, query: str) -> bool:
        """간단한 대화인지 체크"""
        query_lower = query.lower().strip()
        return any(re.match(pattern, query_lower) for pattern in self.simple_patterns)

    def _has_references(self, query: str) -> bool:
        """참조 표현이 있는지 체크"""
        return any(re.search(pattern, query) for pattern in self.reference_patterns)

    def _has_typo_indicators(self, query: str) -> bool:
        """오타 가능성 지표가 있는지 체크"""
        return any(re.search(pattern, query) for pattern in self.typo_indicators)

    def _needs_normalization(self, query: str) -> bool:
        """
        언어 표준화가 필요한지 체크

        TODO: 비즈니스 로직을 여기에 구현하세요

        고려사항:
        - 이모티콘/특수문자 과다 사용
        - 구어체 표현 (예: "ㅋㅋ", "ㅎㅎ")
        - 비표준 약어 사용

        현재는 기본 구현만 제공:
        """
        # 기본 구현: 특수문자가 전체의 20% 이상이면 표준화 필요
        special_char_count = len(re.findall(r"[^a-zA-Z0-9가-힣\s]", query))
        total_chars = len(query.replace(" ", ""))

        if total_chars > 0:
            special_ratio = special_char_count / total_chars
            return special_ratio > 0.2

        return False

    def _get_elapsed_ms(self, start_time: datetime) -> int:
        """경과 시간 계산 (밀리초)"""
        return int((datetime.now() - start_time).total_seconds() * 1000)
