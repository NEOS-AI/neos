"""실행 노드의 출구는 다시 계산한다 (spec §2). 그 근거인 `base_route` 의 순수성도 고정한다."""

import ast
import inspect
import textwrap

import pytest

from neos.workflow.enums import WorkflowPathway
from neos.workflow.routing.orchestrator_router import OrchestratorRouter
from neos.workflow.state import SearchResult

pytestmark = pytest.mark.no_db

SKIP = WorkflowPathway.SKIP_ORCHESTRATORS.value
USE = WorkflowPathway.USE_ORCHESTRATORS.value

# query_intent 를 비워 둔다 -- 우선 라우팅 표(`_PRIORITY_ROUTING_MAP`)·항상 검색 intent 를 피한다.
_CHITCHAT = {"original_query": "안녕", "query_intent": "", "required_agents": [], "selected_tools": []}
_SEARCHY = {"original_query": "2025년 반도체 수출 통계는?", "query_intent": "search", "required_agents": ["knowledge_search"]}


def test_skip_stays_skip() -> None:
    assert OrchestratorRouter().route_after_skill_execution(_CHITCHAT) == SKIP


def test_use_stays_use() -> None:
    assert OrchestratorRouter().route_after_skill_execution(_SEARCHY) == USE


def test_approved_always_orchestrates() -> None:
    assert OrchestratorRouter().route_after_skill_execution({**_CHITCHAT, "approval_outcome": "approved"}) == USE


def test_skill_results_do_not_change_the_base_route() -> None:
    router = OrchestratorRouter()
    with_results = {**_CHITCHAT, "search_results": [SearchResult(source="arxiv", title="t", content="c")]}
    assert router.base_route(with_results) == router.base_route(_CHITCHAT)


def test_base_route_never_reads_search_results() -> None:
    # 출구 재계산은 "base_route 가 실행 노드의 산출을 읽지 않는다" 에 기댄다. 누가
    # base_route 가 search_results 를 보게 바꾸면 이 설계가 깨진다 -- 여기서 막는다.
    source = textwrap.dedent(inspect.getsource(OrchestratorRouter.base_route))
    constants = {node.value for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Constant)}
    assert "search_results" not in constants


def test_rejected_outcome_does_not_force_orchestration() -> None:
    assert OrchestratorRouter().route_after_skill_execution({**_CHITCHAT, "approval_outcome": "rejected"}) == SKIP
