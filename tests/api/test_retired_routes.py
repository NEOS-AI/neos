"""딥 하네스·코딩 루프로 대체되어 제거한 라우트가 다시 생기지 않는가.

2026-09-27 에 프론트·게이트웨이·nginx·스크립트 어디에서도 부르지 않는 라우트를
걷어 냈다. 호출자 조사는 그때의 사실이고, 이 목록은 그 결정을 고정한다 --
되살리려면 여기서 지우는 것부터 해야 하므로 되살림이 판단으로 남는다.

유지하는 이웃: `/api/v1/health`(docker-compose 헬스체크), 표준 챗 스트림,
deep-analysis(비동기 조사의 대체), 코딩 루프.
"""

from __future__ import annotations

import pytest

RETIRED = {
    # similarity chat -- 표준 챗 스트림이 대체
    ("POST", "/api/v1/chat/conversations/{conversation_id}/messages/similarity"),
    ("POST", "/api/v1/chat/conversations/{conversation_id}/messages/similarity/stream"),
    (
        "POST",
        "/api/v1/chat/conversations/{conversation_id}/messages/similarity/cross-conversation",
    ),
    (
        "POST",
        "/api/v1/chat/conversations/{conversation_id}/messages/similarity/high-confidence",
    ),
    ("GET", "/api/v1/chat/conversations/{conversation_id}/similarity/config"),
    ("GET", "/api/v1/chat/conversations/{conversation_id}/similarity/analytics"),
    # unified -- 챗 경로와 기능이 겹쳤다
    ("POST", "/api/v1/unified/process"),
    ("POST", "/api/v1/unified/process/stream"),
    ("POST", "/api/v1/unified/process/upload"),
    ("POST", "/api/v1/unified/process/upload/stream"),
    ("GET", "/api/v1/unified/health"),
    # research 플랫폼 -- 딥 하네스가 대체. 워크플로우가 내부에서 쓰는 템플릿 자동 적용과
    # 세션 기록은 서비스라서 남는다.
    ("GET", "/api/v1/research/sessions"),
    ("GET", "/api/v1/research/sessions/{session_id}"),
    ("POST", "/api/v1/research/sessions/branch"),
    ("GET", "/api/v1/research/sessions/{session_id}/branches"),
    ("POST", "/api/v1/research/sessions/continue"),
    ("POST", "/api/v1/research/async"),
    ("GET", "/api/v1/research/async/{job_id}/status"),
    ("GET", "/api/v1/research/stream/{session_id}"),
    ("GET", "/api/v1/research/{session_id}/export"),
    ("POST", "/api/v1/research/refine/investigate-claim"),
    ("POST", "/api/v1/research/refine/reject-source"),
    ("POST", "/api/v1/research/refine/adjust-trust"),
    ("POST", "/api/v1/research/refine/redirect"),
    ("POST", "/api/v1/research/refine/more-detail"),
    ("GET", "/api/v1/research/templates"),
    ("GET", "/api/v1/research/templates/{template_id}"),
    # deep-research -- 비동기 조사는 deep-analysis 가 맡는다
    ("POST", "/api/v1/deep-research/start"),
    ("GET", "/api/v1/deep-research/{report_id}/stream"),
    ("GET", "/api/v1/deep-research/{report_id}"),
    ("GET", "/api/v1/conversations/{conversation_id}/deep-research"),
    # 레거시 쿼리 API -- 대화 밖 워크플로우 진입점과 그 부가 기능. `/health` 만 남는다.
    ("POST", "/api/v1/query"),
    ("POST", "/api/v1/query/stream"),
    ("GET", "/api/v1/trending"),
    ("GET", "/api/v1/related/{query_id}"),
    ("GET", "/api/v1/history/{user_id}"),
    ("DELETE", "/api/v1/cache/{cache_key}"),
    ("GET", "/api/v1/stats/system"),
    ("GET", "/api/v1/hyper-research"),
    ("GET", "/api/v1/hyper-research/{report_uuid}"),
    # RAG 문서 부가 기능 -- 프론트는 upload 와 detail 만 쓴다(DELETE 도 남긴다).
    # 이중 prefix 는 의도다(`web/lib/backend-routes.ts`).
    ("GET", "/api/v1/documents/documents/"),
    ("POST", "/api/v1/documents/documents/search"),
    ("GET", "/api/v1/documents/documents/{document_id}/chunks"),
    ("GET", "/api/v1/documents/documents/{document_id}/knowledge-graph"),
}


def _routes() -> set[tuple[str, str]]:
    from neos.main import app

    found = set()
    for route in app.routes:
        contexts = (
            route.effective_route_contexts()
            if hasattr(route, "effective_route_contexts")
            else [route]
        )
        for ctx in contexts:
            for method in getattr(ctx, "methods", None) or {"WS"}:
                found.add((method, ctx.path))
    return found


@pytest.mark.parametrize("method,path", sorted(RETIRED))
def test_retired_route_is_not_served(method, path):
    assert (method, path) not in _routes()


def test_health_stays_public():
    assert ("GET", "/api/v1/health") in _routes()


def test_only_ticketed_coding_sockets_declare_websocket_routes():
    """레거시 WebSocket(`/ws/{session_id}`, `/ws/query/*`, `/chat/ws/{id}`)은 인증 없이
    열려 있어서 비디버그에서는 `_include_router_for_runtime` 이 떼어 냈고, 프론트는
    SSE 를 쓴다. 그래서 앱 라우트로는 부재를 확인할 수 없다(테스트 앱은 비디버그다) --
    선언 자체를 센다. 티켓 인증을 가진 코딩 소켓 둘만 남는다.
    """
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[2] / "neos" / "api"
    declaring = sorted(
        str(path.relative_to(root))
        for path in root.rglob("*.py")
        if "__pycache__" not in path.parts and ".websocket(" in path.read_text()
    )
    assert declaring == [
        "handlers/coding_workspace_ws_handlers.py",
        "handlers/coding_ws_handlers.py",
    ]
