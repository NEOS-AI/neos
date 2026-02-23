"""OpenAlex Skill implementation"""

from typing import Dict, Any, Optional, List
import logging

import httpx

from neos.skills.base import BaseSkill, SkillResult, SkillType
from neos.config.settings import settings

logger = logging.getLogger(__name__)


class OpenAlexSkill(BaseSkill):
    """OpenAlex 오픈 학술 메타데이터 검색 스킬

    OpenAlex API는 무료이며 API 키가 필요하지 않습니다.
    이메일을 제공하면 polite pool (더 빠른 응답)에 접근할 수 있습니다.
    260M+ 학술 작품에 대한 포괄적인 메타데이터를 제공합니다.
    """

    def __init__(self, **kwargs):
        super().__init__(
            name="openalex",
            skill_type=SkillType.RESEARCH,
            description="OpenAlex 오픈 학술 메타데이터 - 논문, 저자, 기관, 인용 네트워크",
            capabilities=[
                "open_academic_search",
                "citation_graph",
                "institution_analysis",
                "author_search",
                "deep_research",
            ],
            version="1.0.0",
            **kwargs,
        )
        self._client: Optional[httpx.AsyncClient] = None

    async def initialize(self) -> bool:
        """OpenAlex API 클라이언트 초기화"""
        try:
            email = getattr(settings, "OPENALEX_EMAIL", "")
            params = {}
            if email:
                params["mailto"] = email

            self._client = httpx.AsyncClient(
                base_url="https://api.openalex.org",
                params=params,
                timeout=30.0,
                headers={"User-Agent": "NEOS-Research-Engine/1.0"},
            )
            self.is_available = True
            logger.info(
                f"OpenAlex skill initialized (polite pool: {'yes' if email else 'no'})"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to initialize OpenAlex skill: {e}")
            return False

    async def execute(self, params: Dict[str, Any]) -> SkillResult:
        """OpenAlex 검색 실행

        Args:
            params: {
                "action": str,  # "search_works", "search_authors", "search_institutions", "get_work"
                "query": str,
                "max_results": int (optional, 기본값: 10),
                "year_from": int (optional),
                "year_to": int (optional),
                "open_access": bool (optional),  # True로 필터하면 OA 논문만
                "sort": str (optional),  # "cited_by_count", "publication_date", "relevance_score"
            }
        """
        if not self.is_available or not self._client:
            return SkillResult.error_result(
                error="OpenAlex skill not initialized",
                skill_name=self.name,
            )

        action = params.get("action", "search_works")

        if action == "search_works":
            return await self._search_works(params)
        elif action == "search_authors":
            return await self._search_authors(params)
        elif action == "search_institutions":
            return await self._search_institutions(params)
        elif action == "get_work":
            return await self._get_work(params)
        else:
            return SkillResult.error_result(
                error=f"Unknown action: {action}",
                skill_name=self.name,
            )

    async def _search_works(self, params: Dict[str, Any]) -> SkillResult:
        """학술 작품(논문) 검색"""
        query = params.get("query")
        if not query:
            return SkillResult.error_result(
                error="Query parameter is required",
                skill_name=self.name,
            )

        max_results = min(params.get("max_results", 10), 50)
        year_from = params.get("year_from")
        year_to = params.get("year_to")
        open_access = params.get("open_access")
        sort = params.get("sort", "relevance_score:desc")

        try:
            api_params = {
                "search": query,
                "per_page": max_results,
                "sort": sort,
            }

            # Build filter string
            filters = []
            if year_from:
                filters.append(f"from_publication_date:{year_from}-01-01")
            if year_to:
                filters.append(f"to_publication_date:{year_to}-12-31")
            if open_access is True:
                filters.append("is_oa:true")
            if filters:
                api_params["filter"] = ",".join(filters)

            response = await self._client.get("/works", params=api_params)
            response.raise_for_status()
            data = response.json()

            works = []
            for result in data.get("results", []):
                # Extract best OA URL
                oa_url = None
                best_oa = result.get("best_oa_location")
                if best_oa:
                    oa_url = best_oa.get("pdf_url") or best_oa.get("landing_page_url")

                works.append({
                    "title": result.get("title", ""),
                    "doi": result.get("doi", ""),
                    "publication_date": result.get("publication_date"),
                    "publication_year": result.get("publication_year"),
                    "cited_by_count": result.get("cited_by_count", 0),
                    "authors": self._extract_authors(result.get("authorships", [])),
                    "abstract": self._reconstruct_abstract(result.get("abstract_inverted_index")),
                    "type": result.get("type"),
                    "is_open_access": result.get("open_access", {}).get("is_oa", False),
                    "oa_url": oa_url,
                    "source": result.get("primary_location", {}).get("source", {}).get("display_name") if result.get("primary_location") else None,
                    "openalex_id": result.get("id", ""),
                    "concepts": [
                        c.get("display_name")
                        for c in result.get("concepts", [])[:5]
                    ],
                })

            return SkillResult.success_result(
                data={
                    "works": works,
                    "total_count": data.get("meta", {}).get("count", 0),
                    "query": query,
                },
                skill_name=self.name,
                metadata={"action": "search_works", "max_results": max_results},
            )

        except httpx.HTTPStatusError as e:
            logger.error(f"OpenAlex API error: {e.response.status_code}")
            return SkillResult.error_result(
                error=f"OpenAlex API error: {e.response.status_code}",
                skill_name=self.name,
            )
        except Exception as e:
            logger.error(f"Failed to search OpenAlex works: {e}")
            return SkillResult.error_result(error=str(e), skill_name=self.name)

    async def _search_authors(self, params: Dict[str, Any]) -> SkillResult:
        """저자 검색"""
        query = params.get("query")
        if not query:
            return SkillResult.error_result(
                error="Query parameter is required",
                skill_name=self.name,
            )

        max_results = min(params.get("max_results", 10), 25)

        try:
            response = await self._client.get(
                "/authors",
                params={"search": query, "per_page": max_results},
            )
            response.raise_for_status()
            data = response.json()

            authors = []
            for result in data.get("results", []):
                authors.append({
                    "name": result.get("display_name", ""),
                    "openalex_id": result.get("id", ""),
                    "orcid": result.get("orcid"),
                    "works_count": result.get("works_count", 0),
                    "cited_by_count": result.get("cited_by_count", 0),
                    "institution": result.get("last_known_institution", {}).get("display_name") if result.get("last_known_institution") else None,
                    "h_index": result.get("summary_stats", {}).get("h_index"),
                })

            return SkillResult.success_result(
                data={
                    "authors": authors,
                    "total_count": data.get("meta", {}).get("count", 0),
                    "query": query,
                },
                skill_name=self.name,
                metadata={"action": "search_authors"},
            )

        except Exception as e:
            logger.error(f"Failed to search OpenAlex authors: {e}")
            return SkillResult.error_result(error=str(e), skill_name=self.name)

    async def _search_institutions(self, params: Dict[str, Any]) -> SkillResult:
        """기관 검색"""
        query = params.get("query")
        if not query:
            return SkillResult.error_result(
                error="Query parameter is required",
                skill_name=self.name,
            )

        max_results = min(params.get("max_results", 10), 25)

        try:
            response = await self._client.get(
                "/institutions",
                params={"search": query, "per_page": max_results},
            )
            response.raise_for_status()
            data = response.json()

            institutions = []
            for result in data.get("results", []):
                institutions.append({
                    "name": result.get("display_name", ""),
                    "openalex_id": result.get("id", ""),
                    "country_code": result.get("country_code"),
                    "type": result.get("type"),
                    "works_count": result.get("works_count", 0),
                    "cited_by_count": result.get("cited_by_count", 0),
                    "homepage_url": result.get("homepage_url"),
                })

            return SkillResult.success_result(
                data={
                    "institutions": institutions,
                    "total_count": data.get("meta", {}).get("count", 0),
                    "query": query,
                },
                skill_name=self.name,
                metadata={"action": "search_institutions"},
            )

        except Exception as e:
            logger.error(f"Failed to search OpenAlex institutions: {e}")
            return SkillResult.error_result(error=str(e), skill_name=self.name)

    async def _get_work(self, params: Dict[str, Any]) -> SkillResult:
        """특정 논문 상세 정보 (DOI 또는 OpenAlex ID)"""
        query = params.get("query")
        if not query:
            return SkillResult.error_result(
                error="DOI or OpenAlex ID is required",
                skill_name=self.name,
            )

        try:
            # DOI or OpenAlex ID
            if query.startswith("https://doi.org/") or query.startswith("10."):
                doi = query if query.startswith("https://doi.org/") else f"https://doi.org/{query}"
                response = await self._client.get(f"/works/{doi}")
            else:
                response = await self._client.get(f"/works/{query}")

            response.raise_for_status()
            result = response.json()

            oa_url = None
            best_oa = result.get("best_oa_location")
            if best_oa:
                oa_url = best_oa.get("pdf_url") or best_oa.get("landing_page_url")

            work = {
                "title": result.get("title", ""),
                "doi": result.get("doi", ""),
                "publication_date": result.get("publication_date"),
                "cited_by_count": result.get("cited_by_count", 0),
                "authors": self._extract_authors(result.get("authorships", [])),
                "abstract": self._reconstruct_abstract(result.get("abstract_inverted_index")),
                "type": result.get("type"),
                "is_open_access": result.get("open_access", {}).get("is_oa", False),
                "oa_url": oa_url,
                "source": result.get("primary_location", {}).get("source", {}).get("display_name") if result.get("primary_location") else None,
                "concepts": [c.get("display_name") for c in result.get("concepts", [])[:10]],
                "referenced_works_count": len(result.get("referenced_works", [])),
                "related_works": result.get("related_works", [])[:5],
            }

            return SkillResult.success_result(
                data=work,
                skill_name=self.name,
                metadata={"action": "get_work"},
            )

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return SkillResult.error_result(
                    error=f"Work not found: {query}",
                    skill_name=self.name,
                )
            return SkillResult.error_result(
                error=f"OpenAlex API error: {e.response.status_code}",
                skill_name=self.name,
            )
        except Exception as e:
            logger.error(f"Failed to get work: {e}")
            return SkillResult.error_result(error=str(e), skill_name=self.name)

    @staticmethod
    def _extract_authors(authorships: List[Dict]) -> List[str]:
        """저자 목록 추출"""
        return [
            a.get("author", {}).get("display_name", "")
            for a in authorships[:10]
            if a.get("author")
        ]

    @staticmethod
    def _reconstruct_abstract(inverted_index: Optional[Dict]) -> str:
        """OpenAlex inverted index에서 초록 복원"""
        if not inverted_index:
            return ""

        # Reconstruct from inverted index: {word: [positions]}
        word_positions = []
        for word, positions in inverted_index.items():
            for pos in positions:
                word_positions.append((pos, word))

        word_positions.sort(key=lambda x: x[0])
        return " ".join(word for _, word in word_positions)

    async def cleanup(self) -> None:
        """리소스 정리"""
        if self._client:
            await self._client.aclose()
            self._client = None
        self.is_available = False
        logger.info("OpenAlex skill cleaned up")
