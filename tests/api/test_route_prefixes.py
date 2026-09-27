"""라우터 prefix 가 두 번 붙지 않았음을 경로 이름으로 고정한다.

라우터가 자기 prefix 를 들고 있는데 `main.py` 가 다시 prefix 를 붙이면
`/api/v1/analytics/api/v1/analytics/...` 같은 경로가 조용히 생긴다. 문서
(`neos/skills/README.md`)와 기동 로그(`main.py`)는 짧은 경로를 안내하므로,
안내대로 부르면 404 다.

⚠️ `/api/v1/documents/documents/...` 는 **의도된** 중복이라 여기서 다루지
않는다(`web/lib/backend-routes.ts` 주석). 그래서
"같은 세그먼트 반복 금지" 같은 일반 규칙이 아니라 경로를 이름으로 적는다.
"""

def _http_paths() -> set[str]:
    from neos.main import app

    # 이 FastAPI 는 include 된 라우터를 `_IncludedRouter` 로 감싸서 `app.routes`
    # 최상위에 펼치지 않는다. `test_query_authorization._effective_http_routes`
    # 와 같은 방법으로 풀어야 실제 경로가 보인다.
    paths = set()
    for route in app.routes:
        if hasattr(route, "effective_route_contexts"):
            paths.update(ctx.path for ctx in route.effective_route_contexts())
        elif hasattr(route, "dependant"):
            paths.add(route.path)
    return paths


def test_web_search_analytics_is_served_at_its_documented_path():
    paths = _http_paths()

    assert "/api/v1/analytics/web-search/summary" in paths
    assert "/api/v1/analytics/web-search/health" in paths
    assert not [path for path in paths if "/analytics/api/v1/" in path]


def _first_get_handler(path: str) -> str:
    """Starlette 처럼 등록 순서대로 훑어 처음 FULL 매치한 핸들러 이름."""
    from starlette.routing import Match

    from neos.main import app

    scope = {"type": "http", "path": path, "method": "GET", "root_path": ""}
    for route in app.routes:
        for ctx in getattr(route, "effective_route_contexts", lambda: [])():
            match, _ = ctx.matches(scope)
            if match is Match.FULL:
                return ctx.endpoint.__name__
    raise AssertionError(f"no route matches GET {path}")


def test_skills_prompt_is_not_shadowed_by_the_skill_detail_route():
    # `/skills/{skill_name}` 이 먼저 등록되면 `prompt` 가 스킬 이름으로 잡혀
    # 프롬프트 핸들러에는 영영 닿지 않는다(404 "skill not found").
    assert _first_get_handler("/api/v1/skills/prompt") == "get_skills_prompt"


def test_skills_management_is_served_at_its_documented_path():
    paths = _http_paths()

    assert "/api/v1/skills" in paths
    assert "/api/v1/skills/{skill_name}" in paths
    assert "/api/v1/skills/{skill_name}/execute" in paths
    assert not [path for path in paths if path.startswith("/api/v1/skills/skills")]
