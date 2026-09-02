"""리덕션 층의 인용 손실을 D92 의 세 후보에 귀속한다 (CITE1 판독기).

**라이브 표본을 쓰지 않는다** -- 원장에 이미 있는 것만 읽는다. LLM 호출도 없다.
`deep_analysis_citation_production.py`(D91)가 손실을 `reduce_node` 로 좁힌 뒤,
D92 가 그 안에서 후보를 셋으로 갈랐다. 이 도구는 그 셋을 센다.

    verified ──selection──▶ 조립 프롬프트   (D91 이 0.56~0.63 으로 잰 링크)
                  ↑
                  이 층이 잃는 것을 셋으로 나눈다:

* ``llm_drop``           : LLM 이 **보여준 마커 중 산문에 안 실은 수**
                           Σ `node_summary`: prompt − answer
* ``own_claims_dropped`` : (가) 자기 클레임 침묵 폐기 -- 자식 답이 있으면
                           이 노드의 verified 클레임은 join 에 안 들어간다
                           Σ `node_reduction_degraded` where
                           `answer_source == "children_join"`: `own_claims_available`
* ``truncation_drop``    : (나) `_bound_degraded_answer` 의 반절 자르기
                           Σ `before_bound − after_bound`

셋은 마커 단위로 서로소다. 한 노드에서 잃은 마커는 그 위 노드의 프롬프트에
애초에 들어오지 않으므로 두 번 세어지지 않는다. 그래서 합이 의미를 갖는다.

## 계측되지 않은 런은 0 이 아니라 거부다

#21·#22 의 페이로드에는 이 키가 하나도 없다. 없는 키를 0 으로 읽으면 이 도구는
**세 후보가 전부 무죄라고 보고한다** -- §3.2 가 이름 붙인 "실패가 성공처럼
보인다" 의 판독기 판본이다. 그래서 미계측 이벤트가 하나라도 있는 런은 판정에
넣지 않고, 넣지 않았다는 것을 출력이 말한다.

## `--verify-d92`

기본으로 켜져 있다. #21·#22 를 **함께** 지정했을 때, D92 가 발표한 합계
(`node_summary` 79 · `node_reduction_degraded` 152 · 사유 `input_bound` 152 ·
`answer_truncated` 15)를 재현하지 못하면 **판정을 내지 않고 실패한다.**
어긋나면 D92 가 틀린 게 아니라 이 도구의 파싱이 틀린 것으로 읽는다.

    .venv/bin/python scripts/deep_analysis_reduction_attribution.py --sample 21 --sample 22
    .venv/bin/python scripts/deep_analysis_reduction_attribution.py --run <prefix8> ...

## 판별 규칙 (사전 등록 D93)

`DOMINANCE_SHARE`·`DOMINANCE_MARGIN`·`MIN_MEDIAN_TOTAL_DROP` 이 그 규칙이고,
표본을 보기 전에 고정된 수다. 표본을 본 뒤 이 셋을 움직이는 것은 §13.5 가
금지한 "판정자가 자기 사전 등록을 수정하는 경로" 다.

판정 코드 다섯 -- **"지배적인 것이 없다" 도 판정이다**:

* ``not_instrumented``  : 미계측 런이 하나라도 있다. 판정하지 않는다
* ``unattributed_gap``  : 격차는 큰데 세 버킷이 못 채운다 -- 넷째 기전이 있고
                          D91 의 층 귀속은 살아 있다
* ``immaterial_loss``   : 손실도 격차도 작다 -- 반증되는 것은 후보가 아니라
                          **층 귀속**이다
* ``no_single_dominant``: 셋이 고르다. 억지로 하나를 고르면 CE2 가 소재지를
                          잘못 잡는다 (D40 의 반복)
* ``dominant``          : 합산과 런별 중앙값이 같은 버킷을 가리켰다
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from dataclasses import dataclass, field
import json
from pathlib import Path
import statistics
import sys

sys.path.append(str(Path(__file__).parent.parent))

from sqlalchemy import func, select

from neos.database.connection import get_session_ctx
from neos.database.deep_analysis_models import DAClaim, DAEvent

# --------------------------------------------------------------------------
# 사전 등록된 상수 (D93). 표본을 본 뒤에 움직이지 말 것.
# --------------------------------------------------------------------------

#: 지배적이라 부르려면 합산 몫이 이 값 이상이어야 한다.
DOMINANCE_SHARE = 0.50

#: 그리고 2위 버킷의 몫보다 이 배수 이상이어야 한다. 0.50 하나만 걸면
#: 0.51 대 0.49 도 "지배적" 이 되고, 그 둘은 사실상 같은 관측이다.
DOMINANCE_MARGIN = 2.0

#: 런별 총 손실의 중앙값이 이보다 작으면 이 층에서 가를 것이 없다 --
#: 반증되는 것은 후보가 아니라 D91 의 층 귀속이다.
MIN_MEDIAN_TOTAL_DROP = 3

BUCKETS = ("llm_drop", "own_claims_dropped", "truncation_drop")

#: 표본별 런 접두사 8자. 정본은 DECISIONS.md D86(#21)·D89(#22) 와 §8.1 이다.
SAMPLES: dict[str, tuple[str, ...]] = {
    "21": ("e1e461e9", "3abaf523", "643ddd46", "ca288b93", "de15f297"),
    "22": ("e0c1a998", "950c948a", "c44ee6ee", "7b899de3", "6252da9e"),
}

#: 재현 게이트가 성립하는 표본 집합. D92 가 발표한 것은 이 열 런의 **합계**
#: 이므로 부분집합에는 걸 수 없다.
GATE_SAMPLES = frozenset({"21", "22"})

SUMMARY_KEYS = ("distinct_claims_prompt", "distinct_claims_answer")
DEGRADED_KEYS = (
    "answer_source",
    "own_claims_available",
    "distinct_claims_before_bound",
    "distinct_claims_after_bound",
)


@dataclass(frozen=True)
class GateCounts:
    """재현 게이트가 세는 넷. 전부 CITE1 **이전** 키로 셀 수 있다."""

    summaries: int
    degradations: int
    input_bound: int
    truncated: int


#: D92 가 발표한 합계. 기대값이 아니라 정답키다.
D92_PUBLISHED = GateCounts(
    summaries=79, degradations=152, input_bound=152, truncated=15
)


@dataclass(frozen=True)
class Summary:
    """`node_summary` 한 건 -- LLM 이 실제로 요약을 쓴 리덕션."""

    prompt: int
    answer: int
    instrumented: bool

    @property
    def dropped(self) -> int:
        return max(self.prompt - self.answer, 0)

    @property
    def invented(self) -> int:
        """답이 프롬프트보다 많이 가진 마커. 손실이 아니라 환각이다."""
        return max(self.answer - self.prompt, 0)


@dataclass(frozen=True)
class Degraded:
    """`node_reduction_degraded` 한 건 -- LLM 이 돌지 못한 리덕션."""

    reason: str
    source: str | None
    own_available: int
    before: int
    after: int
    #: CITE1 **이전** 키다. 재현 게이트가 옛 표본에서 성립하는 이유의 하나.
    truncated: bool
    instrumented: bool

    @property
    def own_dropped(self) -> int:
        """쓸 수 있었는데 안 쓴 자기 클레임. `own_claims` 분기는 쓴 것이다."""
        if self.source != "children_join":
            return 0
        return self.own_available

    @property
    def truncated_away(self) -> int:
        return max(self.before - self.after, 0)


@dataclass(frozen=True)
class Attribution:
    summaries: int
    summaries_instrumented: int
    degradations: int
    degradations_instrumented: int
    llm_drop: int
    own_claims_dropped: int
    truncation_drop: int
    invented: int
    #: `answer_truncated` 가 참인 건수. 계측 여부와 무관하게 셀 수 있으므로
    #: `truncation_drop`(새 키가 필요하다)과 달리 옛 표본에서도 나온다.
    truncated_events: int = 0
    reasons: Counter = field(default_factory=Counter)
    sources: Counter = field(default_factory=Counter)

    @property
    def instrumented(self) -> bool:
        """이벤트가 **하나도 빠짐없이** 새 키를 가졌는가.

        부분 계측을 통과시키면 분자는 새 이벤트만, 분모는 전부를 세게 되어
        손실이 조용히 축소된다.
        """
        return (
            self.summaries_instrumented == self.summaries
            and self.degradations_instrumented == self.degradations
        )

    @property
    def total_drop(self) -> int | None:
        if not self.instrumented:
            return None
        return self.llm_drop + self.own_claims_dropped + self.truncation_drop

    def bucket(self, name: str) -> int:
        return getattr(self, name)


@dataclass(frozen=True)
class RunAttribution:
    prefix: str
    verified: int
    selection_gap: int | None
    attribution: Attribution

    @property
    def attributed(self) -> int | None:
        return self.attribution.total_drop

    @property
    def unattributed(self) -> int | None:
        """selection 격차 중 세 버킷이 설명하지 못한 몫.

        D91 은 후보를 셋으로 갈랐지 셋이 전부라고 증명하지 않았다. 잔차를
        안 찍으면 넷째 새는 곳이 판독기 안에서 사라진다.
        """
        if self.selection_gap is None or self.attributed is None:
            return None
        return self.selection_gap - self.attributed


@dataclass(frozen=True)
class Verdict:
    code: str
    dominant: str | None
    pooled_share: dict[str, float]
    median_share: dict[str, float]
    median_total_drop: float | None
    note: str


def parse_summary(payload: dict) -> Summary:
    instrumented = all(key in payload for key in SUMMARY_KEYS)
    return Summary(
        prompt=int(payload.get("distinct_claims_prompt") or 0),
        answer=int(payload.get("distinct_claims_answer") or 0),
        instrumented=instrumented,
    )


def parse_degraded(payload: dict) -> Degraded:
    instrumented = all(key in payload for key in DEGRADED_KEYS)
    return Degraded(
        reason=str(payload.get("reason") or ""),
        source=payload.get("answer_source"),
        own_available=int(payload.get("own_claims_available") or 0),
        before=int(payload.get("distinct_claims_before_bound") or 0),
        after=int(payload.get("distinct_claims_after_bound") or 0),
        truncated=bool(payload.get("answer_truncated")),
        instrumented=instrumented,
    )


def attribute(
    summaries: list[Summary], degradations: list[Degraded]
) -> Attribution:
    reasons: Counter = Counter()
    sources: Counter = Counter()
    for degraded in degradations:
        reasons[degraded.reason] += 1
        if degraded.source is not None:
            sources[degraded.source] += 1
    return Attribution(
        summaries=len(summaries),
        summaries_instrumented=sum(1 for s in summaries if s.instrumented),
        degradations=len(degradations),
        degradations_instrumented=sum(
            1 for d in degradations if d.instrumented
        ),
        llm_drop=sum(s.dropped for s in summaries if s.instrumented),
        own_claims_dropped=sum(
            d.own_dropped for d in degradations if d.instrumented
        ),
        truncation_drop=sum(
            d.truncated_away for d in degradations if d.instrumented
        ),
        invented=sum(s.invented for s in summaries if s.instrumented),
        truncated_events=sum(1 for d in degradations if d.truncated),
        reasons=reasons,
        sources=sources,
    )


def verdict(runs: list[RunAttribution]) -> Verdict:
    """사전 등록된 규칙 그대로. 순서가 규칙의 일부다.

    미계측 → 손실 미미 → 지배 판정. 앞의 둘을 뒤로 미루면 판정할 수 없는
    표본에서도 버킷 이름이 나오고, 그 이름은 근거 없이 CE2 의 소재지를 정한다.
    """
    empty = dict.fromkeys(BUCKETS, 0.0)

    if not runs:
        return Verdict("no_runs", None, empty, empty, None, "런이 없다")

    uninstrumented = [r.prefix for r in runs if r.attributed is None]
    if uninstrumented:
        return Verdict(
            "not_instrumented",
            None,
            empty,
            empty,
            None,
            "미계측 런: " + ", ".join(uninstrumented) + " -- 판정하지 않는다",
        )

    totals = [float(r.attributed) for r in runs]
    median_total = statistics.median(totals)

    pooled_sum = {
        name: sum(r.attribution.bucket(name) for r in runs) for name in BUCKETS
    }
    grand = sum(pooled_sum.values())
    pooled_share = (
        {name: pooled_sum[name] / grand for name in BUCKETS} if grand else empty
    )

    per_run_shares: dict[str, list[float]] = {name: [] for name in BUCKETS}
    for run in runs:
        total = run.attributed or 0
        if not total:
            continue
        for name in BUCKETS:
            per_run_shares[name].append(run.attribution.bucket(name) / total)
    median_share = {
        name: (statistics.median(values) if values else 0.0)
        for name, values in per_run_shares.items()
    }

    if median_total < MIN_MEDIAN_TOTAL_DROP:
        # 손실이 작다는 같은 관측이 두 가지 정반대의 다음 수를 뜻한다.
        # 격차가 남아 있으면 이 층에서 **다른 기전**으로 새는 것이고(넷째
        # 후보), 격차도 없으면 애초에 이 층이 무대가 아니다(D91 재검토).
        # 판정 시점에 사람이 가르면 그것이 사후 합리화이므로 여기서 가른다.
        gaps = [r.selection_gap for r in runs if r.selection_gap is not None]
        median_gap = statistics.median(gaps) if gaps else None
        if median_gap is not None and median_gap >= MIN_MEDIAN_TOTAL_DROP:
            return Verdict(
                "unattributed_gap",
                None,
                pooled_share,
                median_share,
                median_total,
                f"총 손실 중앙값 {median_total:g} 인데 selection 격차 중앙값은 "
                f"{median_gap:g} -- 세 후보가 격차를 설명하지 못한다. "
                "층 귀속은 살아 있고 넷째 기전이 있다",
            )
        return Verdict(
            "immaterial_loss",
            None,
            pooled_share,
            median_share,
            median_total,
            f"런별 총 손실 중앙값 {median_total:g} < {MIN_MEDIAN_TOTAL_DROP} "
            f"이고 selection 격차도 "
            f"{'없다' if median_gap is None else f'{median_gap:g} 로 작다'} -- "
            "반증되는 것은 후보가 아니라 D91 의 층 귀속이다",
        )

    ranked = sorted(BUCKETS, key=lambda name: pooled_share[name], reverse=True)
    top, second = ranked[0], ranked[1]
    median_top = max(BUCKETS, key=lambda name: median_share[name])

    if pooled_share[top] < DOMINANCE_SHARE:
        return Verdict(
            "no_single_dominant",
            None,
            pooled_share,
            median_share,
            median_total,
            f"최대 몫 {top} {pooled_share[top]:.2f} < {DOMINANCE_SHARE}",
        )
    if pooled_share[second] and (
        pooled_share[top] < DOMINANCE_MARGIN * pooled_share[second]
    ):
        return Verdict(
            "no_single_dominant",
            None,
            pooled_share,
            median_share,
            median_total,
            f"{top} 이 2위 {second} 의 {DOMINANCE_MARGIN:g}배에 못 미친다",
        )
    if median_top != top:
        return Verdict(
            "no_single_dominant",
            None,
            pooled_share,
            median_share,
            median_total,
            f"합산은 {top}, 런별 중앙값은 {median_top} -- 둘이 어긋난다",
        )

    return Verdict(
        "dominant",
        top,
        pooled_share,
        median_share,
        median_total,
        f"{top} 합산 {pooled_share[top]:.2f} · 중앙값 {median_share[top]:.2f}",
    )


def gate_applies(samples: set[str]) -> bool:
    """정답키가 이 실행에 걸리는가. #21·#22 **정확히** 그 둘일 때만이다."""
    return set(samples) == set(GATE_SAMPLES)


