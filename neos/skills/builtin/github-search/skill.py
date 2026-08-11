"""GitHub Search Skill implementation"""

from typing import Dict, Any, Optional
import logging

import httpx

from neos.skills.base import BaseSkill, SkillResult, SkillType
from neos.config.settings import settings

logger = logging.getLogger(__name__)


class GitHubSearchSkill(BaseSkill):
    """GitHub 코드 및 레포지토리 검색 스킬

    GitHub REST API v3를 사용하여 레포지토리, 코드, 이슈를 검색합니다.
    API 토큰 없이도 동작하지만, 인증 시 rate limit이 증가합니다.
    """

    def __init__(self, **kwargs):
        super().__init__(
            name="github-search",
            skill_type=SkillType.RESEARCH,
            description="GitHub 코드/레포지토리/이슈 검색 - 오픈소스 프로젝트, 코드 예제, 기술 토론",
            capabilities=[
                "code_search",
                "repository_search",
                "issue_search",
                "technical_analysis",
            ],
            version="1.0.0",
            **kwargs,
        )
        self._client: Optional[httpx.AsyncClient] = None

    async def initialize(self) -> bool:
        """GitHub API 클라이언트 초기화"""
        try:
            headers = {
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": "NEOS-Research-Engine/1.0",
            }
            token = getattr(settings, "GITHUB_API_TOKEN", None)
            if token:
                headers["Authorization"] = f"token {token}"

            self._client = httpx.AsyncClient(
                base_url="https://api.github.com",
                headers=headers,
                timeout=30.0,
            )
            self.is_available = True
            logger.info("GitHub Search skill initialized successfully")
            return True

        except Exception as e:
            logger.error(f"Failed to initialize GitHub Search skill: {e}")
            return False

    async def execute(self, params: Dict[str, Any]) -> SkillResult:
        """GitHub 검색 실행

        Args:
            params: {
                "action": str,  # "search_repos", "search_code", "search_issues"
                "query": str,
                "max_results": int (optional, 기본값: 10),
                "language": str (optional),  # 프로그래밍 언어 필터
                "sort": str (optional),  # "stars", "forks", "updated"
            }
        """
        if not self.is_available or not self._client:
            return SkillResult.error_result(
                error="GitHub Search skill not initialized",
                skill_name=self.name,
            )

        action = params.get("action", "search_repos")

        if action == "search_repos":
            return await self._search_repositories(params)
        elif action == "search_code":
            return await self._search_code(params)
        elif action == "search_issues":
            return await self._search_issues(params)
        else:
            return SkillResult.error_result(
                error=f"Unknown action: {action}",
                skill_name=self.name,
            )

    async def _search_repositories(self, params: Dict[str, Any]) -> SkillResult:
        """레포지토리 검색"""
        query = params.get("query")
        if not query:
            return SkillResult.error_result(
                error="Query parameter is required",
                skill_name=self.name,
            )

        max_results = min(params.get("max_results", 10), 30)
        language = params.get("language")
        sort = params.get("sort", "best-match")

        search_query = query
        if language:
            search_query += f" language:{language}"

        try:
            response = await self._client.get(
                "/search/repositories",
                params={
                    "q": search_query,
                    "sort": sort if sort != "best-match" else "",
                    "per_page": max_results,
                },
            )
            response.raise_for_status()
            data = response.json()

            repos = []
            for item in data.get("items", []):
                repos.append({
                    "name": item["full_name"],
                    "description": item.get("description", ""),
                    "url": item["html_url"],
                    "stars": item["stargazers_count"],
                    "forks": item["forks_count"],
                    "language": item.get("language"),
                    "topics": item.get("topics", []),
                    "updated_at": item.get("updated_at"),
                    "license": item.get("license", {}).get("spdx_id") if item.get("license") else None,
                })

            return SkillResult.success_result(
                data={
                    "repositories": repos,
                    "total_count": data.get("total_count", 0),
                    "query": query,
                },
                skill_name=self.name,
                metadata={"action": "search_repos", "max_results": max_results},
            )

        except httpx.HTTPStatusError as e:
            logger.error(f"GitHub API error: {e.response.status_code}")
            return SkillResult.error_result(
                error=f"GitHub API error: {e.response.status_code}",
                skill_name=self.name,
            )
        except Exception as e:
            logger.error(f"Failed to search GitHub repositories: {e}")
            return SkillResult.error_result(error=str(e), skill_name=self.name)

    async def _search_code(self, params: Dict[str, Any]) -> SkillResult:
        """코드 검색"""
        query = params.get("query")
        if not query:
            return SkillResult.error_result(
                error="Query parameter is required",
                skill_name=self.name,
            )

        max_results = min(params.get("max_results", 10), 30)
        language = params.get("language")

        search_query = query
        if language:
            search_query += f" language:{language}"

        try:
            response = await self._client.get(
                "/search/code",
                params={"q": search_query, "per_page": max_results},
            )
            response.raise_for_status()
            data = response.json()

            code_results = []
            for item in data.get("items", []):
                code_results.append({
                    "name": item["name"],
                    "path": item["path"],
                    "repository": item["repository"]["full_name"],
                    "url": item["html_url"],
                    "score": item.get("score", 0),
                })

            return SkillResult.success_result(
                data={
                    "code_results": code_results,
                    "total_count": data.get("total_count", 0),
                    "query": query,
                },
                skill_name=self.name,
                metadata={"action": "search_code", "max_results": max_results},
            )

        except httpx.HTTPStatusError as e:
            logger.error(f"GitHub API error: {e.response.status_code}")
            return SkillResult.error_result(
                error=f"GitHub API error: {e.response.status_code}",
                skill_name=self.name,
            )
        except Exception as e:
            logger.error(f"Failed to search GitHub code: {e}")
            return SkillResult.error_result(error=str(e), skill_name=self.name)

    async def _search_issues(self, params: Dict[str, Any]) -> SkillResult:
        """이슈/PR 검색"""
        query = params.get("query")
        if not query:
            return SkillResult.error_result(
                error="Query parameter is required",
                skill_name=self.name,
            )

        max_results = min(params.get("max_results", 10), 30)

        try:
            response = await self._client.get(
                "/search/issues",
                params={
                    "q": query,
                    "sort": "relevance",
                    "per_page": max_results,
                },
            )
            response.raise_for_status()
            data = response.json()

            issues = []
            for item in data.get("items", []):
                issues.append({
                    "title": item["title"],
                    "body": (item.get("body") or "")[:500],
                    "url": item["html_url"],
                    "state": item["state"],
                    "comments": item["comments"],
                    "created_at": item["created_at"],
                    "labels": [l["name"] for l in item.get("labels", [])],
                    "is_pull_request": "pull_request" in item,
                })

            return SkillResult.success_result(
                data={
                    "issues": issues,
                    "total_count": data.get("total_count", 0),
                    "query": query,
                },
                skill_name=self.name,
                metadata={"action": "search_issues", "max_results": max_results},
            )

        except httpx.HTTPStatusError as e:
            logger.error(f"GitHub API error: {e.response.status_code}")
            return SkillResult.error_result(
                error=f"GitHub API error: {e.response.status_code}",
                skill_name=self.name,
            )
        except Exception as e:
            logger.error(f"Failed to search GitHub issues: {e}")
            return SkillResult.error_result(error=str(e), skill_name=self.name)

    async def cleanup(self) -> None:
        """리소스 정리"""
        if self._client:
            await self._client.aclose()
            self._client = None
        self.is_available = False
        logger.info("GitHub Search skill cleaned up")
