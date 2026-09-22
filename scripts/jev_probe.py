"""Jev 프로바이더 사실 확인과 일관성 기준선 (로드맵 L0 · L1).

    export TYPESAFE_API_KEY=...            # 또는 .env 에 적는다
    python -m scripts.jev_probe models                       # L0
    python -m scripts.jev_probe consistency --model <해소된 id> --runs 15   # L1

## 이 스크립트가 답하는 것

**L0 -- 무엇이 실제로 있는가.** `models.list()` 가 돌려주는 이름·설명·출시일을
그대로 찍는다. `jev-latest` 가 **무엇으로 해소되는지**는 별칭을 직접 한 번
불러 응답의 `model` 필드를 읽어서 확인한다 -- 목록에 적힌 이름이 아니라
서버가 답한 값이 핀의 근거다.

**L1 -- NEOS 자신의 루브릭에서 얼마나 흔들리는가.** 쿡북의 `0.0102` 를
그대로 들여오지 않는다(§14 "계측을 먼저 의심한다"). 고정 루브릭 · 고정 대상 ·
**신선한 uid** 로 N 회 물어 질문별 표준편차를 낸다.

## 적지 않는 것

**가격은 이 스크립트가 알아낼 수 없다.** `ListModelsResponse` 는 이름·설명·
출시일만 준다 -- 가격 필드가 없다. 그러므로 카탈로그 등재는 이 스크립트의
출력만으로 끝나지 않고, 가격은 TypeSafe 계정의 청구 정보에서 사람이 가져와야
한다. 모르는 값을 그럴듯하게 적는 것이 가장 나쁜 선택이다.

출력은 아티팩트로 남긴다 -- 측정 날짜 없는 수치는 로드맵에 옮겨 적지 않는다.
"""

import argparse
import asyncio
import json
import os
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path

from typesafe_sdk import AsyncTypeSafeClient, constants

from neos.jev.credentials import resolve_typesafe_key
from neos.jev.rubric import load_rubric

#: 기본 대상. **극단에 붙어 있다** -- 2026-09-22 실측 0.93~0.94.
#:
#: 그래서 이 대상의 표준편차는 기준선으로 쓰면 안 된다. 확률은 0 과 1 근처에서
#: 자연히 압축되므로, 게이트가 실제로 흔들리는 자리(중간대)의 변동을 과소평가
#: 한다. 밴드를 정할 근거가 필요하면 `--subject` 로 중간대 대상을 지정해 재라.
_CONSISTENCY_SUBJECT = {
    "tool": "execute.v1",
    "input": {"argv": ["git", "push", "--force", "origin", "main"]},
}


def _artifact_dir() -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = Path("artifacts") / "jev-probe" / stamp
    path.mkdir(parents=True, exist_ok=True)
    return path


def _require_key() -> str:
    """키를 찾아 프로세스 환경에 올린다.

    SDK 클라이언트는 생성자 인자나 환경변수에서 키를 읽는다. `.env` 는 보지
    않으므로, 저장소 규칙대로 찾은 값을 여기서 한 번 올려 준다.
    """
    key = resolve_typesafe_key()
    os.environ[constants.API_KEY_ENV] = key
    return key


async def probe_models(args: argparse.Namespace) -> None:
    """L0. 목록과, 별칭이 무엇으로 해소되는지."""
    _require_key()
    rubric = load_rubric(args.rubric)
    report: dict[str, object] = {
        "measured_at": datetime.now(UTC).isoformat(),
        "rubric": args.rubric,
        "rubric_digest": rubric.digest,
    }

    async with AsyncTypeSafeClient() as client:
        listing = await client.models.list()
        report["models"] = [
            {
                "name": model.name,
                "description": model.description,
                "release_date": model.release_date,
            }
            for model in listing.models
        ]

        # 별칭이 무엇으로 해소되는가. 목록이 아니라 **응답**이 근거다.
        resolutions: dict[str, object] = {}
        for candidate in (constants.DEFAULT_MODEL, *args.also):
            started = time.perf_counter()
            try:
                response = await client.system_one(
                    {**_CONSISTENCY_SUBJECT, "uid": f"{rubric.digest}:probe"},
                    rubric.questions,
                    model=candidate,
                )
            except Exception as error:  # noqa: BLE001 -- 실패도 사실이다
                resolutions[candidate] = {"error": f"{type(error).__name__}: {error}"}
                continue
            resolutions[candidate] = {
                "resolved_model": response.model,
                "latency_sec": round(time.perf_counter() - started, 3),
                "usage": response.usage.model_dump(),
                "answers": {
                    name: answer.model_dump() for name, answer in response.answers.items()
                },
            }
        report["resolutions"] = resolutions

    report["pricing"] = (
        "미상 -- ListModelsResponse 에 가격 필드가 없다. 카탈로그 등재 전에 "
        "TypeSafe 계정의 청구 정보에서 사람이 가져와야 한다."
    )
    _write(report, args)


async def probe_consistency(args: argparse.Namespace) -> None:
    """L1. 같은 루브릭 · 같은 대상 · 신선한 uid 로 N 회."""
    _require_key()
    rubric = load_rubric(args.rubric)
    subject = json.loads(args.subject) if args.subject else _CONSISTENCY_SUBJECT
    observations: list[dict[str, object]] = []

    async with AsyncTypeSafeClient() as client:
        for index in range(args.runs):
            started = time.perf_counter()
            response = await client.system_one(
                {**subject, "uid": f"{rubric.digest}:{index}:{os.urandom(4).hex()}"},
                rubric.questions,
                model=args.model,
            )
            observations.append(
                {
                    "resolved_model": response.model,
                    "latency_sec": round(time.perf_counter() - started, 3),
                    "nouls": {name: answer.noul for name, answer in response.nouls.items()},
                }
            )

    per_question: dict[str, object] = {}
    question_names = {name for row in observations for name in row["nouls"]}
    for name in sorted(question_names):
        values = [row["nouls"][name] for row in observations if name in row["nouls"]]
        per_question[name] = {
            "n": len(values),
            "mean": statistics.fmean(values),
            "stdev": statistics.stdev(values) if len(values) > 1 else 0.0,
            "min": min(values),
            "max": max(values),
        }

    _write(
        {
            "measured_at": datetime.now(UTC).isoformat(),
            "requested_model": args.model,
            "rubric": args.rubric,
            "rubric_digest": rubric.digest,
            "subject": subject,
            "runs": args.runs,
            "per_question": per_question,
            "observations": observations,
        },
        args,
    )


def _write(report: dict[str, object], args: argparse.Namespace) -> None:
    destination = Path(args.out) if args.out else _artifact_dir() / "report.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"\n-> {destination}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rubric", default="tool_risk")
    parser.add_argument("--out", default=None)
    sub = parser.add_subparsers(dest="command", required=True)

    models = sub.add_parser("models", help="L0 -- 목록과 별칭 해소")
    models.add_argument(
        "--also",
        nargs="*",
        default=[],
        help="추가로 해소를 확인할 모델 이름 (예: jev-1.13.0)",
    )
    models.set_defaults(func=probe_models)

    consistency = sub.add_parser("consistency", help="L1 -- 일관성 기준선")
    consistency.add_argument("--model", required=True, help="해소된 id 를 핀한다")
    consistency.add_argument("--runs", type=int, default=15)
    consistency.add_argument(
        "--subject",
        default=None,
        help="판단 대상 JSON. 밴드를 정할 기준선은 **중간대 대상**에서 재야 한다",
    )
    consistency.set_defaults(func=probe_consistency)

    args = parser.parse_args()
    asyncio.run(args.func(args))


if __name__ == "__main__":
    main()
