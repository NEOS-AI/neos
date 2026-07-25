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


def test_worker_brief_v3_scopes_claims_and_grounds_exact_quotes():
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

    assert "<!-- version: 3 -->" in output
    assert "한 기관·한 결론·한 비교축" in output
    assert "기관별로 별도 claim" in output
    assert "비교 대상과 비교 방향을 모두 직접 명시" in output
    assert "하나의 연속된 문자열" in output
    assert "번역·의역·생략 부호·분리된 문장 결합" in output
    assert "source_url의 fetch 원문에서 그대로 검색" in output
    assert "분리하거나 지지 범위로 좁히고" in output
    assert "지지되지 않는 나머지는 버린다" in output
    assert "고유 source_url" in output
    assert "1개 0.55" in output
    assert "2개 0.75" in output
    assert "3개 이상 0.9" in output


def test_claim_entailment_prompt_contract():
    output = render(
        "claim_entailment",
        claims_json='[{"index":0,"claim":"c","evidence":["e"]}]',
    )

    assert "<!-- version: 1 -->" in output
    assert "keep|narrow|discard" in output
    assert "기관·행위자·날짜·대상 집단·조건·수치" in output
    assert "비교 대상과 방향·인과 표현·보고된 결론" in output
    assert "새 사실·근거·기관·날짜·수치·인과관계" in output
    assert '{"results":' in output
    assert '"index":0' in output
    assert '"action"' in output
    assert '"new_text"' in output
    assert '{"index":0,"action":"keep"}' in output
    assert (
        '{"index":1,"action":"narrow","new_text":'
        '"근거가 직접 지지하는 좁힌 claim"}' in output
    )
    assert '{"index":2,"action":"discard"}' in output
    assert "new_text는 narrow action에만 포함" in output
