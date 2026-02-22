"""News API Skill implementation

NewsAPI.org를 통해 80,000+ 뉴스 소스에서 실시간 뉴스를 검색합니다.
realtime_info intent의 핵심 소스로 활용됩니다.
"""

from typing import Dict, Any
import logging

from neos.skills.base import BaseSkill, SkillResult, SkillType
from neos.config.settings import settings

logger = logging.getLogger(__name__)


class NewsApiSkill(BaseSkill):
    """NewsAPI 실시간 뉴스 검색 스킬"""

    def __init__(self, **kwargs):
        super().__init__(
            name="news_api",
            skill_type=SkillType.RESEARCH,
            description="NewsAPI: 80,000+ 소스에서 실시간 뉴스 검색",
            capabilities=[
                "news_search",
                "realtime_news",
                "top_headlines",
                "news_by_topic",
                "news_by_source",
            ],
            version="1.0.0",
            **kwargs
        )
        self._session = None
        self._api_key = None
        self._base_url = "https://newsapi.org/v2"

    async def initialize(self) -> bool:
        """HTTP 세션 초기화"""
        api_key = getattr(settings, "NEWS_API_KEY", None)
        if not api_key:
            logger.warning("[NewsAPI] NEWS_API_KEY not configured, skill disabled")
            return False

        try:
            import httpx

            self._api_key = api_key
            self._session = httpx.AsyncClient(
                timeout=httpx.Timeout(15.0),
                headers={"X-Api-Key": api_key},
            )
            self.is_available = True
            logger.info("News API skill initialized successfully")
            return True

        except ImportError:
            logger.warning("httpx not available for News API skill")
            return False
        except Exception as e:
            logger.error(f"Failed to initialize News API skill: {e}")
            return False

    async def execute(self, params: Dict[str, Any]) -> SkillResult:
        """뉴스 검색 실행

        Args:
            params: {
                "action": str,  # "search", "top_headlines"
                "query": str,  # 검색 쿼리
                "max_results": int (optional),  # 최대 결과 수 (기본값: 10)
                "language": str (optional),  # 언어 코드 (기본값: "en")
                "sort_by": str (optional),  # "publishedAt", "relevancy", "popularity"
                "from_date": str (optional),  # ISO 8601 시작 날짜
                "to_date": str (optional),  # ISO 8601 종료 날짜
                "country": str (optional),  # top_headlines 전용, 국가 코드
                "category": str (optional),  # top_headlines 전용
            }
        """
        if not self.is_available or not self._session:
            return SkillResult.error_result(
                "News API skill not initialized (NEWS_API_KEY required)",
                skill_name=self.name
            )

        action = params.get("action", "search")

        try:
            if action == "search":
                return await self._search_news(params)
            elif action == "top_headlines":
                return await self._top_headlines(params)
            else:
                return SkillResult.error_result(
                    f"Unknown action: {action}",
                    skill_name=self.name
                )
        except Exception as e:
            logger.error(f"[NewsAPI] Action '{action}' failed: {e}")
            return SkillResult.error_result(str(e), skill_name=self.name)

    async def _search_news(self, params: Dict[str, Any]) -> SkillResult:
        """뉴스 검색 (everything endpoint)"""
        query = params.get("query", "")
        page_size = min(params.get("max_results", 10), 100)

        request_params = {
            "q": query,
            "pageSize": page_size,
            "language": params.get("language", "en"),
            "sortBy": params.get("sort_by", "publishedAt"),
        }

        if params.get("from_date"):
            request_params["from"] = params["from_date"]
        if params.get("to_date"):
            request_params["to"] = params["to_date"]

        resp = await self._session.get(
            f"{self._base_url}/everything",
            params=request_params,
        )
        resp.raise_for_status()
        data = resp.json()

        if data.get("status") != "ok":
            return SkillResult.error_result(
                data.get("message", "NewsAPI error"),
                skill_name=self.name
            )

        articles = self._format_articles(data.get("articles", []))

        return SkillResult.success_result(
            data={
                "articles": articles,
                "total_results": data.get("totalResults", 0),
                "query": query,
            },
            skill_name=self.name,
            metadata={"action": "search", "page_size": page_size},
        )

    async def _top_headlines(self, params: Dict[str, Any]) -> SkillResult:
        """주요 뉴스 (top-headlines endpoint)"""
        page_size = min(params.get("max_results", 10), 100)

        request_params = {
            "pageSize": page_size,
            "country": params.get("country", "us"),
        }

        if params.get("query"):
            request_params["q"] = params["query"]
        if params.get("category"):
            request_params["category"] = params["category"]

        resp = await self._session.get(
            f"{self._base_url}/top-headlines",
            params=request_params,
        )
        resp.raise_for_status()
        data = resp.json()

        if data.get("status") != "ok":
            return SkillResult.error_result(
                data.get("message", "NewsAPI error"),
                skill_name=self.name
            )

        articles = self._format_articles(data.get("articles", []))

        return SkillResult.success_result(
            data={
                "articles": articles,
                "total_results": data.get("totalResults", 0),
            },
            skill_name=self.name,
            metadata={"action": "top_headlines"},
        )

    def _format_articles(self, raw_articles: list) -> list:
        """API 응답을 표준 형식으로 변환"""
        return [
            {
                "title": a.get("title", ""),
                "description": a.get("description", ""),
                "url": a.get("url", ""),
                "published_at": a.get("publishedAt", ""),
                "source": (a.get("source") or {}).get("name", ""),
                "author": a.get("author", ""),
                "content": a.get("content", ""),
                "image_url": a.get("urlToImage", ""),
            }
            for a in raw_articles
            if a.get("title")  # [Removed] 태그가 붙은 기사 제외
        ]

    async def cleanup(self) -> None:
        """HTTP 세션 정리"""
        if self._session:
            await self._session.aclose()
            self._session = None
