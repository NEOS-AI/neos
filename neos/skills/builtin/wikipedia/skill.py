"""Wikipedia Skill implementation"""

from typing import Dict, Any
import logging
from langchain_community.utilities import WikipediaAPIWrapper

from neos.skills.base import BaseSkill, SkillResult, SkillType


logger = logging.getLogger(__name__)


class WikipediaSkill(BaseSkill):
    """Wikipedia 일반 지식 검색 스킬"""

    def __init__(self, **kwargs):
        super().__init__(
            name="wikipedia",
            skill_type=SkillType.RESEARCH,
            description="Wikipedia 일반 지식 검색 - 개념 정의, 배경 정보, 일반 지식",
            capabilities=[
                "knowledge_search",
                "concept_definition",
                "background_research",
                "general_information",
                "research_support",
            ],
            version="1.0.0",
            **kwargs
        )
        self.wikipedia_wrapper = None

    async def initialize(self) -> bool:
        """Wikipedia API 래퍼 초기화"""
        try:
            self.wikipedia_wrapper = WikipediaAPIWrapper()
            self.is_available = True
            logger.info("Wikipedia skill initialized successfully")
            return True

        except ImportError as e:
            logger.warning(
                f"Wikipedia skill not available: {e}. "
                "Install with: pip install langchain-community wikipedia"
            )
            return False
        except Exception as e:
            logger.error(f"Failed to initialize Wikipedia skill: {e}")
            return False

    async def execute(self, params: Dict[str, Any]) -> SkillResult:
        """Wikipedia 검색 실행

        Args:
            params: {
                "action": str,  # "search", "get_page"
                "query": str,  # 검색 쿼리
                "max_results": int (optional),  # 최대 결과 수 (기본값: 3)
                "load_all_summaries": bool (optional),  # 모든 요약 로드 (기본값: False)
                "lang": str (optional),  # 언어 코드 (기본값: "en")
            }

        Returns:
            검색 결과
        """
        if not self.is_available:
            return SkillResult.error_result(
                error="Wikipedia skill not initialized",
                skill_name=self.name,
            )

        action = params.get("action", "search")

        if action == "search":
            return await self._search_articles(params)
        elif action == "get_page":
            return await self._get_page_content(params)
        else:
            return SkillResult.error_result(
                error=f"Unknown action: {action}",
                skill_name=self.name,
            )

    async def _search_articles(self, params: Dict[str, Any]) -> SkillResult:
        """Wikipedia에서 문서 검색"""
        query = params.get("query")
        max_results = params.get("max_results", 3)
        load_all_summaries = params.get("load_all_summaries", False)
        lang = params.get("lang", "en")

        if not query:
            return SkillResult.error_result(
                error="Query parameter is required",
                skill_name=self.name,
            )

        try:
            # 래퍼 생성
            wikipedia_wrapper = WikipediaAPIWrapper(
                top_k_results=max_results,
                load_all_available_meta=load_all_summaries,
                lang=lang,
            )

            # 문서 로드
            docs = wikipedia_wrapper.load(query)

            # 결과 파싱
            articles = []
            for doc in docs:
                article_info = {
                    "title": doc.metadata.get("title", ""),
                    "summary": doc.metadata.get("summary", ""),
                    "content": doc.page_content[:1000] + "..." if len(doc.page_content) > 1000 else doc.page_content,
                    "full_content": doc.page_content,
                    "url": doc.metadata.get("source", ""),
                }
                articles.append(article_info)

            return SkillResult.success_result(
                data={
                    "articles": articles,
                    "total_results": len(articles),
                    "query": query,
                    "lang": lang,
                },
                skill_name=self.name,
                metadata={
                    "action": "search",
                    "max_results": max_results,
                },
            )

        except Exception as e:
            logger.error(f"Failed to search Wikipedia: {e}")
            return SkillResult.error_result(
                error=str(e),
                skill_name=self.name,
            )

    async def _get_page_content(self, params: Dict[str, Any]) -> SkillResult:
        """특정 Wikipedia 페이지 내용 가져오기"""
        query = params.get("query") or params.get("page_title")
        lang = params.get("lang", "en")

        if not query:
            return SkillResult.error_result(
                error="Query or page_title parameter is required",
                skill_name=self.name,
            )

        try:
            # 페이지 검색 (단일 결과)
            wikipedia_wrapper = WikipediaAPIWrapper(
                top_k_results=1,
                lang=lang,
            )
            docs = wikipedia_wrapper.load(query)

            if not docs:
                return SkillResult.error_result(
                    error=f"Page not found: {query}",
                    skill_name=self.name,
                )

            doc = docs[0]
            article_info = {
                "title": doc.metadata.get("title", ""),
                "summary": doc.metadata.get("summary", ""),
                "content": doc.page_content,
                "url": doc.metadata.get("source", ""),
            }

            return SkillResult.success_result(
                data=article_info,
                skill_name=self.name,
                metadata={"action": "get_page"},
            )

        except Exception as e:
            logger.error(f"Failed to get Wikipedia page: {e}")
            return SkillResult.error_result(
                error=str(e),
                skill_name=self.name,
            )

    async def cleanup(self) -> None:
        """리소스 정리"""
        self.wikipedia_wrapper = None
        self.is_available = False
        logger.info("Wikipedia skill cleaned up")
