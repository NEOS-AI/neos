import pytest

from neos.workflow.deep_analysis.prompt_loader import load_prompt, render


pytestmark = pytest.mark.no_db


def test_all_m1_prompts_have_version_header():
    for name in (
        "decompose",
        "worker_brief",
        "node_summary",
        "final_compose",
    ):
        assert load_prompt(name).lstrip().startswith("<!-- version:")


def test_render_replaces_values_without_consuming_json_braces():
    output = render(
        "decompose",
        question_text="What is MoE?",
        prior_findings="none",
        dead_ends="none",
    )

    assert "What is MoE?" in output
    assert "{question_text}" not in output
    assert '{"subquestions":' in output


def test_worker_brief_keeps_verified_findings_before_repairs():
    output = render(
        "worker_brief",
        question_text="q",
        verified_summaries="verified",
        dead_ends="dead",
        repair_count=1,
        repairs="repair",
        token_cap=2000,
        fetched_evidence="<evidence>source</evidence>",
    )

    assert output.index("[3]") < output.index("[4]")
    assert "<evidence>source</evidence>" in output
    assert "self_assessment" in output


def test_worker_brief_v2_calibrates_atomic_claims_and_confidence():
    output = render(
        "worker_brief",
        question_text="q",
        verified_summaries="none",
        dead_ends="none",
        repair_count=0,
        repairs="none",
        token_cap=2000,
        confidence_cap_one=0.55,
        confidence_cap_two=0.75,
        confidence_cap_three_plus=0.9,
        fetched_evidence="<evidence>source</evidence>",
    )

    assert "독립적으로 검증 가능한 명제 하나" in output
    assert "대상" in output and "시점" in output and "조건" in output
    assert "상관관계" in output and "인과" in output
    assert "고유 source_url" in output
    assert "1개 0.55" in output
    assert "2개 0.75" in output
    assert "3개 이상 0.9" in output
