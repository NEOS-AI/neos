"""인용 생산 비율(D90)을 네 링크로 쪼개 어느 링크가 새는지 가른다.

**라이브 표본을 쓰지 않는다** -- 원장에 이미 있는 것만 읽는다. LLM 호출도 없다.
D90 이 "그 백테스트가 먼저다" 로 남긴 것이 이것이다.

D90 은 `배달 본문이 인용한 고유 클레임 / 그 run 의 verified 클레임` 하나만 쟀다.
그 비율이 낮다는 것은 알겠는데 **어디서 새는지**를 말하지 못한다. 이 도구는 같은
분자·분모 사이에 원장이 이미 갖고 있는 두 지점을 끼워 넣는다:

    verified  ──selection──▶  prompt_before  ──clamp──▶  prompt_after  ──writer──▶  cited

* ``verified``       : `deep_analysis_claims.status = 'verified'`
* ``prompt_before``  : `finalization_prompt_clamped{stage=report_assembly}` 의
                       `distinct_claims_before` -- 절삭 **전** 조립 프롬프트에 실린 수
* ``prompt_after``   : 같은 이벤트의 `distinct_claims_after` -- 절삭 **후**
* ``cited``          : 배달 본문의 `## 출처` 각주 수 + 남은 고유 `[C:...]` 마커 수
                       (orphan 도 "인용하려 한 것" 이므로 분자에 든다 -- D90 정의)

세 비율 중 **1 에서 가장 멀리 떨어진 것이 병목**이다. 셋을 곱하면 D90 의
`인용 생산 비율`이 되므로, 이 도구는 D90 을 대체하지 않고 분해한다.

## `--verify-d90`

기본으로 켜져 있다. #21·#22 의 열 런에 대해 D90 이 발표한 `cited/verified` 를
그대로 재현하지 못하면 **판정을 내지 않고 실패한다.** 파싱이 D90 과 어긋난 채
새 결론을 내면 그 결론이 D90 과 비교 불가해지기 때문이다 -- §8.1.2 의
"계측을 먼저 의심한다" 를 도구 안에 넣은 것이다.

## 시도가 여럿인 런

조립은 재시도한다(`claim_retry_cap`). 어느 시도가 배달됐는지는 원장이 직접
말하지 않으므로 **가정하지 않는다**: 시도별 수를 전부 찍고, `cited` 와 일치하는
시도를 `match` 열에 표시한다. 일치가 없으면 `-` 다.

    .venv/bin/python scripts/deep_analysis_citation_production.py --sample 21 --sample 22
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from sqlalchemy import func, select

from neos.database.connection import get_session_ctx
from neos.database.deep_analysis_models import (
    DAClaim,
    DAEvent,
    DAQuestion,
)
from neos.utils.citations import SOURCE_HEADING_KO

# 배달 본문에서 세는 두 가지. `_FOOTNOTE` 는 `## 출처` 절 **안에서만** 센다 --
# 본문의 `[1]` 은 같은 각주를 여러 번 가리킬 수 있고, 출처 절의 줄 수가
# `CitationRenderer` 가 실제로 해소한 고유 클레임 수와 1:1 이다
# (`numbered_source_lines` 가 1 부터 조밀하게 매긴다).
_FOOTNOTE = re.compile(r"(?m)^\[(\d+)\]\s")
_ORPHAN_MARKER = re.compile(r"\[C:([0-9a-f]{8})\]")

# 표본별 런 접두사 8자. 정본은 DECISIONS.md D86(#21)·D89(#22) 와 §8.1 표본 원장이다.
SAMPLES: dict[str, tuple[str, ...]] = {
    "21": ("e1e461e9", "3abaf523", "643ddd46", "ca288b93", "de15f297"),
    "22": ("e0c1a998", "950c948a", "c44ee6ee", "7b899de3", "6252da9e"),
}

# D90 이 발표한 `cited/verified`. 재현 게이트의 정답키이지 기대값이 아니다 --
# 어긋나면 D90 이 틀린 게 아니라 **이 도구의 파싱이 틀린 것**으로 읽는다.
D90_PUBLISHED: dict[str, tuple[int, int]] = {
    "e1e461e9": (18, 6),
    "3abaf523": (19, 9),
    "643ddd46": (17, 11),
    "ca288b93": (21, 9),
    "de15f297": (16, 6),
    "e0c1a998": (15, 4),
    "950c948a": (19, 14),
    "c44ee6ee": (18, 5),
    "7b899de3": (15, 6),
    "6252da9e": (7, 1),
}


@dataclass(frozen=True)
class Attempt:
    seq: int
    before: int
    after: int


@dataclass(frozen=True)
class Reduction:
    """`node_reduction` 절삭 한 건. 절삭이 **실제로 잘랐을 때만** 기록된다.

    기록되지 않았다는 것은 "안 잘렸다" 는 뜻이므로(`_log_clamp` 의 조기 반환),
    로그에 없는 리덕션은 클레임을 잃을 수 없다. 절삭의 무죄를 이 표본에서
    판정할 수 있는 이유가 그것이다 -- 침묵이 곧 무손실이다.
    """

    qid: str
    is_root: bool
    before: int
    after: int

    @property
    def cut_claims(self) -> bool:
        return self.after < self.before


@dataclass(frozen=True)
class RunChain:
    prefix: str
    verified: int
    attempts: tuple[Attempt, ...]
    cited: int
    body_found: bool
    root_own_verified: int
    reductions: tuple[Reduction, ...]

    @property
    def root_reduction(self) -> Reduction | None:
        for reduction in reversed(self.reductions):
            if reduction.is_root:
                return reduction
        return None

    @property
    def delivered(self) -> Attempt | None:
        """`cited` 와 `after` 가 일치하는 시도. 없으면 None.

        마지막 시도로 가정하지 않는다 -- 실측에서 마지막이 아닌 시도와
        일치하는 런이 있고, 그것 자체가 기록할 사실이다.
        """
        for attempt in self.attempts:
            if attempt.after == self.cited:
                return attempt
        return None

    def ratio(self, numerator: int | None, denominator: int | None) -> float | None:
        if not denominator or numerator is None:
            return None
        return numerator / denominator


async def _load_run(session, prefix: str) -> RunChain:
    verified = await session.scalar(
        select(func.count())
        .select_from(DAClaim)
        .where(DAClaim.run_id.like(f"{prefix}%"), DAClaim.status == "verified")
    )

    root_qid = await session.scalar(
        select(DAQuestion.id).where(
            DAQuestion.run_id.like(f"{prefix}%"),
            DAQuestion.parent_id.is_(None),
        )
    )
    root_own_verified = await session.scalar(
        select(func.count())
        .select_from(DAClaim)
        .where(
            DAClaim.run_id.like(f"{prefix}%"),
            DAClaim.status == "verified",
            DAClaim.question_id == root_qid,
        )
    )

    clamp_rows = (
        await session.execute(
            select(DAEvent.seq, DAEvent.qid, DAEvent.payload)
            .where(
                DAEvent.run_id.like(f"{prefix}%"),
                DAEvent.kind == "finalization_prompt_clamped",
            )
            .order_by(DAEvent.seq)
        )
    ).all()

    attempts: list[Attempt] = []
    reductions: list[Reduction] = []
    for seq, qid, raw in clamp_rows:
        payload = raw if isinstance(raw, dict) else json.loads(raw)
        before = int(payload.get("distinct_claims_before") or 0)
        after = int(payload.get("distinct_claims_after") or 0)
        stage = payload.get("stage")
        if stage == "report_assembly":
            attempts.append(Attempt(seq=int(seq), before=before, after=after))
        elif stage == "node_reduction":
            reductions.append(
                Reduction(
                    qid=str(qid),
                    is_root=qid == root_qid,
                    before=before,
                    after=after,
                )
            )

    body_rows = (
        await session.execute(
            select(DAEvent.payload)
            .where(
                DAEvent.run_id.like(f"{prefix}%"),
                DAEvent.kind == "job_completed",
            )
            .order_by(DAEvent.seq)
        )
    ).all()

    body: str | None = None
    for (raw,) in body_rows:
        payload = raw if isinstance(raw, dict) else json.loads(raw)
        candidate = payload.get("report_markdown")
        if isinstance(candidate, str):
            body = candidate

    return RunChain(
        prefix=prefix,
        verified=int(verified or 0),
        attempts=tuple(attempts),
        cited=_count_cited(body),
        body_found=body is not None,
        root_own_verified=int(root_own_verified or 0),
        reductions=tuple(reductions),
    )


def _count_cited(body: str | None) -> int:
    """해소된 각주 + 남은 고유 orphan 마커. D90 의 분자 정의 그대로."""
    if not body:
        return 0
    heading_at = body.find(SOURCE_HEADING_KO)
    section = body[heading_at:] if heading_at >= 0 else ""
    footnotes = len(set(_FOOTNOTE.findall(section)))
    orphans = len(set(_ORPHAN_MARKER.findall(body)))
    return footnotes + orphans


def _verify_d90(chains: list[RunChain]) -> list[str]:
    problems: list[str] = []
    for chain in chains:
        expected = D90_PUBLISHED.get(chain.prefix)
        if expected is None:
            continue
        want_verified, want_cited = expected
        if chain.verified != want_verified or chain.cited != want_cited:
            problems.append(
                f"{chain.prefix}: D90 은 verified={want_verified} cited={want_cited} "
                f"인데 이 도구는 verified={chain.verified} cited={chain.cited}"
            )
    return problems


def _fmt(value: float | None) -> str:
    return "—" if value is None else f"{value:.2f}"


def _median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def _report(sample: str, chains: list[RunChain]) -> None:
    print(f"\n### 표본 #{sample}\n")
    print(
        "| run | verified | prompt_before | prompt_after | cited | "
        "selection | clamp | writer | production | match |"
    )
    print("|---|---:|---:|---:|---:|---:|---:|---:|---:|---|")

    columns: dict[str, list[float]] = {
        "selection": [],
        "clamp": [],
        "writer": [],
        "production": [],
    }

    for chain in chains:
        delivered = chain.delivered
        before = delivered.before if delivered else None
        after = delivered.after if delivered else None
        if delivered is None and chain.attempts:
            # 일치하는 시도가 없으면 마지막 시도를 *표시만* 한다. 비율은 내지 않는다.
            before = chain.attempts[-1].before
            after = chain.attempts[-1].after

        selection = chain.ratio(before, chain.verified)
        clamp = chain.ratio(after, before)
        writer = chain.ratio(chain.cited, after)
        production = chain.ratio(chain.cited, chain.verified)

        if delivered is not None:
            for name, value in (
                ("selection", selection),
                ("clamp", clamp),
                ("writer", writer),
            ):
                if value is not None:
                    columns[name].append(value)
        if production is not None:
            columns["production"].append(production)

        attempts_note = (
            f"시도 {len(chain.attempts)}, {'일치' if delivered else '불일치'}"
        )
        print(
            f"| `{chain.prefix}` | {chain.verified} | "
            f"{before if before is not None else '—'} | "
            f"{after if after is not None else '—'} | {chain.cited} | "
            f"{_fmt(selection)} | {_fmt(clamp)} | {_fmt(writer)} | "
            f"{_fmt(production)} | {attempts_note} |"
        )

    medians = {name: _median(values) for name, values in columns.items()}
    print(
        f"| **중앙값** | | | | | **{_fmt(medians['selection'])}** | "
        f"**{_fmt(medians['clamp'])}** | **{_fmt(medians['writer'])}** | "
        f"**{_fmt(medians['production'])}** | |"
    )


def _localize(chains: list[RunChain]) -> None:
    """selection 링크가 새는 자리를 좁힌다 -- 절삭인가, 리덕션 LLM 인가.

    두 가지를 함께 찍는다.

    1. **절삭의 무죄.** 비루트 `node_reduction` 절삭 중 클레임을 실제로 자른
       건수. 기록되지 않은 리덕션은 자르지 않은 것이므로, 이 수가 작으면
       verified → 조립 프롬프트 손실을 절삭으로 설명할 수 없다.
    2. **루트 리덕션 항등식.** 루트 질문은 자기 클레임을 갖지 않으므로
       (`root_own_verified`), 루트 리덕션의 `distinct_claims_before` 는 곧
       **자식들의 `NodeSummary.answer` 가 실어 올린 마커 수**다. 그것이
       조립 프롬프트의 `prompt_before` 와 같다면 두 소비자가 같은 것을 받은
       것이고, 손실은 그 위 -- `reduce_node` 의 LLM 출력 -- 에 있다.
    """
    print("\n### selection 링크는 어디서 새는가\n")
    print(
        "| run | 총 verified | 루트 자체 verified | 루트 리덕션 before | "
        "조립 prompt_before | 자식 답변이 실어 올린 비율 |"
    )
    print("|---|---:|---:|---:|---:|---:|")

    carried: list[float] = []
    for chain in chains:
        root = chain.root_reduction
        delivered = chain.delivered or (
            chain.attempts[-1] if chain.attempts else None
        )
        prompt_before = delivered.before if delivered else None
        subtree_verified = chain.verified - chain.root_own_verified
        ratio = (
            (root.before - chain.root_own_verified) / subtree_verified
            if root is not None and subtree_verified
            else None
        )
        if ratio is not None:
            carried.append(ratio)
        print(
            f"| `{chain.prefix}` | {chain.verified} | {chain.root_own_verified} | "
            f"{root.before if root else '—'} | "
            f"{prompt_before if prompt_before is not None else '—'} | "
            f"{_fmt(ratio)} |"
        )
    print(f"| **중앙값** | | | | | **{_fmt(_median(carried))}** |")

    non_root = [r for chain in chains for r in chain.reductions if not r.is_root]
    cut = [r for r in non_root if r.cut_claims]
    print(
        f"\n**절삭의 무죄:** 비루트 `node_reduction` 절삭 {len(non_root)}건 중 "
        f"클레임을 실제로 자른 것은 **{len(cut)}건**이다"
        + (
            f" ({', '.join(f'{r.before}→{r.after}' for r in cut)})."
            if cut
            else "."
        )
        + " 기록되지 않은 리덕션은 자르지 않은 것이므로(`_log_clamp` 조기 반환),"
        " 절삭은 위 손실을 설명하지 못한다."
    )

    identical = sum(
        1
        for chain in chains
        if chain.root_reduction is not None
        and chain.attempts
        and chain.root_reduction.before
        == (chain.delivered or chain.attempts[-1]).before
    )
    print(
        f"**루트 리덕션 항등식:** {identical}/{len(chains)} 런에서 "
        "루트 리덕션의 `before` 와 조립의 `prompt_before` 가 같다 -- "
        "두 소비자가 같은 클레임 집합을 받는다."
    )


async def _run(samples: list[str], verify: bool) -> int:
    all_chains: list[RunChain] = []
    per_sample: dict[str, list[RunChain]] = {}

    async with get_session_ctx() as session:
        for sample in samples:
            prefixes = SAMPLES[sample]
            chains = [await _load_run(session, prefix) for prefix in prefixes]
            per_sample[sample] = chains
            all_chains.extend(chains)

    missing = [c.prefix for c in all_chains if not c.body_found]
    if missing:
        print(f"⚠️ 배달 본문 없음: {', '.join(missing)}", file=sys.stderr)

    if verify:
        problems = _verify_d90(all_chains)
        if problems:
            print(
                "🔴 D90 재현 실패 -- 판정을 내지 않는다. 이 도구의 파싱을 먼저 의심할 것:",
                file=sys.stderr,
            )
            for problem in problems:
                print(f"  - {problem}", file=sys.stderr)
            return 1
        print("✅ D90 재현 확인 -- `cited/verified` 가 발표된 값과 전부 일치한다.")

    for sample in samples:
        _report(sample, per_sample[sample])
    _localize(all_chains)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sample",
        action="append",
        choices=sorted(SAMPLES),
        help="표본 번호. 반복 지정 가능. 생략하면 전부.",
    )
    parser.add_argument(
        "--no-verify-d90",
        action="store_true",
        help="D90 재현 게이트를 끈다. SAMPLES 를 확장할 때만 쓸 것.",
    )
    args = parser.parse_args()
    samples = args.sample or sorted(SAMPLES)
    return asyncio.run(_run(samples, verify=not args.no_verify_d90))


if __name__ == "__main__":
    raise SystemExit(main())
