"""L4 -- Jev-as-Judge 오프라인 백테스트 (로드맵 §12.5).

저장된 원장의 과거 클레임에 Choice 루브릭(`claim_judgement`)을 돌려
`AgenticGrader` 의 판정과 **대조**한다. 산출물은 일치 행렬이다.

    # 무엇이 있는지 본다 -- 네트워크 없음
    .venv/bin/python scripts/jev_judge_backtest.py --sample 21 --sample 22 --dry-run
    .venv/bin/python scripts/jev_judge_backtest.py --all-runs --dry-run

    # 실측 (TYPESAFE_API_KEY 필요)
    .venv/bin/python scripts/jev_judge_backtest.py --sample 21 --limit 90 --repeat 10 \\
        --out-root /Users/ywsung/Desktop/neos/artifacts/jev-judge-backtest

## 정답은 판정자의 판정이 아니다

행렬의 대각선은 "두 판정자가 같은 말을 했다"이지 "Jev 가 맞았다"가 아니다
(§12.1). 클레임 단위 정답키는 저장소에 없다 -- 트랙 F 가 남긴
`scripts/diagnostician_backtest/answer_key.yaml` 은 **표본 단위 병목 라벨**이고
클레임의 지지 여부를 말하지 않는다. 그래서 이 도구는 정확도를 내지 않는다.

## 표본 경계가 아니다

원장을 **읽기만** 한다(§8: D92 재현 게이트와 같은 이유). 세션을 열자마자
`SET TRANSACTION READ ONLY` 를 걸어, 실수로 쓰기 경로가 생겨도 DB 가 거절한다.

## 어떤 클레임을 고르는가 -- 판정자가 본 것을 복원할 수 있는 것만

원장은 "판정자가 그때 무엇을 보았는가"를 직접 적지 않는다. 그래서 복원이
**확실한** 클레임만 고르고, 나머지는 사유별로 센다:

* 판정 이벤트(`claim_verified`/`claim_rejected`/`claim_unverified`)가 **정확히
  하나**다. 둘 이상이면 병합·수리로 문장이나 증거가 바뀌었을 수 있다.
* 그 이벤트에 판정자 라벨이 있다(판정자가 실제로 판정했다).
* 클레임의 현재 상태가 그 이벤트의 결과와 같다. 다르면 판정 뒤에 수리가
  문장을 바꿨다(수리는 이벤트 없이 `pending` 이나 `unverified` 로 되돌린다).
* 판정자가 본 증거 = `agent_grade` 가 그 라벨인 증거 행. 원장은 판정된 증거
  행에만 라벨을 적는다(`Ledger._apply_verdict`).
* 저장된 발췌가 `excerpt_max_chars` 에 닿았으면 **잘렸을 수 있다** -- 판정자는
  잘리기 전 발췌를 보았을 수 있다. 기본으로 빼고(`--include-truncated` 로 넣는다),
  센다.

증거 행에는 순서가 없다(id 는 난수다). 증거가 둘 이상인 클레임은 판정자가 본
**순서**와 다를 수 있고, 행마다 `evidence_order_known=false` 로 적는다.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable, Sequence

sys.path.append(str(Path(__file__).parent.parent))

from sqlalchemy import or_, select, text, true

from neos.database.deep_analysis_models import DAClaim, DAEvent, DAEvidence, DARun
from neos.jev.claim_judge import ClaimJudgement, TypeSafeClaimJudge
from neos.jev.rubric import load_rubric
from scripts.deep_analysis_citation_production import SAMPLES

RUBRIC = "claim_judgement"
QUESTION = "label"
DEFAULT_MODEL = "jev-1.13.0"
#: 실호출 상한. 반복 부분집합을 **포함한다**.
DEFAULT_MAX_CALLS = 200

VERDICT_KINDS: dict[str, str] = {
    "claim_verified": "verified",
    "claim_rejected": "rejected",
    "claim_unverified": "unverified",
}


# ---------------------------------------------------------------------------
# 원장 행 -- DB 에서 온 것을 이 모양으로 옮긴 뒤로는 DB 를 보지 않는다.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LedgerClaim:
    run_id: str
    claim_id: str
    text: str
    status: str


@dataclass(frozen=True)
class LedgerEvidence:
    run_id: str
    claim_id: str
    evidence_id: str
    excerpt: str
    agent_grade: str | None


@dataclass(frozen=True)
class VerdictEvent:
    run_id: str
    seq: int
    kind: str
    claim_id: str
    label: str | None


@dataclass(frozen=True)
class GradedClaim:
    run_id: str
    claim_id: str
    seq: int
    text: str
    judge_label: str
    excerpts: tuple[str, ...]

    @property
    def evidence_order_known(self) -> bool:
        return len(self.excerpts) <= 1


def select_graded_claims(
    claims: Iterable[LedgerClaim],
    evidence: Iterable[LedgerEvidence],
    events: Iterable[VerdictEvent],
    *,
    labels: Sequence[str],
    excerpt_max_chars: int,
    include_possibly_truncated: bool = False,
) -> tuple[list[GradedClaim], Counter]:
    """판정자가 본 입력을 복원할 수 있는 클레임만 고른다. 나머지는 사유별로 센다."""
    label_set = set(labels)
    by_claim_events: dict[tuple[str, str], list[VerdictEvent]] = defaultdict(list)
    for event in events:
        by_claim_events[(event.run_id, event.claim_id)].append(event)
    by_claim_evidence: dict[tuple[str, str], list[LedgerEvidence]] = defaultdict(list)
    for row in evidence:
        by_claim_evidence[(row.run_id, row.claim_id)].append(row)

    selected: list[GradedClaim] = []
    excluded: Counter = Counter()
    for claim in claims:
        key = (claim.run_id, claim.claim_id)
        claim_events = by_claim_events.get(key, [])
        if not claim_events:
            excluded["never_graded"] += 1
            continue
        if len(claim_events) > 1:
            excluded["graded_more_than_once"] += 1
            continue
        (event,) = claim_events
        if event.label not in label_set:
            excluded["no_judge_label"] += 1
            continue
        if claim.status != VERDICT_KINDS[event.kind]:
            excluded["changed_after_grading"] += 1
            continue
        rows = by_claim_evidence.get(key, [])
        graded_rows = [row for row in rows if row.agent_grade == event.label]
        if any(row.agent_grade not in (None, event.label) for row in rows):
            excluded["evidence_label_mismatch"] += 1
            continue
        if not graded_rows:
            excluded["evidence_not_attributable"] += 1
            continue
        if not include_possibly_truncated and any(
            len(row.excerpt) >= excerpt_max_chars for row in graded_rows
        ):
            excluded["excerpt_possibly_truncated"] += 1
            continue
        graded_rows.sort(key=lambda row: row.evidence_id)
        selected.append(
            GradedClaim(
                run_id=claim.run_id,
                claim_id=claim.claim_id,
                seq=event.seq,
                text=claim.text,
                judge_label=event.label,
                excerpts=tuple(row.excerpt for row in graded_rows),
            )
        )
    selected.sort(key=lambda item: (item.run_id, item.seq))
    return selected, excluded


def spread_across_runs(items: Sequence[GradedClaim], limit: int | None) -> list[GradedClaim]:
    """런을 돌아가며 뽑는다. 앞 런 하나가 한도를 다 먹지 않게 한다.

    **판정자 라벨로 층화하지 않는다** -- 비교 대상으로 표본을 고르면 행렬의
    주변분포가 우리가 고른 모양이 된다.
    """
    if limit is None or limit >= len(items):
        return list(items)
    queues: dict[str, list[GradedClaim]] = defaultdict(list)
    for item in items:
        queues[item.run_id].append(item)
    order = sorted(queues)
    picked: list[GradedClaim] = []
    while len(picked) < limit:
        for run_id in order:
            if queues[run_id] and len(picked) < limit:
                picked.append(queues[run_id].pop(0))
    return picked


# ---------------------------------------------------------------------------
# 통계 -- 순수 함수. 손으로 계산한 경우로 테스트한다.
# ---------------------------------------------------------------------------


def agreement_matrix(
    pairs: Sequence[tuple[str, str]], labels: Sequence[str]
) -> dict[str, dict[str, int]]:
    """행 = 판정자(`AgenticGrader`) 라벨, 열 = Jev choice."""
    matrix = {row: {col: 0 for col in labels} for row in labels}
    for judge, jev in pairs:
        matrix[judge][jev] += 1
    return matrix


def cohens_kappa(pairs: Sequence[tuple[str, str]], labels: Sequence[str]) -> float | None:
    """두 평가자의 Cohen's kappa. 기대 일치가 1 이면 정의되지 않는다(None)."""
    n = len(pairs)
    if n == 0:
        return None
    observed = sum(1 for judge, jev in pairs if judge == jev) / n
    judge_counts = Counter(judge for judge, _ in pairs)
    jev_counts = Counter(jev for _, jev in pairs)
    expected = sum((judge_counts[label] / n) * (jev_counts[label] / n) for label in labels)
    if expected >= 1.0:
        return None
    return (observed - expected) / (1.0 - expected)


