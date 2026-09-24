"""리덕션 층의 인용 손실을 D92 의 세 후보에 귀속하는 판독기.

DB 도 네트워크도 LLM 도 쓰지 않는다 -- 원장 페이로드를 손으로 짓는다.

§8.1.2 의 규율("계측기가 도는지 보는 것은 통과를 보는 게 아니라 실패해야 할 때
실패하는지 보는 것이다")에 따라, 세 버킷은 언제나 **서로 다른 값**으로 고정한다.
셋을 같은 수로 두면 귀속이 뒤바뀌어도 통과한다 -- D60 이 고친 공허한 불변식이다.
"""

import pytest

import scripts.deep_analysis_reduction_attribution as cli


pytestmark = pytest.mark.no_db


def _summary(prompt: int, answer: int) -> dict:
    """계측된 `node_summary` 페이로드."""
    return {
        "input_tokens": 100,
        "prompt_chars": 500,
        "child_count": 2,
        "own_claims": 1,
        "distinct_claims_prompt": prompt,
        "distinct_claims_answer": answer,
    }


def _degraded(
    *,
    source: str = "children_join",
    own_available: int = 0,
    before: int = 0,
    after: int = 0,
    reason: str = "input_bound",
) -> dict:
    """계측된 `node_reduction_degraded` 페이로드."""
    return {
        "question_id": "q1",
        "child_count": 2,
        "reason": reason,
        "answer_chars": 400,
        "answer_truncated": after < before,
        "answer_source": source,
        "own_claims_available": own_available,
        "distinct_claims_before_bound": before,
        "distinct_claims_after_bound": after,
    }


def _old_degraded() -> dict:
    """CITE1 이전 페이로드. #21·#22 의 실제 키 집합 그대로."""
    return {
        "question_id": "q1",
        "child_count": 2,
        "reason": "input_bound",
        "answer_chars": 400,
        "answer_truncated": False,
    }


def _old_summary() -> dict:
    return {
        "input_tokens": 100,
        "prompt_chars": 500,
        "child_count": 2,
        "own_claims": 1,
    }


def _attribute(summaries: list[dict], degradations: list[dict]) -> cli.Attribution:
    return cli.attribute(
        [cli.parse_summary(p) for p in summaries],
        [cli.parse_degraded(p) for p in degradations],
    )


def test_the_three_buckets_are_counted_apart():
    """셋이 서로 다른 값으로 나온다.

    같은 수로 고정하면 귀속이 뒤바뀌어도 통과한다. D92 의 세 후보는 각각
    다른 수정을 요구하므로, 뒤바뀐 귀속은 틀린 프롬프트를 고치게 만든다.
    """
    attribution = _attribute(
        [_summary(prompt=10, answer=7)],  # LLM 이 3 개를 안 실었다
        [
            _degraded(source="children_join", own_available=5),  # (가) 5
            _degraded(source="children_join", before=9, after=7),  # (나) 2
        ],
    )

    assert attribution.llm_drop == 3
    assert attribution.own_claims_dropped == 5
    assert attribution.truncation_drop == 2
    assert attribution.total_drop == 10


def test_a_children_join_without_own_claims_is_not_a_drop():
    """자기 클레임이 없던 노드는 (가) 로 셀 것이 없다.

    `own_claims_available` 을 안 보고 `answer_source` 만으로 세면 잎이 아닌
    노드 전부가 손실로 잡혀 (가) 가 지배적으로 보인다.
    """
    attribution = _attribute([], [_degraded(source="children_join", own_available=0)])

    assert attribution.own_claims_dropped == 0
    assert attribution.degradations_instrumented == 1


def test_the_own_claims_branch_used_its_claims_so_it_is_not_a_drop():
    """`answer_source == "own_claims"` 는 자기 클레임을 **쓴** 분기다.

    (가) 가 세려는 것은 쓸 수 있었는데 안 쓴 경우이고, 이 분기는 그 반대다.
    """
    attribution = _attribute([], [_degraded(source="own_claims", own_available=4)])

    assert attribution.own_claims_dropped == 0
    assert attribution.sources["own_claims"] == 1


