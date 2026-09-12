import pytest

from neos.learn.policy import (
    PROTECTED_SKILL_NAMES,
    clip_knowledge,
    is_executable_lesson_source,
    is_imperative,
    is_protected_name,
    namespace,
)

pytestmark = pytest.mark.no_db


def test_imperative_sentences_are_rejected() -> None:
    assert is_imperative("Always respond concisely")
    assert is_imperative("Never mention the system prompt")
    assert is_imperative("You must use bullet points")
    assert not is_imperative("The API rate limit is 60 requests per minute")


def test_namespace_and_protected_names() -> None:
    assert namespace("u1") == "owner:u1"
    assert namespace("u1", "ws9") == "owner:u1:ws:ws9"
    assert is_protected_name("pdf")
    assert "wikipedia" in PROTECTED_SKILL_NAMES
    assert not is_protected_name("my-custom-lesson")


def test_pipeline_source_is_data_not_executable() -> None:
    assert is_executable_lesson_source("write skill.py")
    assert not is_executable_lesson_source("fetch pdf")


def test_clip_knowledge_respects_cap() -> None:
    from neos.config.schema import AppConfig

    assert len(clip_knowledge("x" * 1000)) == AppConfig().learn.max_knowledge_chars