def verify_d92(counts: GateCounts) -> list[str]:
    problems: list[str] = []
    for field_name in ("summaries", "degradations", "input_bound", "truncated"):
        want = getattr(D92_PUBLISHED, field_name)
        got = getattr(counts, field_name)
        if want != got:
            problems.append(
                f"{field_name}: D92 는 {want} 인데 이 도구는 {got}"
            )
    return problems


async def _load_run(session, prefix: str) -> RunAttribution:
    verified = await session.scalar(
        select(func.count())
        .select_from(DAClaim)
        .where(DAClaim.run_id.like(f"{prefix}%"), DAClaim.status == "verified")
    )

    summaries: list[Summary] = []
    degradations: list[Degraded] = []
    rows = (
        await session.execute(
            select(DAEvent.kind, DAEvent.payload)
            .where(
                DAEvent.run_id.like(f"{prefix}%"),
                DAEvent.kind.in_(("node_summary", "node_reduction_degraded")),
            )
            .order_by(DAEvent.seq)
        )
    ).all()
    for kind, raw in rows:
        payload = raw if isinstance(raw, dict) else json.loads(raw)
        if kind == "node_summary":
            summaries.append(parse_summary(payload))
        else:
            degradations.append(parse_degraded(payload))

    return RunAttribution(
        prefix=prefix,
        verified=int(verified or 0),
        selection_gap=await _selection_gap(session, prefix, int(verified or 0)),
        attribution=attribute(summaries, degradations),
    )


