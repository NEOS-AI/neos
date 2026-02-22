"""Semantic Scholar Skill implementation

무료 API를 통해 학술 논문 검색, 인용 그래프 탐색,
오픈 액세스 PDF 접근을 제공합니다.

ArXiv보다 풍부한 메타데이터와 citation graph를 활용할 수 있습니다.
"""

from typing import Dict, Any, Optional
import logging

from neos.skills.base import BaseSkill, SkillResult, SkillType
from neos.config.settings import settings

logger = logging.getLogger(__name__)

SEMANTIC_SCHOLAR_BASE_URL = "https://api.semanticscholar.org/graph/v1"


class SemanticScholarSkill(BaseSkill):
    """Semantic Scholar 학술 논문 검색 스킬"""

    def __init__(self, **kwargs):
        super().__init__(
            name="semantic_scholar",
            skill_type=SkillType.RESEARCH,
            description="Semantic Scholar: 학술 논문 검색, 인용 그래프, 오픈 액세스 PDF",
            capabilities=[
                "academic_search",
                "citation_graph",
                "paper_metadata",
                "open_access_pdf",
                "research_support",
                "author_search",
            ],
            version="1.0.0",
            **kwargs
        )
        self._session = None

    async def initialize(self) -> bool:
        """HTTP 세션 초기화"""
        try:
            import httpx

            headers = {}
            api_key = getattr(settings, "SEMANTIC_SCHOLAR_API_KEY", None)
            if api_key:
                headers["x-api-key"] = api_key

            self._session = httpx.AsyncClient(
                headers=headers,
                timeout=httpx.Timeout(15.0),
            )
            self.is_available = True
            logger.info("Semantic Scholar skill initialized successfully")
            return True

        except ImportError:
            logger.warning("httpx not available for Semantic Scholar skill")
            return False
        except Exception as e:
            logger.error(f"Failed to initialize Semantic Scholar skill: {e}")
            return False

    async def execute(self, params: Dict[str, Any]) -> SkillResult:
        """Semantic Scholar 검색 실행

        Args:
            params: {
                "action": str,  # "search", "get_citations", "get_references", "get_paper"
                "query": str,   # 검색 쿼리 또는 paper_id
                "max_results": int (optional),  # 최대 결과 수 (기본값: 10)
                "paper_id": str (optional),  # citation/reference 조회 시
                "year": str (optional),  # 연도 필터 (예: "2020-2025")
            }
        """
        if not self.is_available or not self._session:
            return SkillResult.error_result(
                "Semantic Scholar skill not initialized",
                skill_name=self.name
            )

        action = params.get("action", "search")

        try:
            if action == "search":
                return await self._search_papers(params)
            elif action == "get_citations":
                return await self._get_citations(params)
            elif action == "get_references":
                return await self._get_references(params)
            elif action == "get_paper":
                return await self._get_paper(params)
            else:
                return SkillResult.error_result(
                    f"Unknown action: {action}",
                    skill_name=self.name
                )
        except Exception as e:
            logger.error(f"[SemanticScholar] Action '{action}' failed: {e}")
            return SkillResult.error_result(str(e), skill_name=self.name)

    async def _search_papers(self, params: Dict[str, Any]) -> SkillResult:
        """논문 검색"""
        query = params.get("query", "")
        limit = min(params.get("max_results", 10), 100)
        fields = "title,authors,year,abstract,citationCount,openAccessPdf,externalIds,url"

        request_params = {
            "query": query,
            "limit": limit,
            "fields": fields,
        }

        # 연도 필터
        year = params.get("year")
        if year:
            request_params["year"] = year

        resp = await self._session.get(
            f"{SEMANTIC_SCHOLAR_BASE_URL}/paper/search",
            params=request_params,
        )
        resp.raise_for_status()
        data = resp.json()

        papers = []
        for p in data.get("data", []):
            pdf_info = p.get("openAccessPdf") or {}
            external_ids = p.get("externalIds") or {}
            papers.append({
                "paper_id": p.get("paperId"),
                "title": p.get("title", ""),
                "authors": [a.get("name") for a in p.get("authors", [])],
                "year": p.get("year"),
                "abstract": p.get("abstract", ""),
                "citation_count": p.get("citationCount", 0),
                "open_access_pdf": pdf_info.get("url"),
                "doi": external_ids.get("DOI"),
                "arxiv_id": external_ids.get("ArXiv"),
                "url": p.get("url", ""),
            })

        return SkillResult.success_result(
            data={
                "papers": papers,
                "total_results": data.get("total", len(papers)),
                "query": query,
            },
            skill_name=self.name,
            metadata={"action": "search", "limit": limit},
        )

    async def _get_citations(self, params: Dict[str, Any]) -> SkillResult:
        """논문의 인용 논문 목록 조회 (citation graph)"""
        paper_id = params.get("paper_id", params.get("query", ""))
        limit = min(params.get("max_results", 20), 100)
        fields = "title,year,authors,citationCount"

        resp = await self._session.get(
            f"{SEMANTIC_SCHOLAR_BASE_URL}/paper/{paper_id}/citations",
            params={"limit": limit, "fields": fields},
        )
        resp.raise_for_status()
        data = resp.json()

        citations = []
        for item in data.get("data", []):
            citing = item.get("citingPaper", {})
            citations.append({
                "paper_id": citing.get("paperId"),
                "title": citing.get("title", ""),
                "year": citing.get("year"),
                "authors": [a.get("name") for a in citing.get("authors", [])],
                "citation_count": citing.get("citationCount", 0),
            })

        return SkillResult.success_result(
            data={"citations": citations, "paper_id": paper_id, "total": len(citations)},
            skill_name=self.name,
        )

    async def _get_references(self, params: Dict[str, Any]) -> SkillResult:
        """논문이 참조하는 논문 목록 조회"""
        paper_id = params.get("paper_id", params.get("query", ""))
        limit = min(params.get("max_results", 20), 100)
        fields = "title,year,authors,citationCount"

        resp = await self._session.get(
            f"{SEMANTIC_SCHOLAR_BASE_URL}/paper/{paper_id}/references",
            params={"limit": limit, "fields": fields},
        )
        resp.raise_for_status()
        data = resp.json()

        references = []
        for item in data.get("data", []):
            cited = item.get("citedPaper", {})
            references.append({
                "paper_id": cited.get("paperId"),
                "title": cited.get("title", ""),
                "year": cited.get("year"),
                "authors": [a.get("name") for a in cited.get("authors", [])],
                "citation_count": cited.get("citationCount", 0),
            })

        return SkillResult.success_result(
            data={"references": references, "paper_id": paper_id, "total": len(references)},
            skill_name=self.name,
        )

    async def _get_paper(self, params: Dict[str, Any]) -> SkillResult:
        """특정 논문 상세 정보 조회"""
        paper_id = params.get("paper_id", params.get("query", ""))
        fields = "title,authors,year,abstract,citationCount,referenceCount,openAccessPdf,externalIds,url,venue,fieldsOfStudy"

        resp = await self._session.get(
            f"{SEMANTIC_SCHOLAR_BASE_URL}/paper/{paper_id}",
            params={"fields": fields},
        )
        resp.raise_for_status()
        p = resp.json()

        pdf_info = p.get("openAccessPdf") or {}
        external_ids = p.get("externalIds") or {}

        paper = {
            "paper_id": p.get("paperId"),
            "title": p.get("title", ""),
            "authors": [a.get("name") for a in p.get("authors", [])],
            "year": p.get("year"),
            "abstract": p.get("abstract", ""),
            "citation_count": p.get("citationCount", 0),
            "reference_count": p.get("referenceCount", 0),
            "open_access_pdf": pdf_info.get("url"),
            "doi": external_ids.get("DOI"),
            "arxiv_id": external_ids.get("ArXiv"),
            "url": p.get("url", ""),
            "venue": p.get("venue", ""),
            "fields_of_study": p.get("fieldsOfStudy", []),
        }

        return SkillResult.success_result(
            data=paper,
            skill_name=self.name,
        )

    async def cleanup(self) -> None:
        """HTTP 세션 정리"""
        if self._session:
            await self._session.aclose()
            self._session = None
