import json

import pytest

from scripts.deep_analysis_diagnostician import build_summary

pytestmark = pytest.mark.no_db


def _row(run_id: str, seq: int, kind: str, payload: dict):
    return (run_id, seq, kind, json.dumps(payload))


def test_summary_counts_events_by_kind():
    rows = [
        _row("r1", 1, "claim_verified", {}),
        _row("r1", 2, "claim_verified", {}),
        _row("r1", 3, "claim_rejected", {}),
    ]
    summary = build_summary(
        rows, run_ids=["r1"], report_bodies={}, config_fingerprint={}
    )
    assert summary["events"]["claim_verified"] == 2
    assert summary["events"]["claim_rejected"] == 1


def test_summary_splits_budget_by_stage():
    rows = [
        _row("r1", 1, "token_budget_reserved",
             {"reservation_id": "a", "reserved_tokens": 100,
              "stage": "worker_analysis"}),
        _row("r1", 2, "token_budget_settled",
             {"reservation_id": "a", "reserved_tokens": 100,
              "actual_tokens": 40}),
    ]
    summary = build_summary(
        rows, run_ids=["r1"], report_bodies={}, config_fingerprint={}
    )
    stage = summary["budget"]["by_stage"]["worker_analysis"]
    assert stage["reserved"] == 100
    assert stage["settled"] == 40
    assert stage["calls"] == 1


def test_summary_counts_zero_token_passes():
    rows = [
        _row("r1", 1, "pass_completed", {"status": "failed", "tokens": 0}),
        _row("r1", 2, "pass_completed", {"status": "completed", "tokens": 900}),
    ]
    summary = build_summary(
        rows, run_ids=["r1"], report_bodies={}, config_fingerprint={}
    )
    assert summary["passes"]["zero_token"] == 1
    assert summary["passes"]["productive"] == 1


def test_summary_reports_delivered_body_median_across_runs():
    """배달 각주/원마커/글자 수는 run당 값의 중앙값이다 -- 이 프로젝트의
    "배달 각주 중앙값" 어휘가 가리키는 계산 (§ 2026-08-18 표본 #16 판정).

    세 run 모두 본문이 있으므로 홀수 개라 중앙값이 모호하지 않다.
    """
    bodies = {
        "r1": "짧다[1]",
        "r2": "본문[1][2] [C:aaa] 남음\n\n## 출처\n[1] x\n[2] y",
        "r3": "본문[1][2][3] 남음\n\n## 출처\n[1] x",
    }
    summary = build_summary(
        [], run_ids=["r1", "r2", "r3"], report_bodies=bodies,
        config_fingerprint={},
    )
    delivered = summary["delivered"]
    assert delivered["runs_total"] == 3
    assert delivered["runs_with_body"] == 3
    assert delivered["runs_missing_body"] == 0
    # footnote counts per run: r1=1, r2=2, r3=3 -> median 2
    assert delivered["footnotes_median"] == 2
    assert delivered["raw_markers_median"] == 0  # only r2 has a raw marker
    assert delivered["sources_section_count"] == 2


def test_summary_counts_runs_with_no_delivered_body_as_a_signal():
    """본문이 없는 run은 빈 문자열로 섞이지 않고 별도로 세어진다 (태스크 3).

    `report_bodies`에 없는 run은 "본문 없음"이지, 각주 0개인 본문이 아니다
    -- 섞으면 `footnotes_median`이 실제 배달 본문의 중앙값이 아니게 된다.
    """
    summary = build_summary(
        [], run_ids=["r1", "r2"], report_bodies={"r1": "본문[1]"},
        config_fingerprint={},
    )
    delivered = summary["delivered"]
    assert delivered["runs_total"] == 2
    assert delivered["runs_with_body"] == 1
    assert delivered["runs_missing_body"] == 1
    assert delivered["footnotes_median"] == 1
    assert delivered["chars_median"] == len("본문[1]")