async def _selection_gap(session, prefix: str, verified: int) -> int | None:
    """D91 의 selection 링크가 잃은 수 -- `verified − 조립 프롬프트(절삭 전)`.

    시도가 여럿일 때 **최대**를 쓴다. 어느 시도가 배달됐는지는 원장이 직접
    말하지 않고(D91 이 그것을 `match` 열로 다뤘다), 잔차를 과대평가하지 않는
    쪽이 최대다: 프롬프트가 가장 많이 실린 시도조차 놓친 클레임만 센다.
    """
    rows = (
        await session.execute(
            select(DAEvent.payload).where(
                DAEvent.run_id.like(f"{prefix}%"),
                DAEvent.kind == "finalization_prompt_clamped",
            )
        )
    ).all()
    befores = []
    for (raw,) in rows:
        payload = raw if isinstance(raw, dict) else json.loads(raw)
        if payload.get("stage") == "report_assembly":
            befores.append(int(payload.get("distinct_claims_before") or 0))
    if not befores or not verified:
        return None
    return verified - max(befores)


def _fmt(value: float | None) -> str:
    return "—" if value is None else f"{value:.2f}"


def _report(sample: str, runs: list[RunAttribution]) -> None:
    print(f"\n### 표본 #{sample}\n")
    print(
        "| run | verified | 계측 | llm_drop | own_claims | truncation | "
        "합 | selection 격차 | 미귀속 | invented |"
    )
    print("|---|---:|---|---:|---:|---:|---:|---:|---:|---:|")
    for run in runs:
        a = run.attribution
        mark = (
            "✅"
            if a.instrumented
            else f"❌ {a.summaries_instrumented}/{a.summaries}"
            f"·{a.degradations_instrumented}/{a.degradations}"
        )
        print(
            f"| `{run.prefix}` | {run.verified} | {mark} | "
            f"{a.llm_drop} | {a.own_claims_dropped} | {a.truncation_drop} | "
            f"{'—' if a.total_drop is None else a.total_drop} | "
            f"{'—' if run.selection_gap is None else run.selection_gap} | "
            f"{'—' if run.unattributed is None else run.unattributed} | "
            f"{a.invented} |"
        )


