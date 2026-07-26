"""SEC EDGAR Skill implementation"""

from typing import Dict, Any, Optional
import logging

import httpx

from neos.skills.base import BaseSkill, SkillResult, SkillType
from neos.config.settings import settings

logger = logging.getLogger(__name__)


class SECEdgarSkill(BaseSkill):
    """SEC EDGAR 재무 보고서 검색 스킬

    SEC EDGAR EFTS (Full-Text Search) API를 사용합니다.
    API 키 불필요, User-Agent 헤더만 필요합니다.
    """

    def __init__(self, **kwargs):
        super().__init__(
            name="sec-edgar",
            skill_type=SkillType.RESEARCH,
            description="SEC EDGAR 재무 보고서 검색 - 10-K, 10-Q, 8-K 등 기업 공시",
            capabilities=[
                "financial_filings",
                "company_reports",
                "regulatory_data",
                "financial_analysis",
            ],
            version="1.0.0",
            **kwargs,
        )
        self._client: Optional[httpx.AsyncClient] = None

    async def initialize(self) -> bool:
        """SEC EDGAR API 클라이언트 초기화"""
        try:
            user_agent = getattr(
                settings, "SEC_EDGAR_USER_AGENT", "NEOS-Research contact@neos.ai"
            )

            self._client = httpx.AsyncClient(
                headers={
                    "User-Agent": user_agent,
                    "Accept": "application/json",
                },
                timeout=30.0,
            )
            self.is_available = True
            logger.info("SEC EDGAR skill initialized successfully")
            return True

        except Exception as e:
            logger.error(f"Failed to initialize SEC EDGAR skill: {e}")
            return False

    async def execute(self, params: Dict[str, Any]) -> SkillResult:
        """SEC EDGAR 검색 실행

        Args:
            params: {
                "action": str,  # "search_filings", "company_filings", "full_text_search"
                "query": str,  # 검색어 또는 회사 ticker/CIK
                "form_type": str (optional),  # "10-K", "10-Q", "8-K" 등
                "max_results": int (optional, 기본값: 10),
                "date_from": str (optional),  # "YYYY-MM-DD"
                "date_to": str (optional),
            }
        """
        if not self.is_available or not self._client:
            return SkillResult.error_result(
                error="SEC EDGAR skill not initialized",
                skill_name=self.name,
            )

        action = params.get("action", "full_text_search")

        if action == "full_text_search":
            return await self._full_text_search(params)
        elif action == "company_filings":
            return await self._company_filings(params)
        else:
            return SkillResult.error_result(
                error=f"Unknown action: {action}",
                skill_name=self.name,
            )

    async def _full_text_search(self, params: Dict[str, Any]) -> SkillResult:
        """EDGAR 전체 텍스트 검색 (EFTS)"""
        query = params.get("query")
        if not query:
            return SkillResult.error_result(
                error="Query parameter is required",
                skill_name=self.name,
            )

        max_results = min(params.get("max_results", 10), 50)
        form_type = params.get("form_type")
        date_from = params.get("date_from")
        date_to = params.get("date_to")

        try:
            api_params = {
                "q": query,
                "dateRange": "custom" if (date_from or date_to) else None,
                "startdt": date_from,
                "enddt": date_to,
                "forms": form_type,
            }
            # Remove None values
            api_params = {k: v for k, v in api_params.items() if v is not None}

            response = await self._client.get(
                "https://efts.sec.gov/LATEST/search-index",
                params=api_params,
            )
            response.raise_for_status()
            data = response.json()

            filings = []
            for hit in data.get("hits", {}).get("hits", [])[:max_results]:
                source = hit.get("_source", {})
                filings.append({
                    "form_type": source.get("form_type", ""),
                    "company_name": source.get("display_names", [""])[0] if source.get("display_names") else "",
                    "filed_date": source.get("file_date", ""),
                    "period_of_report": source.get("period_of_report", ""),
                    "url": f"https://www.sec.gov/Archives/edgar/data/{source.get('entity_id', '')}/{source.get('file_num', '')}",
                    "description": source.get("display_description", ""),
                })

            return SkillResult.success_result(
                data={
                    "filings": filings,
                    "total_count": data.get("hits", {}).get("total", {}).get("value", 0),
                    "query": query,
                },
                skill_name=self.name,
                metadata={"action": "full_text_search", "form_type": form_type},
            )

        except httpx.HTTPStatusError as e:
            # Fallback to company_tickers endpoint
            logger.warning(f"EFTS search failed ({e.response.status_code}), trying company tickers")
            return await self._company_tickers_fallback(params)
        except Exception as e:
            logger.error(f"Failed to search SEC EDGAR: {e}")
            return SkillResult.error_result(error=str(e), skill_name=self.name)

    async def _company_filings(self, params: Dict[str, Any]) -> SkillResult:
        """특정 회사의 최근 공시 조회 (CIK 기반)"""
        query = params.get("query", "").strip().upper()
        if not query:
            return SkillResult.error_result(
                error="Company ticker or CIK is required",
                skill_name=self.name,
            )

        max_results = min(params.get("max_results", 10), 40)
        form_type = params.get("form_type")

        try:
            # First, resolve ticker to CIK
            cik = await self._resolve_cik(query)
            if not cik:
                return SkillResult.error_result(
                    error=f"Company not found: {query}",
                    skill_name=self.name,
                )

            # Pad CIK to 10 digits
            cik_padded = str(cik).zfill(10)

            response = await self._client.get(
                f"https://data.sec.gov/submissions/CIK{cik_padded}.json",
            )
            response.raise_for_status()
            data = response.json()

            recent = data.get("filings", {}).get("recent", {})
            filings = []

            forms = recent.get("form", [])
            dates = recent.get("filingDate", [])
            accessions = recent.get("accessionNumber", [])
            descriptions = recent.get("primaryDocDescription", [])

            for i in range(min(len(forms), max_results)):
                if form_type and forms[i] != form_type:
                    continue
                filings.append({
                    "form_type": forms[i],
                    "company_name": data.get("name", ""),
                    "filed_date": dates[i] if i < len(dates) else "",
                    "accession_number": accessions[i] if i < len(accessions) else "",
                    "description": descriptions[i] if i < len(descriptions) else "",
                    "url": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type={forms[i]}&dateb=&owner=include&count=10",
                    "ticker": query,
                    "cik": cik,
                })
                if len(filings) >= max_results:
                    break

            return SkillResult.success_result(
                data={
                    "filings": filings,
                    "company_name": data.get("name", ""),
                    "cik": cik,
                    "ticker": query,
                    "total_filings": len(filings),
                },
                skill_name=self.name,
                metadata={"action": "company_filings", "form_type": form_type},
            )

        except Exception as e:
            logger.error(f"Failed to get company filings: {e}")
            return SkillResult.error_result(error=str(e), skill_name=self.name)

    async def _resolve_cik(self, ticker: str) -> Optional[int]:
        """Ticker를 CIK로 변환"""
        try:
            response = await self._client.get(
                "https://www.sec.gov/files/company_tickers.json",
            )
            response.raise_for_status()
            data = response.json()

            for entry in data.values():
                if entry.get("ticker", "").upper() == ticker.upper():
                    return entry.get("cik_str")

            # Maybe the query is already a CIK
            if ticker.isdigit():
                return int(ticker)

            return None
        except Exception as e:
            logger.error(f"Failed to resolve CIK for {ticker}: {e}")
            return None

    async def _company_tickers_fallback(self, params: Dict[str, Any]) -> SkillResult:
        """EFTS 실패 시 company_tickers로 fallback"""
        query = params.get("query", "").lower()

        try:
            response = await self._client.get(
                "https://www.sec.gov/files/company_tickers.json",
            )
            response.raise_for_status()
            data = response.json()

            matches = []
            for entry in data.values():
                title = entry.get("title", "").lower()
                ticker = entry.get("ticker", "").lower()
                if query in title or query in ticker:
                    matches.append({
                        "company_name": entry.get("title", ""),
                        "ticker": entry.get("ticker", ""),
                        "cik": entry.get("cik_str"),
                    })
                    if len(matches) >= 10:
                        break

            return SkillResult.success_result(
                data={
                    "companies": matches,
                    "total_results": len(matches),
                    "query": params.get("query"),
                    "note": "Full-text search unavailable; showing matching companies.",
                },
                skill_name=self.name,
                metadata={"action": "company_tickers_fallback"},
            )

        except Exception as e:
            logger.error(f"SEC EDGAR fallback failed: {e}")
            return SkillResult.error_result(error=str(e), skill_name=self.name)

    async def cleanup(self) -> None:
        """리소스 정리"""
        if self._client:
            await self._client.aclose()
            self._client = None
        self.is_available = False
        logger.info("SEC EDGAR skill cleaned up")