def test_summary_delivered_is_all_none_and_zero_when_no_body_ever_arrives():
    summary = build_summary(
        [], run_ids=["r1"], report_bodies={}, config_fingerprint={}
    )
    delivered = summary["delivered"]
    assert delivered["runs_with_body"] == 0
    assert delivered["runs_missing_body"] == 1
    assert delivered["footnotes_median"] is None
    assert delivered["raw_markers_median"] is None
    assert delivered["chars_median"] is None
    assert delivered["sources_section_count"] == 0


def test_summary_schema_is_identical_for_empty_and_full_input():
    """최상위 키, `delivered`, `questions`의 세 카운터는 표본이 무엇을 보든
    항상 같은 스키마다 -- `build_summary`가 있을 수 있는 상태를 항상
    명시적으로, 0을 포함해 채우기 때문이다(태스크 1, D79 정정).

    **`questions.resolved_gate`는 예외이며 의도된 예외다.** 그 필드가 원장에
    존재하지 않던 시절에 실행된 표본에서는 `null`이 실린다 -- 네 값을 0으로
    채우면 "아무것도 해소되지 않았다"와 "그때는 재지 않았다"가 같은 모양이
    되고, 계측 정직성을 재는 실험이 그 자리에서 거짓말을 하게 된다(F1-m1).
    그래서 여기서는 두 상태를 각각 고정한다.

    `events`·`gate.codes`·`budget.by_stage`·`stop_reasons`는 다르다 --
    그 표본에서 실제로 일어난 이벤트 kind만 키로 올리는 카운터라서, 표본마다
    키 집합 자체가 달라진다. 그건 결함이 아니라 이 네 블록의 정의다: 빈
    표본은 이 블록들이 전부 비어 있고, 이벤트가 난 표본은 그 kind만큼만
    채워진다. 이 테스트는 그 비대칭을 숨기지 않고 그대로 고정한다.
    """
    empty = build_summary(
        [], run_ids=[], report_bodies={}, config_fingerprint={}
    )
    full = build_summary(
        [
            _row("r1", 1, "claim_verified", {}),
            _row("r1", 2, "token_budget_reserved",
                 {"reservation_id": "a", "reserved_tokens": 10,
                  "stage": "worker_analysis"}),
            _row("r1", 3, "token_budget_settled",
                 {"reservation_id": "a", "actual_tokens": 5}),
            _row("r1", 4, "finalization_prompt_clamped", {"exhausted": True}),
            _row("r1", 5, "report_graded", {"code": "OK", "judge": "present"}),
            _row("r1", 6, "pass_completed",
                 {"status": "completed", "tokens": 5,
                  "resolved_gate": "resolved"}),
            _row("r1", 7, "question_opened", {"depth": 0, "value_est": 1.0}),
            _row("r1", 8, "abandoned", {}),
            _row("r1", 9, "dead_end", {"text": "x"}),
            _row("r1", 10, "token_budget_exhausted", {}),
        ],
        run_ids=["r1"],
        report_bodies={"r1": "x"},
        config_fingerprint={"global_token_cap": 140000},
    )
    assert set(empty) == set(full)
    assert set(empty["delivered"]) == set(full["delivered"])

    # 세 카운터는 항상 완전하다 -- 값만 0이지 키가 빠지지 않는다.
    for block in (empty["questions"], full["questions"]):
        assert {"question_opened", "abandoned", "dead_end"} <= set(block)

    # `resolved_gate`의 두 상태를 각각 고정한다.
    # (a) 그 필드를 실은 `pass_completed`가 하나도 없으면 -> null
    assert empty["questions"]["resolved_gate"] is None
    # (b) 하나라도 있으면 -> 네 값이 전부, 0을 포함해
    assert full["questions"]["resolved_gate"] == {
        "resolved": 1, "failed_status": 0,
        "no_verified_claim": 0, "below_threshold": 0,
    }

    # 동적 카운터 넷은 반대로 실제로 일어난 kind에 따라 키 집합 자체가
    # 달라진다 -- empty는 비어 있고, full은 그 표본이 낸 kind만큼 찬다.
    assert empty["events"] == {}
    assert set(full["events"]) == {
        "claim_verified", "token_budget_reserved", "token_budget_settled",
        "finalization_prompt_clamped", "report_graded", "pass_completed",
        "question_opened", "abandoned", "dead_end",
        "token_budget_exhausted",
    }
    assert empty["gate"]["codes"] == {}
    assert set(full["gate"]["codes"]) == {"OK"}
    assert empty["budget"]["by_stage"] == {}
    assert set(full["budget"]["by_stage"]) == {"worker_analysis"}
    assert empty["stop_reasons"] == {}
    assert set(full["stop_reasons"]) == {"token_budget_exhausted"}


