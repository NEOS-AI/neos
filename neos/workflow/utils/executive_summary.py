"""Executive Summary 자동 생성 (Phase 2.10)

500단어 이상 응답에 2-3문장 TL;DR을 자동 생성합니다.
Fast LLM 호출 + 다국어 지원 (ko/en/ja/zh).
"""

import logging
from typing import Optional

from neos.config.settings import settings

logger = logging.getLogger(__name__)

_SUMMARY_PROMPT_TEMPLATE = """다음 연구 응답의 핵심을 {max_sentences}문장 이내로 요약해주세요.
언어: {language}

원본 쿼리: {query}

응답:
{response}

요약 (반드시 {max_sentences}문장 이내):"""


class ExecutiveSummaryGenerator:
    """장문 응답에 대한 Executive Summary 자동 생성

    - 설정된 단어 수(기본 500) 이상의 응답에만 작동
    - Fast LLM (Haiku 등)을 사용하여 지연 최소화
    - 감지된 언어에 맞춰 요약 생성
    """

    def __init__(self):
        self._llm = None

    def _get_llm(self):
        if self._llm is None:
            from neos.utils.llm_factory import create_llm

            model = getattr(settings, "QUERY_CLASSIFIER_LLM_MODEL", "claude-haiku-4-5-20251001")
            if "claude" in model or "haiku" in model:
                provider = "anthropic"
            elif "gemini" in model:
                provider = "gemini"
            else:
                provider = "openai"

            self._llm = create_llm(
                provider=provider,
                model=model,
                temperature=0.0,
                max_tokens=300,
                request_timeout=15,
            )
        return self._llm

    async def generate(
        self,
        response: str,
        query: str,
        language: str = "en",
    ) -> Optional[str]:
        """Executive summary 생성

        Args:
            response: 최종 응답 텍스트
            query: 원본 사용자 쿼리
            language: 감지된 언어 코드

        Returns:
            요약 문자열 또는 None (조건 미충족 시)
        """
        min_words = getattr(settings, "EXECUTIVE_SUMMARY_MIN_WORDS", 500)
        max_sentences = getattr(settings, "EXECUTIVE_SUMMARY_MAX_SENTENCES", 3)

        word_count = len(response.split())
        if word_count < min_words:
            return None

        try:
            llm = self._get_llm()

            # 응답이 너무 길면 앞부분만 사용 (LLM 컨텍스트 절약)
            truncated = response[:4000] if len(response) > 4000 else response

            lang_name = {
                "ko": "한국어", "en": "English", "ja": "日本語", "zh": "中文"
            }.get(language, "English")

            prompt = _SUMMARY_PROMPT_TEMPLATE.format(
                max_sentences=max_sentences,
                language=lang_name,
                query=query,
                response=truncated,
            )

            result = await llm.ainvoke(prompt)
            content = result.content if hasattr(result, "content") else str(result)
            summary = content.strip()

            if summary:
                logger.info(f"Executive summary generated ({len(summary)} chars) for response ({word_count} words)")
                return summary

            return None
        except Exception as e:
            logger.warning(f"Executive summary generation failed: {e}")
            return None


# 전역 인스턴스
executive_summary_generator = ExecutiveSummaryGenerator()