def confidence_quantile_groups(
    rows: Sequence[tuple[float, bool]], groups: int = 4
) -> list[dict[str, object]]:
    """관측된 confidence 의 **순위 분위** 묶음별 일치율.

    임계값이 아니다. 묶음 경계는 이 표본에서 관측된 값에서 나오고, 다른
    표본에서는 다른 곳에 떨어진다 -- 밴드를 정하는 근거로 쓰지 않는다.
    """
    ordered = sorted(rows, key=lambda row: row[0])
    n = len(ordered)
    groups = max(1, min(groups, n))
    result: list[dict[str, object]] = []
    for index in range(groups):
        chunk = ordered[index * n // groups : (index + 1) * n // groups]
        if not chunk:
            continue
        agree = sum(1 for _, agreed in chunk if agreed)
        result.append(
            {
                "quantile_group": f"Q{index + 1}/{groups}",
                "confidence_min": chunk[0][0],
                "confidence_max": chunk[-1][0],
                "n": len(chunk),
                "agree": agree,
                "agreement": agree / len(chunk),
            }
        )
    return result


def flip_summary(
    first: Sequence[ClaimJudgement], second: Sequence[ClaimJudgement]
) -> dict[str, object]:
    """같은 클레임을 두 번 물었을 때 choice 가 바뀐 비율. 반복가능성 ≠ 정확도."""
    if len(first) != len(second):
        raise ValueError("repeat runs must pair up")
    n = len(first)
    flips = sum(1 for a, b in zip(first, second) if a.choice != b.choice)
    deltas = [
        max(
            abs(a.probabilities.get(label, 0.0) - b.probabilities.get(label, 0.0))
            for label in set(a.probabilities) | set(b.probabilities)
        )
        for a, b in zip(first, second)
    ]
    return {
        "n": n,
        "flips": flips,
        "flip_rate": flips / n if n else None,
        "max_abs_probability_delta": max(deltas) if deltas else None,
        "mean_max_abs_probability_delta": sum(deltas) / n if n else None,
    }


# ---------------------------------------------------------------------------
# 원장 읽기 -- 읽기 전용.
# ---------------------------------------------------------------------------


async def load_ledger(
    session, run_prefixes: Sequence[str] | None
) -> tuple[list[LedgerClaim], list[LedgerEvidence], list[VerdictEvent], dict[str, str]]:
    """원장에서 SELECT 만 한다. 첫 문장이 트랜잭션을 읽기 전용으로 만든다.

    `run_prefixes` 가 None 이면 모든 런을 본다(`--all-runs`).
    """
    await session.execute(text("SET TRANSACTION READ ONLY"))

    def scoped(column):
        if run_prefixes is None:
            return true()
        return or_(*(column.like(f"{prefix}%") for prefix in run_prefixes))

    run_rows = (await session.execute(select(DARun.id, DARun.created_at).where(scoped(DARun.id)))).all()
    run_created = {str(run_id): created.isoformat() if created else "" for run_id, created in run_rows}

    claim_rows = (
        await session.execute(
            select(DAClaim.run_id, DAClaim.id, DAClaim.text, DAClaim.status).where(
                scoped(DAClaim.run_id)
            )
        )
    ).all()
    evidence_rows = (
        await session.execute(
            select(
                DAEvidence.run_id,
                DAEvidence.claim_id,
                DAEvidence.id,
                DAEvidence.excerpt,
                DAEvidence.agent_grade,
            ).where(scoped(DAEvidence.run_id))
        )
    ).all()
    event_rows = (
        await session.execute(
            select(DAEvent.run_id, DAEvent.seq, DAEvent.kind, DAEvent.payload)
            .where(scoped(DAEvent.run_id), DAEvent.kind.in_(tuple(VERDICT_KINDS)))
            .order_by(DAEvent.seq)
        )
    ).all()

    claims = [LedgerClaim(str(r), str(c), t, s) for r, c, t, s in claim_rows]
    evidence = [LedgerEvidence(str(r), str(c), str(i), e, g) for r, c, i, e, g in evidence_rows]
    events: list[VerdictEvent] = []
    for run_id, seq, kind, raw in event_rows:
        payload = raw if isinstance(raw, dict) else json.loads(raw or "{}")
        label = payload.get("label")
        events.append(
            VerdictEvent(
                run_id=str(run_id),
                seq=int(seq),
                kind=str(kind),
                claim_id=str(payload.get("claim_id", "")),
                label=label if isinstance(label, str) else None,
            )
        )
    return claims, evidence, events, run_created


def sample_of(run_id: str) -> str | None:
    for sample, prefixes in SAMPLES.items():
        if any(run_id.startswith(prefix) for prefix in prefixes):
            return sample
    return None


# ---------------------------------------------------------------------------
# 실행
# ---------------------------------------------------------------------------


async def _judge_all(
    judge: TypeSafeClaimJudge, items: Sequence[GradedClaim], concurrency: int
) -> list[ClaimJudgement | Exception]:
    semaphore = asyncio.Semaphore(concurrency)

    async def one(item: GradedClaim) -> ClaimJudgement | Exception:
        async with semaphore:
            try:
                return await judge.judge(item.text, item.excerpts)
            except Exception as error:  # noqa: BLE001 -- 실패는 센다, 삼키지 않는다
                return error

    return await asyncio.gather(*(one(item) for item in items))


def _summarise(
    items: Sequence[GradedClaim],
    results: Sequence[ClaimJudgement | Exception],
    labels: Sequence[str],
) -> tuple[list[dict[str, object]], dict[str, object]]:
    rows: list[dict[str, object]] = []
    pairs: list[tuple[str, str]] = []
    confidence_rows: list[tuple[float, bool]] = []
    failures: Counter = Counter()
    for item, result in zip(items, results):
        row: dict[str, object] = {
            "run_id": item.run_id,
            "sample": sample_of(item.run_id),
            "claim_id": item.claim_id,
            "verdict_seq": item.seq,
            "judge_verdict": item.judge_label,
            "n_excerpts": len(item.excerpts),
            "evidence_order_known": item.evidence_order_known,
        }
        if isinstance(result, Exception):
            failures[type(result).__name__] += 1
            row["jev_error"] = f"{type(result).__name__}: {result}"
        else:
            # `dict.update` 가 아니라 `|=` -- 이 파일에 `.update(` 호출이 하나도
            # 없어야 쓰기 경로 부재를 소스로 고정하는 테스트가 거짓 양성 없이 선다.
            row |= {
                "jev_choice": result.choice,
                "jev_probabilities": result.probabilities,
                "jev_confidence": result.confidence,
                "rubric_digest": result.rubric_digest,
                "resolved_model": result.model,
                "uid": result.uid,
                "agree": result.choice == item.judge_label,
            }
            if result.choice in labels:
                pairs.append((item.judge_label, result.choice))
                confidence_rows.append((result.confidence, result.choice == item.judge_label))
            else:
                failures["choice_outside_label_set"] += 1
        rows.append(row)
    n = len(pairs)
    stats = {
        "n_compared": n,
        "failures": dict(failures),
        "agreement_matrix": {
            "rows": "AgenticGrader verdict (stored ledger)",
            "cols": "Jev choice",
            "labels": list(labels),
            "counts": agreement_matrix(pairs, labels),
        },
        "raw_agreement": (sum(1 for a, b in pairs if a == b) / n) if n else None,
        "cohens_kappa": cohens_kappa(pairs, labels),
        "judge_marginals": dict(Counter(a for a, _ in pairs)),
        "jev_marginals": dict(Counter(b for _, b in pairs)),
        "agreement_by_confidence_quantile_group": confidence_quantile_groups(confidence_rows),
        "confidence_groups_note": (
            "관측된 confidence 의 순위 분위 묶음이다. 임계값이 아니고, 경계는 이 표본에서만 뜻이 있다."
        ),
    }
    return rows, stats


async def run(args: argparse.Namespace) -> None:
    from neos.config.settings import settings
    from neos.database.connection import get_session_ctx

    rubric = load_rubric(RUBRIC)
    labels = tuple(rubric.questions[QUESTION]["criteria"])
    excerpt_max_chars = settings.config.deep_analysis.excerpt_max_chars

    if args.all_runs:
        prefixes = None
    else:
        prefixes = [p for sample in args.sample for p in SAMPLES[sample]] + list(args.run_id)
        if not prefixes:
            raise SystemExit("--sample, --run-id, --all-runs 중 하나가 필요하다")

    async with get_session_ctx() as session:
        claims, evidence, events, run_created = await load_ledger(session, prefixes)

    selected, excluded = select_graded_claims(
        claims,
        evidence,
        events,
        labels=labels,
        excerpt_max_chars=excerpt_max_chars,
        include_possibly_truncated=args.include_truncated,
    )
    chosen = spread_across_runs(selected, args.limit)
    repeat_n = min(args.repeat, len(chosen))
    planned_calls = len(chosen) + repeat_n

    ledger_summary = {
        "requested_prefixes": prefixes,
        "runs_found": len(run_created),
        "claims_in_scope": len(claims),
        "verdict_events": len(events),
        "verdict_events_with_judge_label": sum(1 for e in events if e.label in labels),
        "selected": len(selected),
        "selected_by_run": dict(Counter(item.run_id for item in selected)),
        "selected_judge_labels": dict(Counter(item.judge_label for item in selected)),
        "excluded": dict(excluded),
        "excerpt_max_chars": excerpt_max_chars,
        "chosen": len(chosen),
        "repeat_subset": repeat_n,
        "planned_jev_calls": planned_calls,
        "max_calls": args.max_calls,
    }
    print(json.dumps(ledger_summary, ensure_ascii=False, indent=2))

    if planned_calls > args.max_calls:
        raise SystemExit(f"planned {planned_calls} calls > --max-calls {args.max_calls}")
    if args.dry_run:
        print("\n(dry-run: Jev 를 부르지 않았다)")
        return
    if not chosen:
        raise SystemExit("판정자 라벨이 있는 클레임이 없다 -- 대조할 것이 없다")
    if args.model.endswith("-latest"):
        raise SystemExit("별칭으로 돈 백테스트는 어떤 모델이 답했는지 모른다. 해소된 id 를 핀하라")

    from typesafe_sdk import AsyncTypeSafeClient, constants

    from neos.jev.credentials import resolve_typesafe_key

    os.environ[constants.API_KEY_ENV] = resolve_typesafe_key()
    started = datetime.now(UTC)
    async with AsyncTypeSafeClient() as client:
        judge = TypeSafeClaimJudge(
            client=client,
            model=args.model,
            rubric=rubric,
            question=QUESTION,
            timeout_sec=args.timeout,
        )
        first = await _judge_all(judge, chosen, args.concurrency)
        # 반복 부분집합: 첫 회에 대답한 것 중 앞에서부터. 새 uid 로 다시 묻는다.
        repeat_items = [
            (item, result)
            for item, result in zip(chosen, first)
            if isinstance(result, ClaimJudgement)
        ][:repeat_n]
        second = await _judge_all(judge, [item for item, _ in repeat_items], args.concurrency)
    finished = datetime.now(UTC)

    rows, stats = _summarise(chosen, first, labels)
    paired = [
        (a, b) for (_, a), b in zip(repeat_items, second) if isinstance(b, ClaimJudgement)
    ]
    repeatability = flip_summary([a for a, _ in paired], [b for _, b in paired])
    repeatability["failures"] = sum(1 for b in second if isinstance(b, Exception))
    repeatability["claim_ids"] = [item.claim_id for item, _ in repeat_items]
    repeatability["note"] = "반복가능성은 정확도가 아니다(§12.1)."

    calls_used = len(chosen) + len(repeat_items)
    report = {
        "step": "L4 Jev-as-Judge offline backtest",
        "measured_at_start": started.isoformat(),
        "measured_at_end": finished.isoformat(),
        "requested_model": args.model,
        "resolved_models": sorted(
            {r.model for r in [*first, *second] if isinstance(r, ClaimJudgement)}
        ),
        "rubric": RUBRIC,
        "rubric_digest": rubric.digest,
        "judge_under_comparison": "AgenticGrader (stored ledger verdicts)",
        "answer_key": None,
        "answer_key_note": (
            "클레임 단위 정답키가 저장소에 없다. 일치율은 정확도가 아니다(§12.1)."
        ),
        "jev_calls_used": calls_used,
        "ledger": {**ledger_summary, "run_created_at": run_created},
        "stats": stats,
        "repeatability": repeatability,
        "rows": rows,
        "repeat_rows": [
            {
                "claim_id": item.claim_id,
                "first_choice": a.choice,
                "second_choice": b.choice if isinstance(b, ClaimJudgement) else None,
                "first_probabilities": a.probabilities,
                "second_probabilities": b.probabilities if isinstance(b, ClaimJudgement) else None,
                "second_error": None if isinstance(b, ClaimJudgement) else f"{type(b).__name__}: {b}",
                "rubric_digest": a.rubric_digest,
            }
            for (item, a), b in zip(repeat_items, second)
        ],
    }
    stamp = started.strftime("%Y%m%dT%H%M%SZ")
    destination = Path(args.out_root) / stamp / "report.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("jev_calls_used", "resolved_models", "stats", "repeatability")}, ensure_ascii=False, indent=2))
    print(f"\n-> {destination}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sample", action="append", default=[], choices=sorted(SAMPLES))
    parser.add_argument("--run-id", action="append", default=[], help="런 id 접두사(반복 가능)")
    parser.add_argument("--all-runs", action="store_true", help="원장의 모든 런을 본다")
    parser.add_argument("--limit", type=int, default=None, help="Jev 에 물을 클레임 수 상한")
    parser.add_argument("--repeat", type=int, default=10, help="두 번 물을 부분집합 크기")
    parser.add_argument("--max-calls", type=int, default=DEFAULT_MAX_CALLS)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--include-truncated", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="선택 수와 예정 호출 수만 찍는다. 네트워크 없음")
    parser.add_argument("--out-root", default="artifacts/jev-judge-backtest")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()


__all__ = [
    "GradedClaim",
    "LedgerClaim",
    "LedgerEvidence",
    "VerdictEvent",
    "agreement_matrix",
    "cohens_kappa",
    "confidence_quantile_groups",
    "flip_summary",
    "load_ledger",
    "select_graded_claims",
    "spread_across_runs",
]