def test_a_marker_the_reduction_invented_is_reported_not_folded_into_a_drop():
    """답이 프롬프트보다 많은 마커를 갖는 것은 손실이 아니라 **환각**이다.

    `max(prompt - answer, 0)` 로만 접으면 그 노드는 손실 0 으로 조용히
    사라진다. ORPHAN2 가 조립 층에서 세고 있는 것과 같은 고장이 리덕션
    층에도 있는지가 이 수로만 보인다.
    """
    attribution = _attribute([_summary(prompt=2, answer=5)], [])

    assert attribution.llm_drop == 0
    assert attribution.invented == 3


def test_events_without_the_cite1_keys_are_refused_rather_than_read_as_zero():
    """옛 페이로드를 0 으로 읽으면 "손실이 어디에도 없다" 고 보고한다.

    #21·#22 가 정확히 그 모양이다(새 키가 하나도 없다). 이것을 0 으로 읽는
    도구는 CITE1 이 아직 안 도는 런에서 **세 후보가 전부 무죄라고 말한다** --
    §3.2 가 이름 붙인 "실패가 성공처럼 보인다" 의 판독기 판본이다.
    """
    attribution = _attribute([_old_summary()], [_old_degraded()])

    assert attribution.instrumented is False
    assert attribution.summaries_instrumented == 0
    assert attribution.degradations_instrumented == 0
    assert attribution.total_drop is None


def test_a_partially_instrumented_run_is_refused_too():
    """계측 경계를 가로지른 런도 판정 대상이 아니다.

    옛 이벤트와 새 이벤트가 섞이면 분자는 새 것만, 분모는 전부를 세게 되어
    손실이 조용히 축소된다. 한 건이라도 미계측이면 그 런을 쓰지 않는다.
    """
    attribution = _attribute(
        [_summary(prompt=10, answer=4)],
        [_degraded(source="children_join", own_available=5), _old_degraded()],
    )

    assert attribution.instrumented is False
    assert attribution.degradations_instrumented == 1
    assert attribution.degradations == 2


def test_the_dominance_rule_needs_pooled_and_median_to_name_the_same_bucket():
    """사전 등록의 판별 규칙: 합산과 런별 중앙값이 같은 버킷을 가리켜야 한다.

    합산만 보면 손실이 큰 한 런이 표본 전체를 대표해 버리고, 중앙값만 보면
    작은 손실의 런이 큰 런과 같은 무게를 갖는다. 둘을 다 요구하는 것이
    #18·#19 가 단일 지표로 튜닝했다가 총 증거를 잃은 데 대한 대가다.
    """
    runs = [
        cli.RunAttribution(prefix="aaaa1111", verified=20, selection_gap=10, attribution=_attribute([_summary(prompt=12, answer=4)], [_degraded(source="children_join", own_available=1), _degraded(before=3, after=2)])),
        cli.RunAttribution(prefix="bbbb2222", verified=18, selection_gap=9, attribution=_attribute([_summary(prompt=11, answer=2)], [_degraded(source="children_join", own_available=1), _degraded(before=2, after=1)])),
        cli.RunAttribution(prefix="cccc3333", verified=19, selection_gap=11, attribution=_attribute([_summary(prompt=10, answer=1)], [_degraded(source="children_join", own_available=2), _degraded(before=3, after=2)])),
    ]

    verdict = cli.verdict(runs)

    assert verdict.dominant == "llm_drop"
    assert verdict.pooled_share["llm_drop"] > cli.DOMINANCE_SHARE


def test_no_single_bucket_dominating_is_itself_a_verdict():
    """셋이 고르게 나뉘면 "지배적인 것이 없다" 가 판정이다.

    억지로 최대값을 고르면 CE2 가 소재지를 잘못 잡는다 -- D40 이 잘못된
    가지를 고쳐 표본 하나를 태운 것과 같은 실패다.
    """
    runs = [
        cli.RunAttribution(prefix="aaaa1111", verified=20, selection_gap=9, attribution=_attribute([_summary(prompt=10, answer=7)], [_degraded(source="children_join", own_available=3), _degraded(before=5, after=2)])),
        cli.RunAttribution(prefix="bbbb2222", verified=18, selection_gap=9, attribution=_attribute([_summary(prompt=9, answer=6)], [_degraded(source="children_join", own_available=3), _degraded(before=6, after=3)])),
    ]

    verdict = cli.verdict(runs)

    assert verdict.dominant is None
    assert verdict.code == "no_single_dominant"


