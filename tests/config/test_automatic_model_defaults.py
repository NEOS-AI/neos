"""자동 워크로드용 모델 설정은 값을 고정하지 않고 역할 라우팅에 위임해야 한다.

`None` = provider × 역할 기본값, 문자열 = 배포/기능 오버라이드.
"""

from unittest.mock import patch

import pytest
import yaml

from neos.config.schema import (
    ContextOptimizationConfig,
    KnowledgeGraphExtractionConfig,
    LLMConfig,
)


pytestmark = pytest.mark.no_db


def test_automatic_model_settings_default_to_role_routing():
    assert LLMConfig().model is None
    assert KnowledgeGraphExtractionConfig().model is None
    assert ContextOptimizationConfig().tool_result_summarization_model is None


def test_committed_default_profile_does_not_pin_automatic_models():
    with open("config/neos.default.yaml", encoding="utf-8") as handle:
        profile = yaml.safe_load(handle)

    assert profile["llm"].get("model") is None
    assert profile["knowledge_graph"]["extraction"].get("model") is None
    assert profile["context_optimization"].get("tool_result_summarization_model") is None


def test_knowledge_graph_extractor_defers_to_role_routing():
    """추출기는 create_llm에 None을 넘겨 everyday 역할 + 폴백 경로를 유지한다."""
    from neos.pipelines.document import knowledge_graph as kg_module

    with patch.object(kg_module, "create_llm") as create_llm, patch.object(
        kg_module, "get_default_model", return_value="claude-sonnet-5"
    ):
        extractor = kg_module.KnowledgeGraphExtractor()

    assert create_llm.call_args.kwargs["model"] is None
    assert extractor.model_name == "claude-sonnet-5"
