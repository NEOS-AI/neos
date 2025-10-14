"""
텍스트 처리 파이프라인

순수 텍스트 입력을 처리합니다.
"""

from typing import Dict, Any
import re

from .base import (
    BasePipeline,
    InputType,
    PipelineContext,
    PipelineResult,
    ProcessingStage
)


class TextPipeline(BasePipeline):
    """
    텍스트 처리 파이프라인

    순수 텍스트 쿼리를 정제하고 분석합니다.
    """

    def __init__(self):
        super().__init__(name="TextPipeline", input_type=InputType.TEXT)

    async def validate(self, context: PipelineContext) -> bool:
        """텍스트 입력 검증"""
        if not context.query or not context.query.strip():
            return False

        if len(context.query) > 50000:  # 최대 길이 제한
            return False

        return True

    async def preprocess(self, context: PipelineContext) -> PipelineContext:
        """텍스트 전처리"""
        # 공백 정리
        context.query = context.query.strip()

        # 연속된 공백 제거
        context.query = re.sub(r'\s+', ' ', context.query)

        # 언어 감지 (간단한 휴리스틱)
        if not context.language:
            context.language = self._detect_language(context.query)

        return context

    async def extract(self, context: PipelineContext) -> PipelineResult:
        """텍스트 정보 추출"""
        result = PipelineResult(
            success=True,
            input_type=InputType.TEXT,
            stage=ProcessingStage.EXTRACTION,
            extracted_text=context.query
        )

        # 메타데이터 추출
        result.metadata = {
            "text_length": len(context.query),
            "word_count": len(context.query.split()),
            "language": context.language,
            "has_special_chars": bool(re.search(r'[^\w\s]', context.query)),
        }

        return result

    async def analyze(self, result: PipelineResult, context: PipelineContext) -> PipelineResult:
        """텍스트 분석"""
        query = result.extracted_text

        # 간단한 분석
        result.analysis = {
            "query_type": self._classify_query_type(query),
            "contains_question": "?" in query,
            "sentence_count": len(re.split(r'[.!?]+', query)),
        }

        # 인사이트 생성
        insights = []
        if len(query.split()) < 5:
            insights.append("Short query - may need clarification")
        if "?" in query:
            insights.append("Question detected - information seeking intent")

        result.insights = insights

        # 통합 컨텍스트 생성 (다음 워크플로우로 전달)
        result.unified_context = f"""
**Query**: {query}

**Metadata**:
- Language: {context.language}
- Length: {len(query)} characters, {len(query.split())} words
- Type: {result.analysis['query_type']}
"""

        return result

    def _detect_language(self, text: str) -> str:
        """간단한 언어 감지 (한글/영어)"""
        korean_chars = len(re.findall(r'[가-힣]', text))
        english_chars = len(re.findall(r'[a-zA-Z]', text))

        if korean_chars > english_chars:
            return "ko"
        elif english_chars > 0:
            return "en"
        else:
            return "unknown"

    def _classify_query_type(self, query: str) -> str:
        """쿼리 타입 분류"""
        query_lower = query.lower()

        if any(word in query_lower for word in ["what", "when", "where", "who", "why", "how", "무엇", "언제", "어디", "누구", "왜", "어떻게"]):
            return "question"
        elif any(word in query_lower for word in ["compare", "vs", "versus", "비교", "차이"]):
            return "comparison"
        elif any(word in query_lower for word in ["analyze", "analysis", "분석", "검토"]):
            return "analysis"
        elif any(word in query_lower for word in ["create", "generate", "make", "생성", "만들어"]):
            return "generation"
        else:
            return "general"