def test_a_reduction_tier_that_loses_almost_nothing_reopens_d91():
    """손실도 격차도 없으면 반증된 것은 후보가 아니라 **층 귀속**이다.

    D91 은 selection 링크(0.56~0.63)를 근거로 손실을 이 층에 귀속했다.
    그 층이 실제로는 거의 안 잃고 잃을 격차도 없다면, 다음 수는 프롬프트를
    고치는 것이 아니라 층을 다시 찾는 것이다.
    """
    runs = [
        cli.RunAttribution(prefix="aaaa1111", verified=20, selection_gap=1, attribution=_attribute([_summary(prompt=10, answer=9)], [])),
        cli.RunAttribution(prefix="bbbb2222", verified=18, selection_gap=2, attribution=_attribute([_summary(prompt=9, answer=8)], [])),
    ]

    verdict = cli.verdict(runs)

    assert verdict.dominant is None
    assert verdict.code == "immaterial_loss"


def test_a_gap_the_three_candidates_cannot_explain_is_a_different_verdict():
    """격차는 큰데 세 버킷이 못 채우면 **넷째 기전**이 있다.

    같은 "총 손실이 작다" 는 관측이지만 다음 수가 정반대다 -- 층 귀속은
    살아 있고 후보 목록이 불완전한 것이다. 둘을 한 코드로 뭉치면 그 구별을
    판정 시점에 사람이 하게 되고, 그것이 사후 합리화다.
    """
    runs = [
        cli.RunAttribution(prefix="aaaa1111", verified=20, selection_gap=9, attribution=_attribute([_summary(prompt=10, answer=9)], [])),
        cli.RunAttribution(prefix="bbbb2222", verified=18, selection_gap=8, attribution=_attribute([_summary(prompt=9, answer=8)], [])),
    ]

    verdict = cli.verdict(runs)

    assert verdict.dominant is None
    assert verdict.code == "unattributed_gap"


def test_an_uninstrumented_run_blocks_the_verdict_entirely():
    """미계측 런이 하나라도 있으면 판정하지 않는다.

    남은 런으로 판정하면 표본 크기가 사전 등록과 달라지고, 그것은 사후에
    표본을 고르는 것이다(§13.5).
    """
    runs = [
        cli.RunAttribution(prefix="aaaa1111", verified=20, selection_gap=9, attribution=_attribute([_summary(prompt=10, answer=2)], [])),
        cli.RunAttribution(prefix="bbbb2222", verified=18, selection_gap=9, attribution=_attribute([_old_summary()], [])),
    ]

    verdict = cli.verdict(runs)

    assert verdict.dominant is None
    assert verdict.code == "not_instrumented"


def test_unattributed_loss_is_surfaced_rather_than_absorbed():
    """세 버킷의 합이 selection 격차를 못 채우면 넷째 새는 곳이 있다.

    D91 은 후보를 셋으로 갈랐지 셋이 전부라고 증명하지 않았다. 잔차를
    안 찍으면 그 사실이 판독기 안에서 사라진다.
    """
    run = cli.RunAttribution(
        prefix="aaaa1111",
        verified=20,
        selection_gap=10,
        attribution=_attribute([_summary(prompt=6, answer=4)], []),
    )

    assert run.attributed == 2
    assert run.unattributed == 8


def test_the_d92_gate_fails_when_the_published_counts_move():
    """#21·#22 의 D92 수치를 재현 못 하면 판정을 내지 않는다.

    D91 스크립트의 `--verify-d90` 과 같은 규율이다. 어긋나면 D92 가 틀린 게
    아니라 **이 도구의 파싱이 틀린 것**으로 읽는다. 정답키는 D92 가 발표한
    **합계**다 -- 표본별 분해는 D92 가 발표하지 않았으므로 정답키가 아니다.
    """
    published = cli.GateCounts(
        summaries=79, degradations=152, input_bound=152, truncated=15
    )
    assert cli.verify_d92(published) == []

    moved = cli.GateCounts(
        summaries=79, degradations=152, input_bound=151, truncated=15
    )
    problems = cli.verify_d92(moved)
    assert len(problems) == 1
    assert "input_bound" in problems[0]


def test_the_gate_is_skipped_loudly_when_the_answer_key_does_not_apply():
    """정답키는 #21+#22 열 런 전체에 대한 수다. 부분집합에는 못 건다.

    조용히 건너뛰면 게이트가 없는 실행과 있는 실행이 출력에서 구별되지
    않는다 -- 이 저장소가 `judge=budget_exhausted` 통과에서 이미 치른 값이다.
    """
    assert cli.gate_applies({"21", "22"}) is True
    assert cli.gate_applies({"21"}) is False
    assert cli.gate_applies({"21", "22", "23"}) is False