def test_summary_folds_resolved_gate_into_questions():
    """`resolved`는 이벤트 kind가 아니다 -- `Ledger._transition`이 상태만
    바꾸고 로그하지 않는다 (D79 정정). 해소 여부는 `pass_completed`의
    `resolved_gate`가 나른다: `build_summary`가 그것을
    `questions.resolved_gate`로 접어야 커버리지 축이 요약에 실제로 존재한다
    (태스크 1).
    """
    rows = [
        _row("r1", 1, "pass_completed",
             {"status": "completed", "tokens": 5, "resolved_gate": "resolved"}),
        _row("r1", 2, "pass_completed",
             {"status": "completed", "tokens": 5, "resolved_gate": "resolved"}),
        _row("r1", 3, "pass_completed",
             {"status": "completed", "tokens": 5,
              "resolved_gate": "below_threshold"}),
        _row("r1", 4, "pass_completed",
             {"status": "failed", "tokens": 0,
              "resolved_gate": "failed_status"}),
        _row("r1", 5, "pass_completed",
             {"status": "completed", "tokens": 0,
              "resolved_gate": "no_verified_claim"}),
        _row("r1", 6, "question_opened", {"depth": 0, "value_est": 1.0}),
        _row("r1", 7, "abandoned", {}),
    ]
    summary = build_summary(
        rows, run_ids=["r1"], report_bodies={}, config_fingerprint={}
    )
    assert summary["questions"]["resolved_gate"] == {
        "resolved": 2, "below_threshold": 1,
        "failed_status": 1, "no_verified_claim": 1,
    }
    assert summary["questions"]["question_opened"] == 1
    assert summary["questions"]["abandoned"] == 1
    assert summary["questions"]["dead_end"] == 0
    # `resolved`는 `events`에서도 kind로 나타나지 않는다 -- 원장에 그 이름의
    # 이벤트가 없기 때문이다. `pass_completed`만 있다.
    assert "resolved" not in summary["events"]


def test_summary_drops_the_git_commit_sha_from_config():
    """`config.git.commit`은 이 표본의 저장소 SHA다 -- 진단이 오늘 저장소를
    읽지 못해 무해하지만, 읽게 되는 순간 표본을 식별하는 통로가 된다
    (태스크 5). `branch`/`dirty`처럼 특정 실행을 가리키지 않는 필드는 남는다.
    """
    summary = build_summary(
        [], run_ids=[], report_bodies={}, config_fingerprint={
            "global_token_cap": 140000,
            "git": {
                "branch": "dev",
                "commit": "6031fe005400f1721d8a5504757d9643883661d7",
                "dirty": False,
                "dirty_paths": [],
            },
        },
    )
    assert "commit" not in summary["config"]["git"]
    assert summary["config"]["git"]["branch"] == "dev"
    assert summary["config"]["global_token_cap"] == 140000


def test_summary_config_without_a_git_block_is_left_alone():
    summary = build_summary(
        [], run_ids=[], report_bodies={}, config_fingerprint={
            "global_token_cap": 140000,
        },
    )
    assert summary["config"] == {"global_token_cap": 140000}