def _print_verdict(result: Verdict) -> None:
    print("\n### 판정 (사전 등록 D93)\n")
    print(f"- 코드: **{result.code}**")
    print(f"- 지배적 후보: **{result.dominant or '없음'}**")
    print(
        "- 합산 몫: "
        + " · ".join(f"{k} {_fmt(v)}" for k, v in result.pooled_share.items())
    )
    print(
        "- 런별 중앙값 몫: "
        + " · ".join(f"{k} {_fmt(v)}" for k, v in result.median_share.items())
    )
    print(f"- 런별 총 손실 중앙값: {_fmt(result.median_total_drop)}")
    print(f"- 근거: {result.note}")


async def _run(samples: list[str], extra_runs: list[str], verify: bool) -> int:
    by_sample: dict[str, list[RunAttribution]] = {}
    async with get_session_ctx() as session:
        for sample in samples:
            by_sample[sample] = [
                await _load_run(session, prefix) for prefix in SAMPLES[sample]
            ]
        if extra_runs:
            by_sample["(직접 지정)"] = [
                await _load_run(session, prefix) for prefix in extra_runs
            ]

    all_runs = [run for runs in by_sample.values() for run in runs]

    if verify and gate_applies(set(samples)) and not extra_runs:
        counts = GateCounts(
            summaries=sum(r.attribution.summaries for r in all_runs),
            degradations=sum(r.attribution.degradations for r in all_runs),
            input_bound=sum(
                r.attribution.reasons.get("input_bound", 0) for r in all_runs
            ),
            truncated=_truncated_count(all_runs),
        )
        problems = verify_d92(counts)
        if problems:
            print("🔴 D92 재현 실패 — 판정을 내지 않는다:")
            for problem in problems:
                print(f"  - {problem}")
            return 1
        print("✅ D92 재현 확인 (79 · 152 · 152 · 15)")
    elif verify:
        print(
            "⚠️ D92 재현 게이트를 걸지 않았다 — 정답키는 #21·#22 열 런의 "
            "합계이고 이 실행은 그 집합이 아니다"
        )

    for sample, runs in by_sample.items():
        _report(sample, runs)

    _print_verdict(verdict(all_runs))
    return 0


def _truncated_count(runs: list[RunAttribution]) -> int:
    """`answer_truncated` 는 CITE1 이전 키라 계측 여부와 무관하게 셀 수 있다.

    게이트가 옛 표본에서 성립하는 이유가 이것이다 -- 넷 다 새 키를 안 쓴다.
    """
    return sum(r.attribution.truncated_events for r in runs)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sample",
        action="append",
        choices=sorted(SAMPLES),
        help="표본 번호. 반복 지정 가능. 생략하면 전부.",
    )
    parser.add_argument(
        "--run",
        action="append",
        default=[],
        help="런 접두사 8자. 표본 원장에 없는 새 표본을 읽을 때 쓴다.",
    )
    parser.add_argument(
        "--no-verify-d92",
        action="store_true",
        help="D92 재현 게이트를 끈다. SAMPLES 를 확장할 때만 쓸 것.",
    )
    args = parser.parse_args()
    samples = args.sample or (sorted(SAMPLES) if not args.run else [])
    return asyncio.run(
        _run(samples, args.run, verify=not args.no_verify_d92)
    )


if __name__ == "__main__":
    raise SystemExit(main())
