"""PubMed Skill implementation"""

from typing import Dict, Any, List
import logging

from neos.skills.base import BaseSkill, SkillResult, SkillType


logger = logging.getLogger(__name__)


class PubmedSkill(BaseSkill):
    """PubMed 의학/생물학 논문 검색 스킬"""

    def __init__(self, **kwargs):
        super().__init__(
            name="pubmed",
            skill_type=SkillType.RESEARCH,
            description="PubMed 의학/생물학 논문 검색 - 의학, 생명과학, 바이오메디컬 분야",
            capabilities=[
                "medical_research",
                "biomedical_search",
                "pubmed_query",
                "paper_search",
                "metadata_extraction",
                "research_support",
            ],
            version="1.0.0",
            **kwargs
        )
        self.pubmed_wrapper = None

    async def initialize(self) -> bool:
        """PubMed API 래퍼 초기화"""
        try:
            from langchain_community.utilities import PubMedAPIWrapper

            self.pubmed_wrapper = PubMedAPIWrapper()
            self.is_available = True
            logger.info("PubMed skill initialized successfully")
            return True

        except ImportError as e:
            logger.warning(
                f"PubMed skill not available: {e}. "
                "Install with: pip install langchain-community"
            )
            return False
        except Exception as e:
            logger.error(f"Failed to initialize PubMed skill: {e}")
            return False

    async def execute(self, params: Dict[str, Any]) -> SkillResult:
        """PubMed 검색 실행

        Args:
            params: {
                "action": str,  # "search", "get_by_pmid"
                "query": str,  # 검색 쿼리 또는 PMID
                "max_results": int (optional),  # 최대 결과 수 (기본값: 5)
            }

        Returns:
            검색 결과
        """
        if not self.is_available:
            return SkillResult.error_result(
                error="PubMed skill not initialized",
                skill_name=self.name,
            )

        action = params.get("action", "search")

        if action == "search":
            return await self._search_papers(params)
        elif action == "get_by_pmid":
            return await self._get_paper_by_pmid(params)
        else:
            return SkillResult.error_result(
                error=f"Unknown action: {action}",
                skill_name=self.name,
            )

    async def _search_papers(self, params: Dict[str, Any]) -> SkillResult:
        """PubMed에서 논문 검색"""
        query = params.get("query")
        max_results = params.get("max_results", 5)

        if not query:
            return SkillResult.error_result(
                error="Query parameter is required",
                skill_name=self.name,
            )

        try:
            from langchain_community.utilities import PubMedAPIWrapper

            # max_results를 설정하여 래퍼 재생성
            pubmed_wrapper = PubMedAPIWrapper(
                top_k_results=max_results,
            )

            # 문서 로드
            docs = pubmed_wrapper.load(query)

            # 결과 파싱
            papers = []
            for doc in docs:
                # PubMed 메타데이터 파싱
                paper_info = {
                    "title": doc.metadata.get("Title", ""),
                    "authors": doc.metadata.get("Authors", ""),
                    "published": doc.metadata.get("Published", ""),
                    "pmid": doc.metadata.get("uid", ""),
                    "summary": doc.page_content[:500] + "..." if len(doc.page_content) > 500 else doc.page_content,
                    "full_summary": doc.page_content,
                    "pubmed_url": f"https://pubmed.ncbi.nlm.nih.gov/{doc.metadata.get('uid', '')}/" if doc.metadata.get('uid') else "",
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
            logger.error(f"Failed to search PubMed: {e}")
            return SkillResult.error_result(
                error=str(e),
                skill_name=self.name,
            )

    async def _get_paper_by_pmid(self, params: Dict[str, Any]) -> SkillResult:
        """PMID로 특정 논문 조회"""
        pmid = params.get("query") or params.get("pmid")

        if not pmid:
            return SkillResult.error_result(
                error="PMID (query or pmid parameter) is required",
                skill_name=self.name,
            )

        try:
            from langchain_community.utilities import PubMedAPIWrapper

            # PMID로 검색
            pubmed_wrapper = PubMedAPIWrapper(top_k_results=1)
            docs = pubmed_wrapper.load(pmid)

            if not docs:
                return SkillResult.error_result(
                    error=f"Paper not found with PMID: {pmid}",
                    skill_name=self.name,
                )

            doc = docs[0]
            paper_info = {
                "title": doc.metadata.get("Title", ""),
                "authors": doc.metadata.get("Authors", ""),
                "published": doc.metadata.get("Published", ""),
                "pmid": doc.metadata.get("uid", ""),
                "summary": doc.page_content,
                "pubmed_url": f"https://pubmed.ncbi.nlm.nih.gov/{doc.metadata.get('uid', '')}/" if doc.metadata.get('uid') else "",
            }

            return SkillResult.success_result(
                data=paper_info,
                skill_name=self.name,
                metadata={"action": "get_by_pmid"},
            )

        except Exception as e:
            logger.error(f"Failed to get PubMed paper by PMID: {e}")
            return SkillResult.error_result(
                error=str(e),
                skill_name=self.name,
            )

    async def cleanup(self) -> None:
        """리소스 정리"""
        self.pubmed_wrapper = None
        self.is_available = False
        logger.info("PubMed skill cleaned up")