def test_summary_drops_run_ids_from_the_runs_map():
    """FIX 3: run_id 는 커밋 SHA보다 강한 손잡이다.

    H1 이후 `config_fingerprint.runs`는 `{run_id: manifest}` 맵이다. SHA는
    같은 커밋을 공유하는 여러 표본을 묶을 뿐이지만 run_id는 정확히 이
    표본의 정확히 이 런 하나를 가리킨다. 매니페스트 내용(모델·예산 등)은
    병목 진단에 쓰이므로 남기고, 그것을 누구의 런인지 구별하는 키만 뗀다.
    """
    summary = build_summary(
        [],
        run_ids=[],
        report_bodies={},
        config_fingerprint={
            "manifest_version": 1,
            "git": {"branch": "dev", "commit": "deadbeef", "dirty": False},
            "runs": {
                "run-aaaaaaaa-1111-2222-3333-444455556666": {
                    "profile": "dev",
                    "budget": {"global_token_cap": 140000},
                },
                "run-bbbbbbbb-1111-2222-3333-444455556666": {
                    "profile": "default",
                    "budget": {"global_token_cap": 300000},
                },
            },
        },
    )

    serialized = json.dumps(summary["config"])
    assert "run-aaaaaaaa-1111-2222-3333-444455556666" not in serialized
    assert "run-bbbbbbbb-1111-2222-3333-444455556666" not in serialized
    assert isinstance(summary["config"]["runs"], list)
    assert {"profile": "dev", "budget": {"global_token_cap": 140000}} in (
        summary["config"]["runs"]
    )
    assert {"profile": "default", "budget": {"global_token_cap": 300000}} in (
        summary["config"]["runs"]
    )


def test_the_aggregator_never_branches_on_a_sample_identifier():
    """표본별로 요약을 고르면 정답을 아는 사람이 답을 흘릴 수 있다.

    스펙 §2의 방어를 코드로 고정한다 -- 집계 소스에 표본 id나 아티팩트
    타임스탬프가 등장하면 실패한다.
    """
    import inspect

    from scripts import deep_analysis_diagnostician as mod

    source = inspect.getsource(mod.build_summary)
    for forbidden in ("2026080", "2026081", "#11", "#16", "sample_id"):
        assert forbidden not in source, f"집계가 표본을 안다: {forbidden}"


def test_resolved_gate_is_null_when_the_sample_predates_the_field():
    """0 과 "그때는 재지 않았다" 는 다른 사실이다.

    `resolved_gate` 는 9a2431d6(2026-08-18)이 추가했고 표본 #11~#16 은
    2026-08-09~11 에 실행됐다. 그 페이로드에는 필드가 아예 없다. 네 값을
    전부 0 으로 실으면 진단자는 "아무것도 해소되지 않았다" 로 읽는데,
    사실은 확인할 수 없는 것이다 -- 계측 정직성을 재는 실험이 바로 그
    자리에서 거짓말을 하게 된다 (F1-m1).
    """
    rows = [
        _row("r1", 1, "pass_completed", {"status": "partial", "tokens": 900}),
        _row("r1", 2, "question_opened", {}),
    ]
    summary = build_summary(
        rows, run_ids=["r1"], report_bodies={}, config_fingerprint={}
    )
    assert summary["questions"]["resolved_gate"] is None
    # 실제로 기록된 축은 그대로 실린다 -- null 은 이 필드 하나에 대한 것이지
    # 커버리지 전체가 없다는 뜻이 아니다.
    assert summary["questions"]["question_opened"] == 1


def test_resolved_gate_carries_explicit_zeros_once_the_field_exists():
    """반대로 계측된 표본에서는 일어나지 않은 상태도 키가 빠지지 않는다."""
    rows = [
        _row("r1", 1, "pass_completed",
             {"status": "completed", "tokens": 900, "resolved_gate": "resolved"}),
    ]
    summary = build_summary(
        rows, run_ids=["r1"], report_bodies={}, config_fingerprint={}
    )
    gate = summary["questions"]["resolved_gate"]
    assert gate["resolved"] == 1
    assert gate["no_verified_claim"] == 0
    assert set(gate) == {
        "resolved", "failed_status", "no_verified_claim", "below_threshold",
    }
