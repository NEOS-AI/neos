"""표본 아티팩트와 이벤트 원장으로 진단자의 입력을 만든다.

이 모듈은 정답키를 로드하지 않는다. 스펙 §2 참조 -- 작성자가 정답을 안다는
사실이 프롬프트로 새는 경로를 구조로 막는다.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import subprocess
from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime
from itertools import combinations
from pathlib import Path

import yaml
from sqlalchemy import select, text

from neos.config.model_routing import resolve_model
from neos.config.settings import settings
from neos.database.connection import get_session_ctx
from neos.database.deep_analysis_models import DAEvent
from neos.workflow.deep_analysis.analytics import DeepAnalysisAnalyticsService

EventRow = tuple[str, int, str, str]

_REPO_ROOT = Path(__file__).resolve().parent.parent
_PROMPT_PATH = (
    _REPO_ROOT
    / "neos" / "workflow" / "deep_analysis" / "prompts" / "diagnose_bottleneck.md"
)
_BACKTEST_DIR = Path(__file__).resolve().parent / "diagnostician_backtest"
_ANSWER_KEY_PATH = _BACKTEST_DIR / "answer_key.yaml"
_LABELS_PATH = _BACKTEST_DIR / "labels.yaml"
_SIGNAL_MAP_PATH = _BACKTEST_DIR / "signal_map.yaml"
_MAX_CANDIDATES = 3

ARTIFACT_ROOT = Path("artifacts/deep-analysis-funnel")
BACKTEST_ROOT = Path("artifacts/diagnostician-backtest")

_FOOTNOTE = re.compile(r"\[\d+\]")
_RAW_MARKER = re.compile(r"\[C:[0-9a-f]+\]")

_STOP_KINDS = (
    "token_budget_exhausted",
    "investigation_stopped_at_floor",
    "investigation_stopped_at_input_bound",
)

# 질문 하나의 일생 중 그 자체가 이벤트 kind 로 원장에 남는 세 갈래.
# `resolved`는 이 목록에 없다 -- `Ledger._transition`(ledger.py:305)이 상태만
# 바꾸고 이벤트를 남기지 않기 때문이다(D79 를 정정한 판정 참조). 해소 여부는
# `pass_completed`의 `resolved_gate` 필드가 대신 나른다 (ledger.py:863).
_QUESTION_EVENT_KINDS = ("question_opened", "abandoned", "dead_end")

# `pass_completed.resolved_gate`가 낼 수 있는 네 값 전부(ledger.py:863-871).
# 하나는 닫힘("resolved"), 셋은 왜 안 닫혔는지의 사유다.
_RESOLVED_GATE_VALUES = (
    "resolved", "failed_status", "no_verified_claim", "below_threshold",
)


def _count_footnotes(body: str) -> int:
    """배달된 리포트 본문 안 서로 다른 각주 번호 수."""
    return len(set(int(m[1:-1]) for m in _FOOTNOTE.findall(body)))


def _median(values: Sequence[int]) -> int | None:
    """`gate.uncited_ratio`와 같은 규칙: 값이 없으면 `None`, 있으면 정렬한
    가운데(짝수 길이는 위쪽) 원소. 이 프로젝트의 "배달 각주 중앙값" 어휘가
    가리키는 계산이 바로 이것이다.
    """
    if not values:
        return None
    ordered = sorted(values)
    return ordered[len(ordered) // 2]


def _delivered_summary(
    run_ids: Sequence[str], report_bodies: dict[str, str]
) -> dict:
    """표본의 배달 리포트 요약 -- run당 하나씩, 분포(중앙값)로 접는다.

    본문이 없는 run은 그 자체가 신호다(태스크 3) -- 빈 문자열로 조용히
    섞으면 `footnotes_median`이 실제로 배달된 본문들의 중앙값이 아니라
    "본문 없음"에 끌려간다. 그래서 `runs_missing_body`로 따로 세고,
    분포 계산에서는 아예 뺀다.
    """
    bodies = [report_bodies[rid] for rid in run_ids if rid in report_bodies]
    runs_with_body = len(bodies)
    return {
        "runs_total": len(run_ids),
        "runs_with_body": runs_with_body,
        "runs_missing_body": len(run_ids) - runs_with_body,
        "chars_median": _median([len(b) for b in bodies]),
        "footnotes_median": _median([_count_footnotes(b) for b in bodies]),
        "raw_markers_median": _median(
            [len(_RAW_MARKER.findall(b)) for b in bodies]
        ),
        "sources_section_count": sum(1 for b in bodies if "## 출처" in b),
    }


def _scrub_config(config_fingerprint: dict) -> dict:
    """설정 지문에서 표본을 특정하는 정체 정보를 뗀다.

    `git.commit`은 이 표본을 만든 실행이 체크아웃하고 있던 정확한 저장소
    SHA다 -- 진단자가 저장소를 읽지 못하는 오늘은 무해하지만, 읽을 수 있는
    진단자가 생기는 순간 표본을 저장소 이력과 대조해 식별하는 경로가 된다
    (태스크 5). 병목 진단에 커밋 SHA가 쓰일 이유가 없으므로 프롬프트에
    넣기 전에 뗀다. `branch`/`dirty`는 SHA와 달리 특정 실행을 가리키지
    않으므로 남긴다.
    """
    scrubbed = dict(config_fingerprint)
    git_info = scrubbed.get("git")
    if isinstance(git_info, dict) and "commit" in git_info:
        git_info = {k: v for k, v in git_info.items() if k != "commit"}
        scrubbed["git"] = git_info
    return scrubbed


def build_summary(
    rows: Sequence[EventRow],
    *,
    run_ids: Sequence[str],
    report_bodies: dict[str, str],
    config_fingerprint: dict,
) -> dict:
    events: dict[str, int] = defaultdict(int)
    by_stage: dict[str, dict[str, int]] = defaultdict(
        lambda: {"reserved": 0, "settled": 0, "calls": 0}
    )
    stage_of: dict[str, str] = {}
    clamp = {
        "exhausted": 0,
        "dropped_primary": 0,
        "primary_chars_after": 0,
        "anchor_chars_before": 0,
        "anchor_chars_after": 0,
        "distinct_claims_after": 0,
    }
    gate: dict[str, dict[str, int]] = {"codes": defaultdict(int),
                                       "judge_states": defaultdict(int)}
    uncited: list[float] = []
    passes = {"zero_token": 0, "productive": 0, "verified_total": 0}
    questions: dict[str, int] = {kind: 0 for kind in _QUESTION_EVENT_KINDS}
    resolved_gate: dict[str, int] = {
        value: 0 for value in _RESOLVED_GATE_VALUES
    }
    evidence = {"candidates": 0, "tier1_selected": 0}
    stop_reasons: dict[str, int] = defaultdict(int)

    for _run_id, _seq, kind, payload_json in rows:
        events[kind] += 1
        payload = json.loads(payload_json)
        if kind in _STOP_KINDS:
            stop_reasons[kind] += 1
        elif kind == "token_budget_reserved":
            stage = payload.get("stage", "?")
            stage_of[payload["reservation_id"]] = stage
            by_stage[stage]["reserved"] += payload.get("reserved_tokens", 0)
            by_stage[stage]["calls"] += 1
        elif kind == "token_budget_settled":
            stage = stage_of.get(payload.get("reservation_id"), "?")
            by_stage[stage]["settled"] += payload.get("actual_tokens", 0)
        elif kind == "finalization_prompt_clamped":
            clamp["exhausted"] += int(bool(payload.get("exhausted")))
            for field in ("dropped_primary", "primary_chars_after",
                          "anchor_chars_before", "anchor_chars_after",
                          "distinct_claims_after"):
                clamp[field] += int(payload.get(field, 0) or 0)
        elif kind == "report_graded":
            gate["codes"][str(payload.get("code", "OK"))] += 1
            gate["judge_states"][str(payload.get("judge", "absent"))] += 1
            if payload.get("uncited_ratio") is not None:
                uncited.append(float(payload["uncited_ratio"]))
        elif kind == "pass_completed":
            if payload.get("tokens", 0) > 0:
                passes["productive"] += 1
            else:
                passes["zero_token"] += 1
            passes["verified_total"] += int(payload.get("verified", 0) or 0)
            evidence["candidates"] += int(payload.get("candidates", 0) or 0)
            evidence["tier1_selected"] += int(payload.get("tier1", 0) or 0)
            gate_value = payload.get("resolved_gate")
            if gate_value in resolved_gate:
                resolved_gate[gate_value] += 1
        elif kind in _QUESTION_EVENT_KINDS:
            questions[kind] += 1

    total_pass = passes["productive"] + passes["zero_token"]
    return {
        "events": dict(events),
        "budget": {"by_stage": {k: dict(v) for k, v in by_stage.items()}},
        "clamp": clamp,
        "gate": {
            "codes": dict(gate["codes"]),
            "judge_states": dict(gate["judge_states"]),
            "uncited_ratio": {
                "n": len(uncited),
                "median": sorted(uncited)[len(uncited) // 2] if uncited else None,
            },
        },
        "stop_reasons": dict(stop_reasons),
        "passes": {
            **passes,
            "claims_per_pass": (
                passes["verified_total"] / passes["productive"]
                if passes["productive"] else 0.0
            ),
            "total": total_pass,
        },
        "questions": {**questions, "resolved_gate": dict(resolved_gate)},
        "evidence": {
            **evidence,
            "tier1_ratio": (
                evidence["tier1_selected"] / evidence["candidates"]
                if evidence["candidates"] else 0.0
            ),
        },
        "delivered": _delivered_summary(run_ids, report_bodies),
        "config": _scrub_config(config_fingerprint),
    }


def summary_field_paths(summary: dict) -> set[str]:
    """요약 안에서 점(`.`) 표기로 인용 가능한 모든 경로.

    리프뿐 아니라 중간 노드도 낸다 -- `clamp.exhausted`도, `clamp`도
    둘 다 인용 가능해야 한다(태스크 3). `summary`가 만드는 값에 리스트가
    없으므로(`build_summary`의 스키마) dict만 재귀한다; 스칼라 값은
    그 자체가 리프 경로로 이미 부모 순회에서 나온다.
    """
    paths: set[str] = set()

    def _walk(node: dict, prefix: str) -> None:
        for key, value in node.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            paths.add(path)
            if isinstance(value, dict):
                _walk(value, path)

    _walk(summary, "")
    return paths


def _evidence_matches_signal(path: str, signal_paths: Sequence[str]) -> bool:
    """`path`가 신호 지도의 한 항목과 겹치는가.

    정확히 같거나, 한쪽이 다른 쪽의 조상 경로(점으로 이어지는 접두)일
    때 겹친다고 본다 -- 모델이 `clamp`를 대면 `clamp.exhausted`를 가리킨
    셈이고, 그 반대도 마찬가지다.
    """
    for signal in signal_paths:
        if path == signal or path.startswith(f"{signal}.") or signal.startswith(f"{path}."):
            return True
    return False


def score_sample(
    candidates,
    *,
    truth,
    contemporaneous,
    valid_paths,
    signal_map: dict[str, Sequence[str]] | None = None,
) -> dict:
    """후보를 채점한다.

    `valid_paths`는 그 표본의 요약(`summary_field_paths`의 출력)에 실제로
    존재하는 점(`.`) 표기 경로 집합이다 -- 예전의 `run_id:seq` 이벤트 id가
    아니다(스펙 §5 정정). 근거가 없거나, 하나라도 요약에 없는 경로를
    대면 그 후보는 여전히 폐기된다.

    `signal_map`이 주어지면 폐기되지 않은 각 후보마다 `evidence_on_target`을
    함께 기록한다: 댄 경로 중 하나라도 신호 지도가 그 라벨에 적어둔 경로와
    겹치는가. **이것은 기록만 한다 -- recall이나 폐기 여부에 관여하지
    않는다.** 신호 지도는 정답을 읽은 사람이 썼으므로(태스크 4), 그것으로
    채점을 흔들면 오염이 채점 경로로 되돌아온다.
    """
    kept, discarded = [], []
    evidence_on_target: list[dict] = []
    for candidate in candidates:
        evidence = candidate.get("evidence") or []
        label = candidate["label"]
        if evidence and all(e in valid_paths for e in evidence):
            kept.append(label)
            if signal_map is not None:
                signals = signal_map.get(label, [])
                on_target = any(
                    _evidence_matches_signal(path, signals) for path in evidence
                )
                evidence_on_target.append({"label": label, "on_target": on_target})
        else:
            discarded.append(label)

    hits = [label for label in truth if label in kept]
    result = {
        "recall": len(hits) / len(truth) if truth else 0.0,
        "hits": hits,
        "kept": kept,
        "discarded": discarded,
        "reproduced_contemporaneous": (
            not hits and any(label in kept for label in contemporaneous)
        ),
    }
    if signal_map is not None:
        result["evidence_on_target"] = evidence_on_target
    return result


def constant_best(key: dict, labels, k: int = 3) -> float:
    """정답을 읽지 않는 최선의 고정 예측이 받는 평균 recall.

    모든 k-라벨 조합을 훑는다. 표본 창이 한 병목을 해상도를 높여가며 쫓던
    구간이면 이 값이 높게 나오고, 그것이 관문의 기준이 되어야 한다.
    """
    best = 0.0
    for combo in combinations(sorted(labels), k):
        chosen = set(combo)
        total = 0.0
        for entry in key.values():
            truth = entry["truth"]
            total += len([t for t in truth if t in chosen]) / len(truth)
        best = max(best, total / len(key))
    return best


def render_prompt(summary: dict, labels: Sequence[str]) -> str:
    """진단 프롬프트를 렌더한다. 표본 요약과 닫힌 라벨 집합만 들어간다.

    이 함수는 정답키를 읽지 않는다 -- 인자로 받는 `summary`/`labels`가 전부다
    (스펙 §2, 모듈 docstring). 치환은 `str.replace`이며, 출력 형식 절의 JSON
    리터럴(`{"candidates": ...}`)은 소문자 식별자 자리표시자 패턴과 겹치지
    않으므로 이스케이프가 필요 없다.
    """
    template = _PROMPT_PATH.read_text(encoding="utf-8")
    rendered = template.replace(
        "{labels}", "\n".join(f"- {label}" for label in labels)
    )
    return rendered.replace(
        "{summary}", json.dumps(summary, ensure_ascii=False, indent=2)
    )


async def diagnose(
    summary: dict, labels: Sequence[str], *, model: str, client=None
) -> dict:
    """표본 요약 하나로 병목 후보를 낸다. LLM 호출 1회.

    `retries=0`이다 -- 파싱될 때까지 다시 묻는 것은 점수를 부풀린다(스펙 §8).
    실패는 삼키지 않고 `failure`에 사유를 남긴다: `"unparseable"` (JSON이
    아니었거나, `candidates` 키 자체가 구조적으로 없었다), `"no_candidates"`
    (JSON은 파싱됐고 `candidates` 키도 있었지만 빈 목록이었다 -- 모델이
    정직하게 "후보 없음"이라 답한 경우다, 태스크 6), `"truncated"` (상한에
    잘렸고 확장 재시도도 잘렸다), `"off_label"` (닫힌 라벨 집합 밖의 라벨만
    나왔다), `"provider_error"` (전송 계층 자체가 실패했다 -- 인증, 네트워크,
    레이트리밋 등). 마지막 것은 앞의 사유들과 원인이 다르다: 응답이 왔는데
    그 내용이 문제인 게 아니라 응답 자체가 없었다. 이걸 삼켜서 예외로
    전파시키면 백테스트 한 번이 표본 18개를 부르는데 그중 하나가 반짝
    실패해도 이미 끝난 표본들의 결과까지 통째로 날아간다 -- 그래서 그 반복
    하나의 값으로만 기록하고 나머지는 계속 돈다.

    `TruncatedResponseError`는 `JSONParseError`의 하위클래스다
    (`neos/workflow/deep_analysis/llm.py`) -- 그래서 반드시 그것을 먼저
    잡는다. 순서를 바꾸면 잘림도 조용히 "unparseable"로 잡힌다.
    """
    from neos.workflow.deep_analysis.llm import (
        JSONParseError,
        LLMProviderError,
        TruncatedResponseError,
        call_json,
    )

    prompt = render_prompt(summary, labels)
    try:
        data, response = await call_json(
            model,
            prompt,
            max_tokens=2000,
            temperature=0.0,
            client=client,
            retries=0,
            stage="diagnose",
        )
    except TruncatedResponseError:
        return {"candidates": [], "failure": "truncated"}
    except JSONParseError:
        return {"candidates": [], "failure": "unparseable"}
    except LLMProviderError:
        return {"candidates": [], "failure": "provider_error"}

    allowed = set(labels)
    raw_candidates = data.get("candidates")
    candidates: list[dict] = []
    off_label = False
    for raw in raw_candidates or []:
        label = raw.get("label")
        if label not in allowed:
            off_label = True
            continue
        candidates.append({
            "label": label,
            "evidence": list(raw.get("evidence") or []),
            "reason": str(raw.get("reason", "")),
        })

    truncated = candidates[:_MAX_CANDIDATES]
    failure = None
    if not truncated:
        if off_label:
            failure = "off_label"
        elif raw_candidates == []:
            # 모델이 정직하게 "이 표본은 후보가 없다"고 답했다 -- JSON은
            # 파싱됐고 `candidates` 키도 있었다, 다만 비어 있었다. 이걸
            # "unparseable"로 적으면 이 필드가 정직하려고 넓힌 취지(태스크 6)
            # 가 무색해진다: 응답이 안 왔거나 못 읽은 것과 응답이 "없음"이라고
            # 말한 것은 다른 사건이다.
            failure = "no_candidates"
        else:
            failure = "unparseable"
    return {
        "candidates": truncated,
        "failure": failure,
        "output_tokens": getattr(response, "output_tokens", None),
    }


async def load_sample(
    sample_id: str, entry: dict, *, session
) -> tuple[list[EventRow], list[str], dict[str, str], dict]:
    """표본 하나의 원장 행·run별 배달 리포트·설정 지문을 읽어온다.

    `entry`는 정답키 항목이지만, 이 함수가 보는 건 `entry["artifact"]`
    (표본 폴더 타임스탬프) 뿐이다 -- `truth`/`contemporaneous`는 손대지
    않는다. 정답키 파일 자체를 여는 건 호출자(`main`)의 몫이다: 이
    모듈은 import 시점은 물론 어떤 경로로도 `answer_key.yaml`을 직접
    열지 않는다 (모듈 docstring, 스펙 §2).

    `sample_id`는 조회에 쓰이지 않는다(그건 `entry["artifact"]`가 전부
    한다) -- 표본 폴더를 못 찾았을 때 에러 메시지에 "표본 몇 번인지"를
    남기기 위해서만 쓴다. 그게 없으면 `FileNotFoundError`가 타임스탬프만
    가리키고, 정답키의 어느 항목이 잘못됐는지는 사람이 다시 대조해야 한다.

    배달된 리포트 본문은 `sample_dir / "report.md"`가 아니다 -- 그건 퍼널
    러너 자신의 사례별 집계표이지, 심층분석이 낸 리포트가 아니다(표본마다
    형태가 동일하고 약 1.1KB). 진짜 본문은 `deep_analysis_runs.report_path`가
    아니라 DB의 `job_completed` 이벤트 페이로드에 실린다(`Ledger.
    report_markdown()` 문서 참조) -- 그래서 `DeepAnalysisAnalyticsService.
    report_bodies()`로 이 표본의 run들을 한 번에 조회한다. 본문이 없는
    run은 반환 dict에서 그냥 빠진다(빈 문자열로 채우지 않는다) -- 호출자가
    "본문 없음"을 신호로 셀 수 있어야 한다.
    """
    sample_dir = ARTIFACT_ROOT / entry["artifact"]
    try:
        manifest = json.loads((sample_dir / "manifest.json").read_text())
    except FileNotFoundError as exc:
        raise FileNotFoundError(
            f"sample {sample_id!r}: no manifest at {sample_dir / 'manifest.json'}"
        ) from exc
    run_ids = [
        r["run_id"] for r in manifest.get("dev_runs", []) if r.get("run_id")
    ]
    default_run = manifest.get("default_run") or {}
    if default_run.get("run_id"):
        run_ids.append(default_run["run_id"])

    result = await session.execute(
        select(DAEvent.run_id, DAEvent.seq, DAEvent.kind, DAEvent.payload)
        .where(DAEvent.run_id.in_(run_ids))
        .order_by(DAEvent.run_id, DAEvent.seq)
    )
    rows: list[EventRow] = [tuple(row) for row in result.all()]
    report_bodies = await DeepAnalysisAnalyticsService(session).report_bodies(
        run_ids
    )
    return rows, run_ids, report_bodies, dict(manifest.get("config_fingerprint", {}))


def write_artifacts(root: Path, *, manifest, inputs, outputs, score) -> Path:
    """빗나갔을 때 '그 신호가 요약에 있었나'를 사람이 확인할 수 있게 한다.

    입력(진단자가 실제로 본 요약)과 출력(모델이 낸 후보)을 나란히 남긴다
    -- 답만 남기면 그 질문에 영원히 답할 수 없다 (스펙 §7).
    """
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = root / stamp
    (out / "inputs").mkdir(parents=True, exist_ok=True)
    (out / "outputs").mkdir(parents=True, exist_ok=True)

    def _dump(path: Path, payload) -> None:
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    _dump(out / "manifest.json", {"generated_at": stamp, **manifest})
    _dump(out / "score.json", score)
    for sample_id, summary in inputs.items():
        _dump(out / "inputs" / f"{sample_id}.json", summary)
    for sample_id, repeats in outputs.items():
        for index, result in enumerate(repeats):
            _dump(out / "outputs" / f"{sample_id}-{index}.json", result)
    return out


class PreflightError(RuntimeError):
    """필요한 프로덕션 의존성(자격 증명·DB)이 없을 때."""


def _git(*args: str) -> str:
    """git 조회 하나, 실패하면 `"unavailable"`.

    절대 예외를 던지지 않는다 -- 영수증에 SHA 하나가 빠지는 것과
    백테스트 전체가 죽는 것은 다른 무게다 (`deep_analysis_funnel_sample.
    py`의 같은 이름 헬퍼와 동일한 계약).
    """
    try:
        completed = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=_REPO_ROOT,
            check=True,
        )
    except (subprocess.SubprocessError, OSError):
        return "unavailable"
    return completed.stdout.strip()


def _answer_key_sha() -> str:
    """정답키를 마지막으로 건드린 커밋.

    점수를 흔드는 네 가지(모델·반복 횟수·정답키·트리 상태) 중 정답키
    쪽을 가리키는 필드 -- 정답키가 바뀌면 이전 점수와 지금 점수는
    비교 대상이 아니다.
    """
    sha = _git(
        "log", "-1", "--format=%H", "--",
        str(_ANSWER_KEY_PATH.relative_to(_REPO_ROOT)),
    )
    return sha or "unavailable"


def _git_tree_clean() -> bool | str:
    status = _git("status", "--porcelain")
    if status == "unavailable":
        return "unavailable"
    return status == ""


def _resolved_model() -> str:
    """`powerful` 역할이 해석하는 모델 ID.

    설계가 지목하는 역할이 `powerful`이다 -- 이 백테스트가 재는 건
    실제 운영에서 진단을 맡길 모델의 성능이지, 저비용 모델의 성능이
    아니다. `deep_analysis_discard_recall.py`의 `_resolved_model`과
    같은 호출 형태(오버라이드 없이 role default)를 따른다.
    """
    return resolve_model(
        config=settings.config.model_routing,
        provider="anthropic",
        role="powerful",
    ).model


async def _preflight() -> None:
    if not getattr(settings, "ANTHROPIC_API_KEY", None):
        raise PreflightError("missing required credential: ANTHROPIC_API_KEY")
    async with get_session_ctx() as session:
        await session.execute(text("SELECT 1"))


def _load_answer_key() -> dict:
    """정답키를 연다.

    모듈이 금지하는 건 이 파일을 import 시점에 여는 것과, 진단자가 보는
    값(`build_summary`/`render_prompt`의 인자)에 진실이 섞여 드는 것이다
    (모듈 docstring, 스펙 §2). 최종 recall을 계산하려면 어차피 진실이
    필요하고, 그 채점 경로가 여기 -- `main()` 안 -- 다.
    """
    return yaml.safe_load(_ANSWER_KEY_PATH.read_text(encoding="utf-8"))


def _load_labels() -> list[str]:
    return yaml.safe_load(_LABELS_PATH.read_text(encoding="utf-8"))["labels"]


def _load_signal_map() -> dict[str, list[str]]:
    return yaml.safe_load(_SIGNAL_MAP_PATH.read_text(encoding="utf-8"))["signals"]


async def _run_sample(
    sample_id: str, entry: dict, *,
    labels: Sequence[str], model: str, repeats: int, session,
    signal_map: dict[str, Sequence[str]] | None = None,
) -> tuple[dict, list[dict]]:
    """표본 하나: 요약을 만들고, `repeats`번 진단을 돌려 각각 채점한다.

    `diagnose()`는 이미 `provider_error`/`unparseable`/`no_candidates`/
    `truncated`/`off_label`을 삼켜 `failure`로 반환한다 (그 함수의
    docstring). 여기
    추가하는 `except Exception`은 마지막 안전망이다 -- 분류되지 않은
    예외 하나가 나머지 반복과 나머지 표본까지 끌고 내려가지 않도록,
    그 반복 하나만 실패로 기록하고 계속 돈다(스펙 §8, 이 태스크 항목 4).

    유효한 근거 경로 집합은 이 표본 자신의 요약에서 만든다
    (`summary_field_paths`) -- 예전의 이벤트 id 집합과 달리 표본마다
    스키마는 같아도 실제로 채워진 경로(예: `budget.by_stage.<stage명>`)는
    다르므로 표본별로 다시 계산해야 한다.
    """
    rows, run_ids, report_bodies, config_fingerprint = await load_sample(
        sample_id, entry, session=session
    )
    summary = build_summary(
        rows, run_ids=run_ids, report_bodies=report_bodies,
        config_fingerprint=config_fingerprint,
    )
    valid_paths = summary_field_paths(summary)

    repeat_results: list[dict] = []
    for _ in range(repeats):
        try:
            result = await diagnose(summary, labels, model=model)
        except Exception as exc:  # noqa: BLE001 -- one bad repetition must not sink the run
            result = {
                "candidates": [],
                "failure": "unexpected_error",
                "error": str(exc),
            }
        score = score_sample(
            result.get("candidates", []),
            truth=entry["truth"],
            contemporaneous=entry["contemporaneous"],
            valid_paths=valid_paths,
            signal_map=signal_map,
        )
        repeat_results.append({**result, "score": score})
    return summary, repeat_results


def _evidence_validity_rate(repeat_results: Sequence[dict]) -> float:
    """`kept / (kept + discarded)`, 후보가 하나도 없으면 0.0.

    후보를 하나도 안 낸(또는 전부 폐기된) 반복은 분모에 아무것도 보태지
    않는다 -- `failure` 사유(`unparseable` 등)로 이미 따로 잡히므로 여기서
    0으로 나누는 대신 그 반복은 조용히 건너뛴다.
    """
    kept = sum(len(r["score"]["kept"]) for r in repeat_results)
    discarded = sum(len(r["score"]["discarded"]) for r in repeat_results)
    total = kept + discarded
    return kept / total if total else 0.0


def _aggregate(outputs: dict[str, list[dict]]) -> dict:
    """`mean_recall`: 표본 안 반복을 먼저 평균하고, 그다음 표본을 평균한다.

    반복을 먼저 접지 않고 전체를 평균하면 반복 횟수가 다른 표본이 있을 때
    (예: 실패로 조기 종료) 반복이 많은 표본 쪽으로 가중치가 쏠린다.

    `evidence_validity_rate`: 채점기가 유효한 근거로 인정한(폐기되지 않은)
    후보의 비율, 전체와 표본별로 각각. 태스크 5 -- 관문(스펙 §6)의 절반은
    recall이 아니라 이 값이 지키므로, 표본을 뭉개기 전에 표본별 값도 함께
    남긴다.
    """
    per_sample: dict[str, float] = {}
    per_sample_validity: dict[str, float] = {}
    for sample_id, repeat_results in outputs.items():
        recalls = [r["score"]["recall"] for r in repeat_results]
        per_sample[sample_id] = sum(recalls) / len(recalls) if recalls else 0.0
        per_sample_validity[sample_id] = _evidence_validity_rate(repeat_results)
    mean_recall = sum(per_sample.values()) / len(per_sample) if per_sample else 0.0

    all_results = [r for repeat_results in outputs.values() for r in repeat_results]
    return {
        "mean_recall": mean_recall,
        "per_sample_recall": per_sample,
        "evidence_validity_rate": _evidence_validity_rate(all_results),
        "per_sample_evidence_validity_rate": per_sample_validity,
    }


async def _main(
    repeats: int, sample_ids: list[str] | None, output_root: Path
) -> Path:
    answer_key = _load_answer_key()
    labels = _load_labels()
    signal_map = _load_signal_map()
    all_samples = answer_key["samples"]

    if sample_ids:
        unknown = set(sample_ids) - set(all_samples)
        if unknown:
            raise SystemExit(
                "unknown --sample id(s): " + ", ".join(sorted(unknown))
            )
        samples = {sid: all_samples[sid] for sid in sample_ids}
    else:
        samples = all_samples

    await _preflight()
    model = _resolved_model()
    started_at = datetime.now(UTC)

    inputs: dict[str, dict] = {}
    outputs: dict[str, list[dict]] = {}
    async with get_session_ctx() as session:
        for sample_id, entry in samples.items():
            summary, repeat_results = await _run_sample(
                sample_id, entry, labels=labels, model=model,
                repeats=repeats, session=session, signal_map=signal_map,
            )
            inputs[sample_id] = summary
            outputs[sample_id] = repeat_results

    finished_at = datetime.now(UTC)

    score = {
        **_aggregate(outputs),
        "constant_best": constant_best(samples, labels),
        "baseline_constant_best": answer_key.get("baseline_constant_best"),
    }
    manifest = {
        "model": model,
        "repeats": repeats,
        "sample_ids": list(samples),
        "answer_key_sha": _answer_key_sha(),
        "git_tree_clean": _git_tree_clean(),
        "started_at": started_at.isoformat().replace("+00:00", "Z"),
        "finished_at": finished_at.isoformat().replace("+00:00", "Z"),
    }
    return write_artifacts(
        output_root, manifest=manifest, inputs=inputs, outputs=outputs,
        score=score,
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the read-only diagnostician against the pre-registered "
            "answer key and write an auditable artifact directory."
        )
    )
    parser.add_argument(
        "--repeats", type=int, default=3,
        help="LLM calls per sample (default: 3)",
    )
    parser.add_argument(
        "--sample", action="append", dest="samples", default=None,
        help=(
            "Restrict the run to this answer-key sample id (repeatable). "
            "Default: every sample in answer_key.yaml. Use this to smoke-"
            "test the command cheaply before spending the full budget."
        ),
    )
    parser.add_argument(
        "--output-root", type=Path, default=BACKTEST_ROOT,
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    out = asyncio.run(_main(args.repeats, args.samples, args.output_root))
    print(out)


if __name__ == "__main__":
    main()
