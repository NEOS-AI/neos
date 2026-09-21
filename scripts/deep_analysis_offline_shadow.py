"""기록된 run 위에서 조사 워커를 돌리고 제안을 맞대 본다 (로드맵 J3).

    python scripts/deep_analysis_offline_shadow.py \
        --run-id run00001 --question-id q_1 \
        --cassette artifacts/shadow.json --mode replay

## 이 섀도가 답하는 질문

**"그때 그 워커를 다시 돌리면?" 이 아니다.** brief 는 `verified_summaries` 와
`unverified_and_deadends` 로 조립되고 그 둘은 **지금** 원장이 말하는 것을
읽는다 -- 끝난 run 에서는 그때 워커가 본 것보다 더 많은 확정 발견이 들어간다.
그 패스의 brief 를 되짚는 방법은 없다(원장에 저장되지 않는다).

답하는 질문은 **"이 run 이 쌓은 지식을 주면 조사 워커는 무엇을
제안하는가?"** 다. 보고서가 그렇게 말한다.

## 원장에 쓰지 않는다

워커에게 가는 것은 `ShadowLedger` 이고 fetch 는 `BlobArchive` 다. 채점기만
**진짜 원장**을 받는데, 읽기만 하기 때문이고(`get_blob`·`get_claim`·
`claim_source_urls`) 보관소가 원장 blob 의 부분집합이라 워커가 인용할 수 있는
모든 blob 은 이미 거기 있다.

⚠️ 서브에이전트 런타임은 `PostgresSubagentStore` 에 자기 실행 기록을 쓴다.
DA 원장은 그대로지만 섀도 실행이 흔적을 아주 안 남기는 것은 아니다.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from neos.coding.sandbox.base import SandboxLimits
from neos.coding.sandbox.factory import create_sandbox_provider
from neos.config.settings import settings
from neos.database.connection import db_manager, get_session_ctx
from neos.workflow.deep_analysis.assignment import build_assignment
from neos.workflow.deep_analysis.cassette import Cassette
from neos.workflow.deep_analysis.cassette_model import CassetteModel
from neos.workflow.deep_analysis.graders.deterministic import DeterministicGrader
from neos.workflow.deep_analysis.ledger import Ledger
from neos.workflow.deep_analysis.models import Effort
from neos.workflow.deep_analysis.shadow import (
    build_shadow_worker,
    run_offline_shadow,
)
from neos.workflow.deep_analysis.subagent_adapter import build_research_runtime


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--run-id", required=True, help="섀도로 돌릴 기록된 run")
    parser.add_argument("--question-id", required=True)
    parser.add_argument("--cassette", required=True, type=Path)
    parser.add_argument(
        "--mode",
        default="replay",
        choices=["replay", "record"],
        help="replay 는 LLM 에 닿지 않는다. record 는 **진짜 호출을 하고 돈을 쓴다**",
    )
    parser.add_argument(
        "--effort",
        default="dig",
        choices=[effort.value for effort in Effort if effort != Effort.SPLIT],
    )
    parser.add_argument("--out", type=Path, help="보고서를 JSON 으로도 쓴다")
    return parser.parse_args(argv)


def _live_model():
    """녹음 모드에서만 만든다 -- 재생 경로가 프로바이더를 만들면 안 된다."""
    from neos.utils.llm_factory import create_coding_model
    from neos.workflow.deep_analysis.harness_bridge import da_provider_for_model
    from neos.workflow.deep_analysis.model_roles import resolve_harness_model

    resolved = resolve_harness_model("dig")
    return create_coding_model(provider=da_provider_for_model(resolved.model))


async def _run(args) -> dict:
    config = settings.config.deep_analysis
    if args.mode == "replay" and not args.cassette.exists():
        # 가장 흔한 운영 실수다. 스택트레이스 대신 다음에 할 일을 말한다.
        raise SystemExit(
            f"{args.cassette} 가 없다 -- 재생할 카세트가 있어야 한다. "
            "먼저 `--mode record` 로 한 번 돌려 녹음할 것 "
            "(그때는 진짜 LLM 호출이 나가고 돈이 든다)."
        )
    cassette = Cassette(args.cassette, mode=args.mode)
    model = CassetteModel(
        cassette, inner=_live_model() if args.mode == "record" else None
    )
    provider = create_sandbox_provider(settings.config.sandbox)

    async with get_session_ctx() as session:
        ledger = Ledger(session, args.run_id)
        question = await ledger.get_question(args.question_id)
        if question is None:
            raise SystemExit(
                f"{args.question_id} 는 run {args.run_id} 에 없다"
            )
        assignment = await build_assignment(
            ledger, question, Effort(args.effort)
        )
        worker = build_shadow_worker(
            provider=provider,
            # 채점기는 원장을 **읽기만** 한다. 계산 클레임은 research 명세가
            # 만들지 않으므로 재실행기는 없다.
            grader=DeterministicGrader(
                ledger,
                quote_threshold=config.quote_match_threshold,
                confidence_cap=config.confidence_cap,
            ),
            runtime_factory=lambda port: build_research_runtime(
                port, session_factory=db_manager.get_session, model=model
            ),
            cap_bytes=config.code_research.evidence_bytes_cap,
            limits=SandboxLimits.safe_defaults(),
            parent_id=args.run_id,
        )
        comparison = await run_offline_shadow(ledger, assignment, worker=worker)

    if args.mode == "record":
        cassette.save()

    return {
        "run_id": args.run_id,
        "question_id": args.question_id,
        "effort": args.effort,
        "question": question.text,
        # 보고서가 스스로 무엇인지 말한다 -- 읽는 쪽이 "그때 그 실행" 으로
        # 읽지 않게.
        "asks": (
            "이 run 이 쌓은 지식을 주면 조사 워커는 무엇을 제안하는가 "
            "(그 패스의 brief 를 되짚은 것이 아니다)"
        ),
        "evidence_was_complete": comparison.evidence_was_complete,
        "shared": list(comparison.shared),
        "only_recorded": [
            {"text": claim.text, "status": claim.status}
            for claim in comparison.only_recorded
        ],
        "only_shadow": list(comparison.only_shadow),
        "served_urls": list(comparison.served_urls),
        "missed_urls": list(comparison.missed_urls),
    }


def _print(report: dict) -> None:
    print(f"run {report['run_id']} / 질문 {report['question_id']}")
    print(f"  묻는 것: {report['asks']}")
    print(f"  양쪽 다: {len(report['shared'])}")
    print(f"  기록된 run 에만: {len(report['only_recorded'])}")
    print(f"  섀도에만: {len(report['only_shadow'])}")
    if report["evidence_was_complete"]:
        print("  증거는 완전했다 -- 차이는 판단 차이다")
    else:
        print(
            f"  ⚠️ 보관소가 못 준 URL {len(report['missed_urls'])}개 -- "
            "섀도는 프로덕션보다 적은 증거로 돌았다. 제안이 빈약한 것을 "
            "워커 탓으로 읽지 말 것"
        )


def main(argv=None) -> int:
    args = _parse_args(argv)
    report = asyncio.run(_run(args))
    _print(report)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
