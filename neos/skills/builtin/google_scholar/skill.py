"""Google Scholar Skill implementation via SerpAPI"""

from typing import Dict, Any, Optional
import logging

import httpx

from neos.skills.base import BaseSkill, SkillResult, SkillType
from neos.config.settings import settings

logger = logging.getLogger(__name__)


class GoogleScholarSkill(BaseSkill):
    """Google Scholar 학술 검색 스킬 (SerpAPI 경유)

    SerpAPI를 통해 Google Scholar 검색 결과를 구조화된 형태로 제공합니다.
    SERPAPI_API_KEY 환경변수가 필요합니다.
    """

    def __init__(self, **kwargs):
        super().__init__(
            name="google_scholar",
            skill_type=SkillType.RESEARCH,
            description="Google Scholar 학술 검색 - 광범위 학술 논문, 인용 추적, 저자 프로필",
            capabilities=[
                "academic_search",
                "citation_tracking",
                "author_profiles",
                "deep_research",
            ],
            version="1.0.0",
            **kwargs,
        )
        self._client: Optional[httpx.AsyncClient] = None
        self._api_key: Optional[str] = None

    async def initialize(self) -> bool:
        """SerpAPI 클라이언트 초기화"""
        try:
            self._api_key = getattr(settings, "SERPAPI_API_KEY", None)
            if not self._api_key:
                logger.warning(
                    "Google Scholar skill: SERPAPI_API_KEY not set. Skill unavailable."
                )
                return False

            self._client = httpx.AsyncClient(
                base_url="https://serpapi.com",
                timeout=30.0,
            )
            self.is_available = True
            logger.info("Google Scholar skill initialized successfully")
            return True

        except Exception as e:
            logger.error(f"Failed to initialize Google Scholar skill: {e}")
            return False

    async def execute(self, params: Dict[str, Any]) -> SkillResult:
        """Google Scholar 검색 실행

        Args:
            params: {
                "action": str,  # "search", "cite"
                "query": str,
                "max_results": int (optional, 기본값: 10),
                "year_from": int (optional),
                "year_to": int (optional),
            }
        """
        if not self.is_available or not self._client:
            return SkillResult.error_result(
                error="Google Scholar skill not initialized (SERPAPI_API_KEY required)",
                skill_name=self.name,
            )

        action = params.get("action", "search")

        if action == "search":
            return await self._search_papers(params)
        elif action == "cite":
            return await self._get_citations(params)
        else:
            return SkillResult.error_result(
                error=f"Unknown action: {action}",
                skill_name=self.name,
            )

    async def _search_papers(self, params: Dict[str, Any]) -> SkillResult:
        """Google Scholar 논문 검색"""
        query = params.get("query")
        if not query:
            return SkillResult.error_result(
                error="Query parameter is required",
                skill_name=self.name,
            )

        max_results = min(params.get("max_results", 10), 20)
        year_from = params.get("year_from")
        year_to = params.get("year_to")

        try:
            api_params = {
                "engine": "google_scholar",
                "q": query,
                "api_key": self._api_key,
                "num": max_results,
            }
            if year_from:
                api_params["as_ylo"] = year_from
            if year_to:
                api_params["as_yhi"] = year_to

            response = await self._client.get("/search", params=api_params)
            response.raise_for_status()
            data = response.json()

            papers = []
            for result in data.get("organic_results", []):
                paper = {
                    "title": result.get("title", ""),
                    "snippet": result.get("snippet", ""),
                    "url": result.get("link", ""),
                    "authors": result.get("publication_info", {}).get("summary", ""),
                    "cited_by_count": result.get("inline_links", {}).get("cited_by", {}).get("total"),
                    "cited_by_link": result.get("inline_links", {}).get("cited_by", {}).get("link"),
                    "year": result.get("publication_info", {}).get("summary", "").split(",")[-1].strip() if result.get("publication_info") else None,
                    "resource_type": result.get("type"),
                    "pdf_link": None,
                }
                # Extract PDF link from resources
                for resource in result.get("resources", []):
                    if resource.get("file_format") == "PDF":
                        paper["pdf_link"] = resource.get("link")
                        break

                papers.append(paper)

            return SkillResult.success_result(
                data={
                    "papers": papers,
                    "total_results": data.get("search_information", {}).get("total_results", len(papers)),
                    "query": query,
                },
                skill_name=self.name,
                metadata={"action": "search", "max_results": max_results},
            )

        except httpx.HTTPStatusError as e:
            logger.error(f"SerpAPI error: {e.response.status_code}")
            return SkillResult.error_result(
                error=f"SerpAPI error: {e.response.status_code}",
                skill_name=self.name,
            )
        except Exception as e:
            logger.error(f"Failed to search Google Scholar: {e}")
            return SkillResult.error_result(error=str(e), skill_name=self.name)

    async def _get_citations(self, params: Dict[str, Any]) -> SkillResult:
        """논문의 인용 목록 검색"""
        query = params.get("query")
        if not query:
            return SkillResult.error_result(
                error="Query parameter is required",
                skill_name=self.name,
            )

        max_results = min(params.get("max_results", 10), 20)

        try:
            api_params = {
                "engine": "google_scholar",
                "q": query,
                "api_key": self._api_key,
                "num": 1,
            }

            response = await self._client.get("/search", params=api_params)
            response.raise_for_status()
            data = response.json()

            results = data.get("organic_results", [])
            if not results:
                return SkillResult.error_result(
                    error="No paper found for citation lookup",
                    skill_name=self.name,
                )

            cited_by = results[0].get("inline_links", {}).get("cited_by", {})
            return SkillResult.success_result(
                data={
                    "paper_title": results[0].get("title", ""),
                    "cited_by_count": cited_by.get("total"),
                    "cited_by_link": cited_by.get("link"),
                    "query": query,
                },
                skill_name=self.name,
                metadata={"action": "cite"},
            )

        except Exception as e:
            logger.error(f"Failed to get citations: {e}")
            return SkillResult.error_result(error=str(e), skill_name=self.name)

    async def cleanup(self) -> None:
        """리소스 정리"""
        if self._client:
            await self._client.aclose()
            self._client = None
        self.is_available = False
        logger.info("Google Scholar skill cleaned up")
