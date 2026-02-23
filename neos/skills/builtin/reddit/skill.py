"""Reddit Search Skill implementation"""

from typing import Dict, Any, Optional
import logging

import httpx

from neos.skills.base import BaseSkill, SkillResult, SkillType
from neos.config.settings import settings

logger = logging.getLogger(__name__)


class RedditSkill(BaseSkill):
    """Reddit 커뮤니티 토론 및 의견 검색 스킬

    Reddit API를 사용하여 서브레딧, 게시물, 댓글을 검색합니다.
    OAuth2 인증을 통해 접근합니다.
    """

    def __init__(self, **kwargs):
        super().__init__(
            name="reddit",
            skill_type=SkillType.RESEARCH,
            description="Reddit 커뮤니티 토론 검색 - 의견 수렴, 비교 토론, 사용자 경험",
            capabilities=[
                "community_opinion",
                "discussion_search",
                "subreddit_analysis",
                "comparison",
            ],
            version="1.0.0",
            **kwargs,
        )
        self._client: Optional[httpx.AsyncClient] = None
        self._access_token: Optional[str] = None

    async def initialize(self) -> bool:
        """Reddit API 클라이언트 초기화 (OAuth2)"""
        try:
            client_id = getattr(settings, "REDDIT_CLIENT_ID", None)
            client_secret = getattr(settings, "REDDIT_CLIENT_SECRET", None)
            user_agent = getattr(settings, "REDDIT_USER_AGENT", "NEOS-Research-Engine/1.0")

            if not client_id or not client_secret:
                logger.warning(
                    "Reddit skill: REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET not set. "
                    "Using unauthenticated access (limited)."
                )
                # Unauthenticated access via old.reddit.com JSON API
                self._client = httpx.AsyncClient(
                    base_url="https://www.reddit.com",
                    headers={"User-Agent": user_agent},
                    timeout=30.0,
                )
                self.is_available = True
                logger.info("Reddit skill initialized (unauthenticated)")
                return True

            # OAuth2 token acquisition
            auth_client = httpx.AsyncClient(timeout=10.0)
            try:
                token_response = await auth_client.post(
                    "https://www.reddit.com/api/v1/access_token",
                    auth=(client_id, client_secret),
                    data={"grant_type": "client_credentials"},
                    headers={"User-Agent": user_agent},
                )
                token_response.raise_for_status()
                token_data = token_response.json()
                self._access_token = token_data["access_token"]
            finally:
                await auth_client.aclose()

            self._client = httpx.AsyncClient(
                base_url="https://oauth.reddit.com",
                headers={
                    "Authorization": f"Bearer {self._access_token}",
                    "User-Agent": user_agent,
                },
                timeout=30.0,
            )
            self.is_available = True
            logger.info("Reddit skill initialized (authenticated)")
            return True

        except Exception as e:
            logger.error(f"Failed to initialize Reddit skill: {e}")
            return False

    async def execute(self, params: Dict[str, Any]) -> SkillResult:
        """Reddit 검색 실행

        Args:
            params: {
                "action": str,  # "search", "subreddit_search"
                "query": str,
                "subreddit": str (optional),
                "max_results": int (optional, 기본값: 10),
                "sort": str (optional),  # "relevance", "hot", "new", "top"
                "time_filter": str (optional),  # "hour", "day", "week", "month", "year", "all"
            }
        """
        if not self.is_available or not self._client:
            return SkillResult.error_result(
                error="Reddit skill not initialized",
                skill_name=self.name,
            )

        action = params.get("action", "search")

        if action == "search":
            return await self._search_posts(params)
        elif action == "subreddit_search":
            return await self._search_subreddit(params)
        else:
            return SkillResult.error_result(
                error=f"Unknown action: {action}",
                skill_name=self.name,
            )

    async def _search_posts(self, params: Dict[str, Any]) -> SkillResult:
        """Reddit 게시물 검색"""
        query = params.get("query")
        if not query:
            return SkillResult.error_result(
                error="Query parameter is required",
                skill_name=self.name,
            )

        max_results = min(params.get("max_results", 10), 25)
        sort = params.get("sort", "relevance")
        time_filter = params.get("time_filter", "all")
        subreddit = params.get("subreddit")

        try:
            endpoint = f"/r/{subreddit}/search" if subreddit else "/search"
            api_params = {
                "q": query,
                "sort": sort,
                "t": time_filter,
                "limit": max_results,
                "restrict_sr": "true" if subreddit else "false",
            }

            # Unauthenticated access needs .json suffix
            if not self._access_token:
                endpoint += ".json"

            response = await self._client.get(endpoint, params=api_params)
            response.raise_for_status()
            data = response.json()

            posts = []
            children = data.get("data", {}).get("children", [])
            for child in children:
                post = child.get("data", {})
                posts.append({
                    "title": post.get("title", ""),
                    "subreddit": post.get("subreddit", ""),
                    "author": post.get("author", "[deleted]"),
                    "score": post.get("score", 0),
                    "num_comments": post.get("num_comments", 0),
                    "url": f"https://www.reddit.com{post.get('permalink', '')}",
                    "selftext": (post.get("selftext") or "")[:500],
                    "created_utc": post.get("created_utc"),
                    "is_self": post.get("is_self", False),
                    "link_flair_text": post.get("link_flair_text"),
                })

            return SkillResult.success_result(
                data={
                    "posts": posts,
                    "total_results": len(posts),
                    "query": query,
                },
                skill_name=self.name,
                metadata={
                    "action": "search",
                    "subreddit": subreddit,
                    "sort": sort,
                },
            )

        except httpx.HTTPStatusError as e:
            logger.error(f"Reddit API error: {e.response.status_code}")
            return SkillResult.error_result(
                error=f"Reddit API error: {e.response.status_code}",
                skill_name=self.name,
            )
        except Exception as e:
            logger.error(f"Failed to search Reddit: {e}")
            return SkillResult.error_result(error=str(e), skill_name=self.name)

    async def _search_subreddit(self, params: Dict[str, Any]) -> SkillResult:
        """서브레딧 검색"""
        query = params.get("query")
        if not query:
            return SkillResult.error_result(
                error="Query parameter is required",
                skill_name=self.name,
            )

        max_results = min(params.get("max_results", 5), 10)

        try:
            endpoint = "/subreddits/search"
            if not self._access_token:
                endpoint += ".json"

            response = await self._client.get(
                endpoint,
                params={"q": query, "limit": max_results},
            )
            response.raise_for_status()
            data = response.json()

            subreddits = []
            for child in data.get("data", {}).get("children", []):
                sr = child.get("data", {})
                subreddits.append({
                    "name": sr.get("display_name", ""),
                    "title": sr.get("title", ""),
                    "description": (sr.get("public_description") or "")[:300],
                    "subscribers": sr.get("subscribers", 0),
                    "url": f"https://www.reddit.com{sr.get('url', '')}",
                })

            return SkillResult.success_result(
                data={
                    "subreddits": subreddits,
                    "total_results": len(subreddits),
                    "query": query,
                },
                skill_name=self.name,
                metadata={"action": "subreddit_search"},
            )

        except Exception as e:
            logger.error(f"Failed to search subreddits: {e}")
            return SkillResult.error_result(error=str(e), skill_name=self.name)

    async def cleanup(self) -> None:
        """리소스 정리"""
        if self._client:
            await self._client.aclose()
            self._client = None
        self._access_token = None
        self.is_available = False
        logger.info("Reddit skill cleaned up")
