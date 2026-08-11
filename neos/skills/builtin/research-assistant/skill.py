"""Research Assistant Skill implementation"""

from typing import Dict, Any, List
import logging
import re

from neos.skills.base import BaseSkill, SkillResult, SkillType


logger = logging.getLogger(__name__)


class ResearchAssistantSkill(BaseSkill):
    """리서치 작업 보조 스킬"""

    def __init__(self, **kwargs):
        super().__init__(
            name="research-assistant",
            skill_type=SkillType.RESEARCH,
            description="리서치 작업 보조 - 소스 분석, 요약, 참고문헌 정리",
            capabilities=[
                "source_analysis",
                "text_summarization",
                "reference_extraction",
                "insight_generation",
                "research_support",
            ],
            version="1.0.0",
            **kwargs
        )

    async def initialize(self) -> bool:
        """스킬 초기화"""
        self.is_available = True
        logger.info("Research Assistant skill initialized successfully")
        return True

    async def execute(self, params: Dict[str, Any]) -> SkillResult:
        """리서치 작업 실행

        Args:
            params: {
                "action": str,  # "analyze_source", "summarize", "extract_references"
                "content": str,  # 분석할 내용
                "options": dict (optional),  # 추가 옵션
            }

        Returns:
            작업 실행 결과
        """
        if not self.is_available:
            return SkillResult.error_result(
                error="Research Assistant skill not initialized",
                skill_name=self.name,
            )

        action = params.get("action")
        if not action:
            return SkillResult.error_result(
                error="Action parameter is required",
                skill_name=self.name,
            )

        if action == "analyze_source":
            return await self._analyze_source(params)
        elif action == "summarize":
            return await self._summarize_text(params)
        elif action == "extract_references":
            return await self._extract_references(params)
        else:
            return SkillResult.error_result(
                error=f"Unknown action: {action}",
                skill_name=self.name,
            )

    async def _analyze_source(self, params: Dict[str, Any]) -> SkillResult:
        """소스 분석 및 품질 평가"""
        content = params.get("content", "")
        options = params.get("options", {})

        if not content:
            return SkillResult.error_result(
                error="Content parameter is required",
                skill_name=self.name,
            )

        try:
            analysis = {
                "content_length": len(content),
                "word_count": len(content.split()),
                "has_citations": self._has_citations(content),
                "has_data": self._has_numerical_data(content),
                "has_links": self._has_links(content),
            }

            # 품질 점수 계산 (0-100)
            quality_score = 0
            if analysis["content_length"] > 500:
                quality_score += 20
            if analysis["has_citations"]:
                quality_score += 30
            if analysis["has_data"]:
                quality_score += 25
            if analysis["has_links"]:
                quality_score += 25

            analysis["quality_score"] = quality_score

            # 핵심 포인트 추출
            if options.get("extract_key_points"):
                analysis["key_points"] = self._extract_key_points(content)

            return SkillResult.success_result(
                data=analysis,
                skill_name=self.name,
                metadata={"action": "analyze_source"},
            )

        except Exception as e:
            logger.error(f"Failed to analyze source: {e}")
            return SkillResult.error_result(
                error=str(e),
                skill_name=self.name,
            )

    async def _summarize_text(self, params: Dict[str, Any]) -> SkillResult:
        """텍스트 요약"""
        content = params.get("content", "")
        options = params.get("options", {})
        max_length = options.get("max_length", 500)

        if not content:
            return SkillResult.error_result(
                error="Content parameter is required",
                skill_name=self.name,
            )

        try:
            # 간단한 추출 요약 (문장 단위)
            sentences = re.split(r'[.!?]+', content)
            sentences = [s.strip() for s in sentences if len(s.strip()) > 20]

            # 상위 문장 선택 (길이 기반)
            summary_sentences = sentences[:3]  # 처음 3문장
            summary = ". ".join(summary_sentences) + "."

            # 길이 제한
            if len(summary) > max_length:
                summary = summary[:max_length] + "..."

            return SkillResult.success_result(
                data={
                    "summary": summary,
                    "original_length": len(content),
                    "summary_length": len(summary),
                    "compression_ratio": len(summary) / len(content),
                },
                skill_name=self.name,
                metadata={"action": "summarize"},
            )

        except Exception as e:
            logger.error(f"Failed to summarize text: {e}")
            return SkillResult.error_result(
                error=str(e),
                skill_name=self.name,
            )

    async def _extract_references(self, params: Dict[str, Any]) -> SkillResult:
        """참고문헌 추출"""
        content = params.get("content", "")

        if not content:
            return SkillResult.error_result(
                error="Content parameter is required",
                skill_name=self.name,
            )

        try:
            # URL 추출
            url_pattern = r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+'
            urls = re.findall(url_pattern, content)

            # DOI 추출
            doi_pattern = r'10\.\d{4,9}/[-._;()/:A-Z0-9]+'
            dois = re.findall(doi_pattern, content, re.IGNORECASE)

            # 인용 패턴 추출 (예: [1], (Author, Year))
            citation_pattern = r'\[(\d+)\]|\(([A-Za-z]+,\s*\d{4})\)'
            citations = re.findall(citation_pattern, content)

            return SkillResult.success_result(
                data={
                    "urls": list(set(urls)),
                    "dois": list(set(dois)),
                    "citations": citations,
                    "total_references": len(urls) + len(dois),
                },
                skill_name=self.name,
                metadata={"action": "extract_references"},
            )

        except Exception as e:
            logger.error(f"Failed to extract references: {e}")
            return SkillResult.error_result(
                error=str(e),
                skill_name=self.name,
            )

    def _has_citations(self, content: str) -> bool:
        """인용이 있는지 확인"""
        citation_patterns = [
            r'\[\d+\]',  # [1], [2]
            r'\([A-Za-z]+,\s*\d{4}\)',  # (Author, 2020)
            r'et al\.',  # et al.
        ]
        return any(re.search(pattern, content) for pattern in citation_patterns)

    def _has_numerical_data(self, content: str) -> bool:
        """수치 데이터가 있는지 확인"""
        # 숫자와 단위가 함께 있는 패턴
        data_pattern = r'\d+\.?\d*\s*(%|percent|million|billion|thousand)'
        return bool(re.search(data_pattern, content, re.IGNORECASE))

    def _has_links(self, content: str) -> bool:
        """링크가 있는지 확인"""
        url_pattern = r'http[s]?://[^\s]+'
        return bool(re.search(url_pattern, content))

    def _extract_key_points(self, content: str, max_points: int = 5) -> List[str]:
        """핵심 포인트 추출"""
        # 문장으로 분할
        sentences = re.split(r'[.!?]+', content)
        sentences = [s.strip() for s in sentences if len(s.strip()) > 30]

        # 키워드가 포함된 문장 우선
        keywords = ["important", "significant", "key", "critical", "essential", "main"]
        key_sentences = []

        for sentence in sentences:
            if any(keyword in sentence.lower() for keyword in keywords):
                key_sentences.append(sentence)

        # 키워드 문장이 부족하면 일반 문장 추가
        if len(key_sentences) < max_points:
            for sentence in sentences:
                if sentence not in key_sentences:
                    key_sentences.append(sentence)
                if len(key_sentences) >= max_points:
                    break

        return key_sentences[:max_points]

    async def cleanup(self) -> None:
        """리소스 정리"""
        self.is_available = False
        logger.info("Research Assistant skill cleaned up")
