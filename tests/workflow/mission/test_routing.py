from neos.workflow.enums import AutonomyLevel, IntentType
from neos.workflow.mission import routing as mission_routing
from neos.workflow.mission.routing import should_use_mission_runtime


def test_routes_deep_research_to_mission_runtime():
    state = {
        "query_intent": IntentType.DEEP_RESEARCH.value,
        "query_classification": {"complexity_score": 0.4},
        "required_agents": ["deep_research"],
        "autonomy_level": AutonomyLevel.ASSISTED.value,
    }

    assert should_use_mission_runtime(state) is True


def test_routes_complex_multi_agent_request_to_mission_runtime():
    state = {
        "query_intent": IntentType.COMPLEX_ANALYSIS.value,
        "query_classification": {"complexity_score": 0.72},
        "required_agents": ["realtime_info_search", "comparative_analysis"],
        "autonomy_level": AutonomyLevel.ASSISTED.value,
    }

    assert should_use_mission_runtime(state) is True


def test_manual_request_with_planned_actions_uses_mission_runtime():
    state = {
        "query_intent": IntentType.REALTIME_INFO.value,
        "query_classification": {"complexity_score": 0.3},
        "required_agents": ["realtime_info_search"],
        "autonomy_level": AutonomyLevel.MANUAL.value,
    }

    assert should_use_mission_runtime(state) is True


def test_simple_conversation_keeps_legacy_path():
    state = {
        "query_intent": IntentType.SIMPLE.value,
        "query_classification": {"complexity_score": 0.1},
        "required_agents": [],
        "selected_tools": [],
        "autonomy_level": AutonomyLevel.ASSISTED.value,
    }

    assert should_use_mission_runtime(state) is False


def test_hyper_deep_intent_keeps_legacy_path_when_wrapper_disabled(monkeypatch):
    monkeypatch.setattr(
        mission_routing.settings,
        "HYPER_DEEP_AGENT_ENABLED",
        False,
    )
    state = {
        "query_intent": IntentType.HYPER_DEEP_RESEARCH.value,
        "query_classification": {"complexity_score": 0.95},
        "required_agents": ["deep_research"],
        "selected_tools": [],
        "autonomy_level": AutonomyLevel.ASSISTED.value,
    }

    assert should_use_mission_runtime(state) is False
