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
