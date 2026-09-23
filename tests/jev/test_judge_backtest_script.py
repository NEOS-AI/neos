"""L4 백테스트 판독기 -- 선택 · 통계 · 읽기 전용.

DB 도 네트워크도 쓰지 않는다. 원장 행을 손으로 짓는다.
"""

from __future__ import annotations

import ast
import math
from pathlib import Path

import pytest
from sqlalchemy.sql import Select

import scripts.jev_judge_backtest as cli
from neos.jev.claim_judge import ClaimJudgement

pytestmark = pytest.mark.no_db

LABELS = ("SUPPORTS", "PARTIAL", "UNRELATED", "CONTRADICTS")


def claim(cid: str, status: str, run: str = "r1", text: str | None = None) -> cli.LedgerClaim:
    return cli.LedgerClaim(run, cid, text or f"claim {cid}", status)


def ev(cid: str, eid: str, excerpt: str, grade: str | None, run: str = "r1") -> cli.LedgerEvidence:
    return cli.LedgerEvidence(run, cid, eid, excerpt, grade)


def event(cid: str, kind: str, label: str | None, seq: int, run: str = "r1") -> cli.VerdictEvent:
    return cli.VerdictEvent(run, seq, kind, cid, label)


def test_selection_keeps_only_claims_whose_judge_input_is_recoverable() -> None:
    claims = [
        claim("ok1", "verified"),
        claim("ok2", "rejected"),
        claim("never", "pending"),
        claim("twice", "verified"),
        claim("nolabel", "rejected"),
        claim("repaired", "pending"),
        claim("noev", "verified"),
        claim("long", "verified"),
        claim("mixed", "verified"),
    ]
    evidence = [
        ev("ok1", "b", "second", "SUPPORTS"),
        ev("ok1", "a", "first", "SUPPORTS"),
        ev("ok2", "c", "x", "PARTIAL"),
        ev("ok2", "d", "never judged", None),  # 앞 패스에서 결정론 단계에 막힌 행
        ev("twice", "e", "x", "SUPPORTS"),
        ev("nolabel", "f", "x", None),
        ev("repaired", "g", "x", "PARTIAL"),
        ev("noev", "h", "x", None),
        ev("long", "i", "y" * 10, "SUPPORTS"),
        ev("mixed", "j", "x", "SUPPORTS"),
        ev("mixed", "k", "x", "PARTIAL"),
    ]
    events = [
        event("ok1", "claim_verified", "SUPPORTS", 5),
        event("ok2", "claim_rejected", "PARTIAL", 3),
        event("twice", "claim_rejected", "PARTIAL", 1),
        event("twice", "claim_verified", "SUPPORTS", 9),
        event("nolabel", "claim_rejected", None, 2),
        event("repaired", "claim_rejected", "PARTIAL", 4),
        event("noev", "claim_verified", "SUPPORTS", 6),
        event("long", "claim_verified", "SUPPORTS", 7),
        event("mixed", "claim_verified", "SUPPORTS", 8),
    ]
    selected, excluded = cli.select_graded_claims(
        claims, evidence, events, labels=LABELS, excerpt_max_chars=10
    )
    assert [(s.claim_id, s.judge_label, s.excerpts) for s in selected] == [
        ("ok2", "PARTIAL", ("x",)),
        ("ok1", "SUPPORTS", ("first", "second")),
    ]
    assert selected[1].evidence_order_known is False
    assert dict(excluded) == {
        "never_graded": 1,
        "graded_more_than_once": 1,
        "no_judge_label": 1,
        "changed_after_grading": 1,
        "evidence_not_attributable": 1,
        "excerpt_possibly_truncated": 1,
        "evidence_label_mismatch": 1,
    }

    with_long, _ = cli.select_graded_claims(
        claims,
        evidence,
        events,
        labels=LABELS,
        excerpt_max_chars=10,
        include_possibly_truncated=True,
    )
    assert "long" in {s.claim_id for s in with_long}


def test_spread_takes_runs_in_turn_not_the_first_run_whole() -> None:
    items = [
        cli.GradedClaim(run, f"{run}{i}", i, "t", "SUPPORTS", ("e",))
        for run in ("a", "b")
        for i in range(3)
    ]
    picked = cli.spread_across_runs(items, 3)
    assert [p.claim_id for p in picked] == ["a0", "b0", "a1"]
    assert cli.spread_across_runs(items, None) == items


