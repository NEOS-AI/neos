"""ArXiv Skill implementation"""

from typing import Dict, Any
import logging

from neos.skills.base import BaseSkill, SkillResult, SkillType


logger = logging.getLogger(__name__)


class ArxivSkill(BaseSkill):
    """ArXiv 학술 논문 검색 스킬"""

    def __init__(self, **kwargs):
        super().__init__(
            name="arxiv",
            skill_type=SkillType.RESEARCH,
            description="ArXiv 학술 논문 검색 - 물리학, 수학, 컴퓨터 과학, AI/ML 등",
            capabilities=[
                "paper_search",
                "academic_research",
                "arxiv_query",
                "metadata_extraction",
                "research_support",
            ],
            version="1.0.0",
            **kwargs
        )
        self.arxiv_wrapper = None

    async def initialize(self) -> bool:
        """ArXiv API 래퍼 초기화"""
        try:
            from langchain_community.utilities import ArxivAPIWrapper

            self.arxiv_wrapper = ArxivAPIWrapper()
            self.is_available = True
            logger.info("ArXiv skill initialized successfully")
            return True

        except ImportError as e:
            logger.warning(
                f"ArXiv skill not available: {e}. "
                "Install with: pip install langchain-community arxiv"
            )
            return False
        except Exception as e:
            logger.error(f"Failed to initialize ArXiv skill: {e}")
            return False

    async def execute(self, params: Dict[str, Any]) -> SkillResult:
        """ArXiv 검색 실행

        Args:
            params: {
                "action": str,  # "search", "get_by_id"
                "query": str,  # 검색 쿼리 또는 ArXiv ID
                "max_results": int (optional),  # 최대 결과 수 (기본값: 5)
                "sort_by": str (optional),  # 정렬 기준 ("relevance", "lastUpdatedDate", "submittedDate")
            }

        Returns:
            검색 결과
        """
        if not self.is_available:
            return SkillResult.error_result(
                error="ArXiv skill not initialized",
                skill_name=self.name,
            )

        action = params.get("action", "search")

        if action == "search":
            return await self._search_papers(params)
        elif action == "get_by_id":
            return await self._get_paper_by_id(params)
        else:
            return SkillResult.error_result(
                error=f"Unknown action: {action}",
                skill_name=self.name,
            )

    async def _search_papers(self, params: Dict[str, Any]) -> SkillResult:
        """ArXiv에서 논문 검색"""
        query = params.get("query")
        max_results = params.get("max_results", 5)

        if not query:
            return SkillResult.error_result(
                error="Query parameter is required",
                skill_name=self.name,
            )

        try:
            # ArXiv API를 통해 검색
            # ArxivAPIWrapper의 run 메서드는 문자열을 반환하므로
            # load 메서드를 사용하여 구조화된 데이터를 가져옵니다
            from langchain_community.utilities import ArxivAPIWrapper

            # max_results를 설정하여 래퍼 재생성
            arxiv_wrapper = ArxivAPIWrapper(
                top_k_results=max_results,
                load_max_docs=max_results,
            )

            # 문서 로드
            docs = arxiv_wrapper.load(query)

            # 결과 파싱
            papers = []
            for doc in docs:
                paper_info = {
                    "title": doc.metadata.get("Title", ""),
                    "authors": doc.metadata.get("Authors", ""),
                    "published": doc.metadata.get("Published", ""),
                    "arxiv_id": doc.metadata.get("entry_id", "").split("/")[-1] if doc.metadata.get("entry_id") else "",
                    "summary": doc.page_content[:500] + "..." if len(doc.page_content) > 500 else doc.page_content,
                    "full_summary": doc.page_content,
                    "pdf_url": doc.metadata.get("entry_id", "").replace("/abs/", "/pdf/") + ".pdf" if doc.metadata.get("entry_id") else "",
                    "entry_url": doc.metadata.get("entry_id", ""),
                }
                papers.append(paper_info)

            return SkillResult.success_result(
                data={
                    "papers": papers,
                    "total_results": len(papers),
                    "query": query,
                },
                skill_name=self.name,
                metadata={
                    "action": "search",
                    "max_results": max_results,
                },
            )

        except Exception as e:
            logger.error(f"Failed to search ArXiv: {e}")
            return SkillResult.error_result(
                error=str(e),
                skill_name=self.name,
            )

    async def _get_paper_by_id(self, params: Dict[str, Any]) -> SkillResult:
        """ArXiv ID로 특정 논문 조회"""
        arxiv_id = params.get("query") or params.get("arxiv_id")

        if not arxiv_id:
            return SkillResult.error_result(
                error="ArXiv ID (query or arxiv_id parameter) is required",
                skill_name=self.name,
            )

        try:
            from langchain_community.utilities import ArxivAPIWrapper

            # ID로 검색
            arxiv_wrapper = ArxivAPIWrapper(top_k_results=1, load_max_docs=1)
            docs = arxiv_wrapper.load(arxiv_id)

            if not docs:
                return SkillResult.error_result(
                    error=f"Paper not found with ID: {arxiv_id}",
                    skill_name=self.name,
                )

            doc = docs[0]
            paper_info = {
                "title": doc.metadata.get("Title", ""),
                "authors": doc.metadata.get("Authors", ""),
                "published": doc.metadata.get("Published", ""),
                "arxiv_id": doc.metadata.get("entry_id", "").split("/")[-1] if doc.metadata.get("entry_id") else "",
                "summary": doc.page_content,
                "pdf_url": doc.metadata.get("entry_id", "").replace("/abs/", "/pdf/") + ".pdf" if doc.metadata.get("entry_id") else "",
                "entry_url": doc.metadata.get("entry_id", ""),
            }

            return SkillResult.success_result(
                data=paper_info,
                skill_name=self.name,
                metadata={"action": "get_by_id"},
            )

        except Exception as e:
            logger.error(f"Failed to get ArXiv paper by ID: {e}")
            return SkillResult.error_result(
                error=str(e),
                skill_name=self.name,
            )

    async def cleanup(self) -> None:
        """리소스 정리"""
        self.arxiv_wrapper = None
        self.is_available = False
        logger.info("ArXiv skill cleaned up")