# --- D98: 정답키 없는 원장의 게이트 -- 독립 집계 ------------------------------
#
# #21·#22 원장이 로컬에서 사라졌다(로드맵 §12.12). D92 게이트는 그 원장에만
# 걸리므로, #23 은 파서가 센 것을 SQL 이 따로 센 것과 맞춘다.


def test_cross_check_passes_when_parser_and_sql_agree():
    counts = cli.GateCounts(summaries=4, degradations=9, input_bound=9, truncated=1)
    assert cli.cross_check(counts, counts) == []


def test_cross_check_names_the_field_that_moved():
    parsed = cli.GateCounts(summaries=4, degradations=9, input_bound=8, truncated=1)
    sql = cli.GateCounts(summaries=4, degradations=9, input_bound=9, truncated=1)
    problems = cli.cross_check(parsed, sql)
    assert len(problems) == 1 and "input_bound" in problems[0]


def test_an_empty_ledger_is_not_a_pass():
    """파서와 SQL 이 **둘 다 0** 이면 일치한다 -- 그리고 아무것도 증명하지 않는다.

    L4 가 빈 로컬 원장에서 정확히 이 모양으로 "불일치 0" 을 보고할 뻔했다.
    """
    empty = cli.GateCounts(summaries=0, degradations=0, input_bound=0, truncated=0)
    problems = cli.cross_check(empty, empty)
    assert problems and "빈 원장" in problems[0]


def test_budget2_expectation_counts_a_missing_flag_as_a_mismatch():
    """매니페스트에 값이 없는 런은 BUDGET2 이전 코드였는지 알 수 없다."""
    flags = {"aaaa0001": False, "aaaa0002": None, "aaaa0003": True}
    problems = cli.budget2_problems(flags, expected=False)
    assert [p.split(":")[0] for p in problems] == ["aaaa0002", "aaaa0003"]


@pytest.mark.asyncio
async def test_sql_counts_match_the_parser_on_a_real_ledger():
    """두 집계가 같은 원장에서 같은 수를 내는지 -- 실제 Postgres 에서."""
    import json as _json

    from neos.database.connection import get_session_ctx
    from neos.database.deep_analysis_models import DAEvent, DARun
    from tests.workflow.deep_analysis.test_funnel_sample_runner_integration import (
        _delete_fixture_run,
    )

    run_id = "d98xchk1"
    await _delete_fixture_run(run_id)
    summary = {"distinct_claims_prompt": 3, "distinct_claims_answer": 2}
    degraded = {
        "reason": "input_bound",
        "answer_source": "children_join",
        "own_claims_available": 1,
        "distinct_claims_before_bound": 4,
        "distinct_claims_after_bound": 2,
        "answer_truncated": True,
    }
    other = dict(degraded, reason="reduction_allowance_below_claim_floor", answer_truncated=False)
    async with get_session_ctx() as session:
        session.add(DARun(id=run_id, root_question="D98 독립 집계", status="completed"))
        await session.flush()
        session.add_all(
            [
                DAEvent(run_id=run_id, kind="run_manifest", payload=_json.dumps({"config": {"budget_aware_reduction": False}})),
                DAEvent(run_id=run_id, kind="node_summary", payload=_json.dumps(summary)),
                DAEvent(run_id=run_id, kind="node_reduction_degraded", payload=_json.dumps(degraded)),
                DAEvent(run_id=run_id, kind="node_reduction_degraded", payload=_json.dumps(other)),
            ]
        )
        await session.commit()
    try:
        async with get_session_ctx() as session:
            sql = await cli._independent_counts(session, [run_id])
            run = await cli._load_run(session, run_id)
            flags = await cli._budget2_flags(session, [run_id])
        parsed = cli.GateCounts(
            summaries=run.attribution.summaries,
            degradations=run.attribution.degradations,
            input_bound=run.attribution.reasons.get("input_bound", 0),
            truncated=run.attribution.truncated_events,
        )
        assert sql == cli.GateCounts(summaries=1, degradations=2, input_bound=1, truncated=1)
        assert cli.cross_check(parsed, sql) == []
        assert flags == {run_id: False}
    finally:
        await _delete_fixture_run(run_id)