def test_matrix_and_kappa_match_a_hand_computed_case() -> None:
    # 판정자 SUPPORTS 6, PARTIAL 4. Jev 는 SUPPORTS 5 번 맞히고 1 번 PARTIAL,
    # PARTIAL 은 2 번 맞히고 2 번 SUPPORTS.
    pairs = (
        [("SUPPORTS", "SUPPORTS")] * 5
        + [("SUPPORTS", "PARTIAL")]
        + [("PARTIAL", "PARTIAL")] * 2
        + [("PARTIAL", "SUPPORTS")] * 2
    )
    matrix = cli.agreement_matrix(pairs, LABELS)
    assert matrix["SUPPORTS"] == {"SUPPORTS": 5, "PARTIAL": 1, "UNRELATED": 0, "CONTRADICTS": 0}
    assert matrix["PARTIAL"] == {"SUPPORTS": 2, "PARTIAL": 2, "UNRELATED": 0, "CONTRADICTS": 0}
    assert matrix["UNRELATED"] == dict.fromkeys(LABELS, 0)
    # po = 7/10. 판정자 주변 (.6,.4), Jev 주변 (.7,.3) -> pe = .42 + .12 = .54.
    # kappa = (.70 - .54) / (1 - .54) = .16 / .46
    assert math.isclose(cli.cohens_kappa(pairs, LABELS), 0.16 / 0.46)


def test_kappa_is_undefined_when_both_raters_use_one_label() -> None:
    assert cli.cohens_kappa([("SUPPORTS", "SUPPORTS")] * 3, LABELS) is None
    assert cli.cohens_kappa([], LABELS) is None


def test_confidence_groups_are_rank_quantiles_of_what_was_observed() -> None:
    rows = [(0.9, True), (0.3, False), (0.5, True), (0.7, False)]
    groups = cli.confidence_quantile_groups(rows, groups=2)
    assert [(g["confidence_min"], g["confidence_max"], g["n"], g["agree"]) for g in groups] == [
        (0.3, 0.5, 2, 1),
        (0.7, 0.9, 2, 1),
    ]
    assert len(cli.confidence_quantile_groups(rows[:1], groups=4)) == 1


def _answer(choice: str, supports: float) -> ClaimJudgement:
    return ClaimJudgement(
        choice=choice,
        probabilities={"SUPPORTS": supports, "PARTIAL": 1 - supports},
        confidence=max(supports, 1 - supports),
        model="jev-1.13.0",
        rubric_digest="d",
        uid="u",
    )


def test_flip_rate_counts_changed_choices() -> None:
    first = [_answer("SUPPORTS", 0.6), _answer("PARTIAL", 0.2)]
    second = [_answer("PARTIAL", 0.4), _answer("PARTIAL", 0.25)]
    summary = cli.flip_summary(first, second)
    assert summary["flips"] == 1
    assert summary["flip_rate"] == 0.5
    assert math.isclose(summary["max_abs_probability_delta"], 0.2)


class ReadOnlySession:
    """`execute` 만 가진 세션. add/flush/commit 을 부르면 AttributeError 로 죽는다."""

    def __init__(self) -> None:
        self.statements: list[object] = []

    async def execute(self, statement):
        self.statements.append(statement)

        class Result:
            def all(self):
                return []

        return Result()


async def test_the_loader_only_selects_and_opens_a_read_only_transaction() -> None:
    session = ReadOnlySession()
    await cli.load_ledger(session, ["e1e461e9"])
    first, *rest = session.statements
    assert str(first) == "SET TRANSACTION READ ONLY"
    assert rest and all(isinstance(statement, Select) for statement in rest)


def test_the_script_has_no_write_path() -> None:
    """원장에 쓰는 경로가 소스에 없다. 런타임 가드(READ ONLY)와 별개로 소스를 본다."""
    tree = ast.parse(Path(cli.__file__).read_text(encoding="utf-8"))
    forbidden_calls = {"add", "add_all", "flush", "commit", "merge", "delete", "insert", "update"}
    called = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert not (called & forbidden_calls), called & forbidden_calls
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "sqlalchemy"
        for alias in node.names
    }
    assert not imported & {"insert", "update", "delete"}
    assert "Ledger" not in {
        alias.name for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) for alias in node.names
    }


def test_the_call_cap_is_the_stated_200() -> None:
    assert cli.DEFAULT_MAX_CALLS == 200
    args = cli.build_parser().parse_args(["--sample", "21", "--dry-run"])
    assert args.max_calls == 200 and args.model == "jev-1.13.0"
