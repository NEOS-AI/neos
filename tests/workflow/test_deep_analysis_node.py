"""Phase 3b: 챗은 deep analysis job의 제출자다 (D23).

D18의 블로킹 완주 노드는 사라졌다. 이 파일은 디스패치 노드의 계약을 고정한다.
"""

import pytest

pytestmark = pytest.mark.no_db


def test_initial_state_carries_conversation_id():
    """챗 경로가 run에 conversation_id를 심으려면 상태에 그 필드가 있어야 한다.

    session_id를 재사용하지 않는다 -- /api/v1/query 호출자에게 session_id는
    대화가 아니라 세션이라, 겹쳐 쓰면 run이 없는 대화를 가리킨다.
    """
    from neos.workflow import graph as graph_mod

    state = graph_mod.multi_agent_workflow._create_initial_state(
        {
            "user_id": "u1",
            "session_id": "s1",
            "query": "q",
            "conversation_id": "conv-1",
        }
    )
    assert state["conversation_id"] == "conv-1"


def test_initial_state_conversation_id_defaults_to_none():
    """대화가 아닌 호출자(/api/v1/query)는 None이어야 한다."""
    from neos.workflow import graph as graph_mod

    state = graph_mod.multi_agent_workflow._create_initial_state(
        {"user_id": "u1", "session_id": "s1", "query": "q"}
    )
    assert state["conversation_id"] is None
