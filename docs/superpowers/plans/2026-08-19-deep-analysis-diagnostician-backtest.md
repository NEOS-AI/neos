# 진단자 백테스트 (트랙 F의 F1) 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 표본 #11~#16의 아티팩트만 보고 병목을 맞히는 읽기 전용 진단자를 만들고,
`DECISIONS.md`에 기록된 정답으로 채점한다. 라이브 표본은 한 건도 쓰지 않는다.

**Architecture:** 스크립트 하나(`scripts/deep_analysis_diagnostician.py`)에 순수 함수
셋(집계·채점·기준선)과 LLM 호출 하나를 둔다. 사전 등록 데이터(라벨·정답키·신호지도)는
별도 디렉터리에 YAML로 두고 **코드보다 먼저 커밋한다.** 채점기만 정답키를 로드하고,
진단 경로는 그 모듈을 import하지 않는다.

**Tech Stack:** Python 3.12 · SQLAlchemy async (`deep_analysis_events` 조회) ·
`neos.workflow.deep_analysis.llm.call_json` · PyYAML · pytest

## Global Constraints

- 설계 정본: `docs/superpowers/specs/2026-08-19-deep-analysis-diagnostician-backtest-design.md`
- 진단 경로는 **정답키를 절대 로드하지 않는다.** 렌더된 프롬프트에 정답키 문자열이
  없다는 것을 테스트가 단언한다 (스펙 §2·§8)
- 집계는 **표본 id로 분기하지 않는다** (스펙 §2)
- LLM 호출은 `retries=0` — 파싱될 때까지 재질의하지 않는다 (스펙 §8)
- 실패는 삼키지 않고 사유를 남긴다: `unparseable` / `truncated` / `off_label`
- 테스트는 LLM을 호출하지 않는다. 가짜 클라이언트만 쓴다
- 이벤트 id 표기는 `"{run_id}:{seq}"` — `deep_analysis_events`의 PK가
  (`run_id`, `seq`)이기 때문이다
- 검증 명령: `HOME=/tmp/neos-test-home .venv/bin/pytest tests/workflow/deep_analysis -q`
- 커밋 메시지에 `Co-Authored-By` 트레일러를 넣지 않는다

---

### Task 1: 사전 등록 — 라벨·정답키·신호지도

**코드보다 먼저 커밋한다.** 사후에 정하면 판정이 아니라 합리화가 된다 (스펙 §3).

**Files:**
- Create: `scripts/diagnostician_backtest/labels.yaml`
- Create: `scripts/diagnostician_backtest/answer_key.yaml`
- Create: `scripts/diagnostician_backtest/signal_map.yaml`
- Test: `tests/workflow/deep_analysis/test_diagnostician_preregistration.py`

**Interfaces:**
- Consumes: 없음 (첫 태스크)
- Produces: 세 YAML 파일. 이후 태스크가 `yaml.safe_load`로 읽는다.
  `labels.yaml` → `{"labels": [str, ...]}` (17개)
  `answer_key.yaml` → `{"samples": {"11": {"artifact": str, "decision": str,
  "truth": [str], "contemporaneous": [str], "quote": str}, ...}}`
  `signal_map.yaml` → `{"signals": {"<label>": ["<summary 필드 경로>", ...]}}`

- [ ] **Step 1: `labels.yaml` 작성**

파이프라인 단계마다 라벨을 준다. #11~#16의 정답이 어디였는지와 무관하게 구성한다.

```yaml
# 닫힌 라벨 집합. 진단자는 여기서만 고른다.
# 파이프라인(설계 §3.1)의 단계마다 하나씩 두었고, 표본 #11~#16의 정답이
# 어디였는지를 보고 만들지 않았다 -- 정답 쪽으로 치우쳤는지는 "모든 단계에
# 라벨이 있는가"로 검사할 수 있다.
labels:
  - search_recall          # 검색이 후보를 못 가져온다
  - source_quality         # 1차 기관 출처를 못 잡는다
  - worker_extraction      # 워커가 증거에서 클레임을 못 뽑는다
  - claim_grading          # 결정론 채점이 과하게 버린다
  - entailment_filter      # entailment가 과하게 버린다
  - subquestion_coverage   # 조사 축이 빠진다
  - investigation_budget   # 조사 예산이 소진돼 패스가 거절된다
  - budget_floor_formula   # 바닥 산식이 실제 비용을 못 덮는다
  - reduction_layer        # node_reduction이 클레임을 잃는다
  - degraded_join          # 강등 요약 join이 무계로 커진다
  - assembly_clamp         # 조립 프롬프트 클램프가 재료를 버린다
  - assembly_truncation    # 조립 출력이 상한에 잘린다
  - writer_prompt          # 작성자가 받은 재료를 안 쓴다
  - citation_render        # 렌더/마커 해소 경로
  - gate_definition        # 게이트가 세는 대상이 틀렸다
  - judge_budget           # 판정자가 굶는다
  - instrumentation        # 계측이 없거나 틀려 원인을 가를 수 없다
```

- [ ] **Step 2: `answer_key.yaml` 작성 — D53~D63을 직접 읽고 인용을 붙인다**

`truth`는 최종 확립된 병목(나중 표본의 정정 포함), `contemporaneous`는 그 시점에
사람이 그 표본만 보고 내린 결론이다. 아래는 각 D 항목의 「다음」 절에서 뽑았다.

```yaml
samples:
  "11":
    artifact: 20260809T125612Z
    decision: D53
    truth: [assembly_clamp, degraded_join]
    contemporaneous: [assembly_clamp, degraded_join]
    quote: "root_answer 를 clamp 대상에 넣는 것이 지금 가장 큰 한 수다"
  "12":
    artifact: 20260809T160315Z
    decision: D55
    truth: [budget_floor_formula]
    contemporaneous: [budget_floor_formula]
    quote: "call_text 의 절단 확장이 조립 예산의 3배를 쓰는데 바닥은 2배만 잡는다"
  "13":
    artifact: 20260810T110354Z
    decision: D57
    # 당시에는 원인을 가를 수 없었고(계측 부족), 실제 병목은 #14·#15가 확정했다.
    truth: [assembly_clamp]
    contemporaneous: [instrumentation]
    quote: "다음 수는 고치는 것이 아니라 재는 것이다"
  "14":
    artifact: 20260810T154952Z
    decision: D59
    truth: [assembly_clamp, instrumentation]
    contemporaneous: [assembly_clamp, instrumentation]
    quote: "병목은 순수하게 절삭이다, 그리고 내 계측이 반쯤 틀렸다"
  "15":
    artifact: 20260811T103154Z
    decision: D61
    truth: [assembly_clamp]
    contemporaneous: [assembly_clamp]
    quote: "절삭이 마커를 인지하게 만들면 어떤 분포에서도 클레임 생존이 오른다"
  "16":
    artifact: 20260811T152942Z
    decision: D63
    truth: [subquestion_coverage]
    contemporaneous: [subquestion_coverage]
    quote: "남은 판정자 불만은 커버리지 하나이고, 그것은 조사 깊이의 문제다"

# 이 정답키에서 계산한 constant_best. Task 3 의 테스트가 계산값과 대조한다.
# 손으로 고치지 말고 `constant_best()` 로 계산해 적을 것.
baseline_constant_best: 0.8333333333333334
```

> 🔴 **초안 정답키의 `constant_best` 는 83.3% 다** -- `{assembly_clamp,
> budget_floor_formula, subquestion_coverage}` 를 항상 답하면 6개 표본 중
> 다섯을 (부분적으로) 덮는다. 스펙 §6 의 관문(`>= constant_best + 1/6`)을
> 그대로 적용하면 **100%** 가 되어 사실상 만점을 요구한다.
>
> **Task 1 을 마친 뒤 관문을 다시 정해야 한다.** 판단 재료:
> - 순수한 고정 예측기는 **근거 이벤트 id 를 댈 수 없으므로 실제로는 0점**이다
>   (Task 3 의 폐기 규칙). `constant_best` 는 "요약을 읽고 id 는 베끼되 추론은
>   하지 않는" 예측기의 상한이다.
> - 표본이 6개뿐이고 정답 라벨이 다섯 개에 몰려 있는 것이 근본 원인이다.
>   라벨을 잘게 쪼개는 것은 정답에 맞춘 재단이라 스펙 §2 가 막는다.
> - 후보: (a) 관문을 `>= constant_best` 로 낮추고 **근거 id 유효율**을 함께
>   관문에 넣는다 (b) 표본 창을 #6~#16 으로 넓혀 정답 분포를 흩뜨린다.

> ⚠️ **작성자는 D53~D63을 직접 열어 위 `truth`/`contemporaneous`가 그 본문과 맞는지
> 확인하고, 다르면 본문을 따른다.** 위 표는 「다음」 절만 보고 뽑은 초안이다.
> 특히 #13의 두 칸이 갈리는지(당시 `instrumentation`, 실제 `assembly_clamp`)를
> D57 본문으로 확인할 것 — 이 표본이 스펙 §6의 판별 규칙을 실제로 발동시키는
> 유일한 표본이다.

- [ ] **Step 3: `signal_map.yaml` 작성**

라벨마다 "이 병목이 있다면 고정 요약의 어느 필드에 나타나야 하는가"를 적는다.
필드 경로는 Task 2의 요약 스키마를 가리킨다.

```yaml
signals:
  search_recall:         [evidence.tier1_selected, evidence.candidates]
  source_quality:        [evidence.tier1_ratio]
  worker_extraction:     [passes.verified_total, passes.claims_per_pass]
  claim_grading:         [events.claim_rejected, events.claim_verified]
  entailment_filter:     [events.entailment_filter_skipped]
  subquestion_coverage:  [questions.open, questions.resolved, questions.abandoned]
  investigation_budget:  [passes.zero_token, stop_reasons]
  budget_floor_formula:  [budget.by_stage, events.report_assembly_degraded]
  reduction_layer:       [events.node_reduction_degraded, budget.by_stage]
  degraded_join:         [clamp.anchor_chars_before, clamp.anchor_chars_after]
  assembly_clamp:        [clamp.exhausted, clamp.dropped_primary, clamp.primary_chars_after]
  assembly_truncation:   [events.llm_truncated, budget.by_stage]
  writer_prompt:         [delivered.footnotes, clamp.distinct_claims_after]
  citation_render:       [delivered.raw_markers, delivered.sources_section]
  gate_definition:       [gate.codes, gate.uncited_ratio]
  judge_budget:          [gate.judge_states]
  instrumentation:       []   # 빈 목록 = 어떤 필드로도 확정할 수 없다는 주장 자체
```

- [ ] **Step 4: 사전 등록을 검증하는 테스트를 쓴다**

```python
from pathlib import Path

import yaml

PREREG = Path("scripts/diagnostician_backtest")


def _load(name: str) -> dict:
    return yaml.safe_load((PREREG / name).read_text(encoding="utf-8"))


def test_label_set_is_closed_and_sized():
    labels = _load("labels.yaml")["labels"]
    assert len(labels) == len(set(labels)), "라벨이 중복된다"
    assert len(labels) == 17


def test_every_key_label_is_in_the_closed_set():
    labels = set(_load("labels.yaml")["labels"])
    samples = _load("answer_key.yaml")["samples"]
    for sample_id, entry in samples.items():
        for field in ("truth", "contemporaneous"):
            unknown = set(entry[field]) - labels
            assert not unknown, f"#{sample_id} {field}에 집합 밖 라벨: {unknown}"


def test_answer_key_covers_samples_11_through_16():
    samples = _load("answer_key.yaml")["samples"]
    assert set(samples) == {"11", "12", "13", "14", "15", "16"}
    for entry in samples.values():
        assert entry["quote"], "인용 없는 정답은 근거 없는 정답이다"
        assert entry["decision"].startswith("D")


def test_signal_map_covers_every_label():
    labels = set(_load("labels.yaml")["labels"])
    signals = _load("signal_map.yaml")["signals"]
    assert set(signals) == labels, "라벨과 신호 지도가 어긋난다"
```

- [ ] **Step 5: 테스트를 돌려 통과를 확인한다**

Run: `HOME=/tmp/neos-test-home .venv/bin/pytest tests/workflow/deep_analysis/test_diagnostician_preregistration.py -v`
Expected: 4 passed

- [ ] **Step 6: 커밋**

```bash
git add scripts/diagnostician_backtest tests/workflow/deep_analysis/test_diagnostician_preregistration.py
git commit -m "test(deep-analysis): pre-register the diagnostician backtest's answer key

The key, the label set and the signal map land before any diagnostician
code, because a key written after seeing the output is not a judgement.
Each sample carries the quote from its D entry, so a later reader can
check the label against what was actually recorded rather than against
what someone remembered."
```

---

### Task 2: 고정 스키마 집계 (`build_input`)

**Files:**
- Create: `scripts/deep_analysis_diagnostician.py`
- Test: `tests/workflow/deep_analysis/test_diagnostician_input.py`

**Interfaces:**
- Consumes: Task 1의 `labels.yaml` (프롬프트에 라벨 목록을 실을 때만)
- Produces:
  - `EventRow = tuple[str, int, str, str]` — (run_id, seq, kind, payload_json)
  - `build_summary(rows: Sequence[EventRow], *, report_markdown: str,
    config_fingerprint: dict) -> dict` — 고정 스키마 요약
  - 요약의 최상위 키: `events` · `budget` · `clamp` · `gate` · `stop_reasons`
    · `passes` · `questions` · `evidence` · `delivered` · `config`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
import json

from scripts.deep_analysis_diagnostician import build_summary


def _row(run_id: str, seq: int, kind: str, payload: dict):
    return (run_id, seq, kind, json.dumps(payload))


def test_summary_counts_events_by_kind():
    rows = [
        _row("r1", 1, "claim_verified", {}),
        _row("r1", 2, "claim_verified", {}),
        _row("r1", 3, "claim_rejected", {}),
    ]
    summary = build_summary(rows, report_markdown="", config_fingerprint={})
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
    summary = build_summary(rows, report_markdown="", config_fingerprint={})
    stage = summary["budget"]["by_stage"]["worker_analysis"]
    assert stage["reserved"] == 100
    assert stage["settled"] == 40
    assert stage["calls"] == 1


def test_summary_counts_zero_token_passes():
    rows = [
        _row("r1", 1, "pass_completed", {"status": "failed", "tokens": 0}),
        _row("r1", 2, "pass_completed", {"status": "completed", "tokens": 900}),
    ]
    summary = build_summary(rows, report_markdown="", config_fingerprint={})
    assert summary["passes"]["zero_token"] == 1
    assert summary["passes"]["productive"] == 1


def test_summary_reads_the_delivered_report():
    summary = build_summary(
        [],
        report_markdown="본문[1] 그리고 [C:abc123] 남음\n\n## 출처\n[1] x",
        config_fingerprint={},
    )
    assert summary["delivered"]["footnotes"] == 1
    assert summary["delivered"]["raw_markers"] == 1
    assert summary["delivered"]["sources_section"] is True


def test_summary_schema_is_identical_for_empty_and_full_input():
    """표본마다 같은 스키마여야 비교가 성립한다."""
    empty = build_summary([], report_markdown="", config_fingerprint={})
    full = build_summary(
        [_row("r1", 1, "claim_verified", {})],
        report_markdown="x",
        config_fingerprint={"global_token_cap": 140000},
    )
    assert set(empty) == set(full)
```

- [ ] **Step 2: 테스트를 돌려 실패를 확인한다**

Run: `HOME=/tmp/neos-test-home .venv/bin/pytest tests/workflow/deep_analysis/test_diagnostician_input.py -v`
Expected: FAIL — `ModuleNotFoundError` 또는 `ImportError: cannot import name 'build_summary'`

- [ ] **Step 3: `build_summary`를 구현한다**

```python
"""표본 아티팩트와 이벤트 원장으로 진단자의 입력을 만든다.

이 모듈은 정답키를 로드하지 않는다. 스펙 §2 참조 -- 작성자가 정답을 안다는
사실이 프롬프트로 새는 경로를 구조로 막는다.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import Sequence

EventRow = tuple[str, int, str, str]

_FOOTNOTE = re.compile(r"\[\d+\]")
_RAW_MARKER = re.compile(r"\[C:[0-9a-f]+\]")

_STOP_KINDS = (
    "token_budget_exhausted",
    "investigation_stopped_at_floor",
    "investigation_stopped_at_input_bound",
)


def build_summary(
    rows: Sequence[EventRow],
    *,
    report_markdown: str,
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
    questions: dict[str, int] = defaultdict(int)
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
        elif kind in ("question_opened", "resolved", "abandoned", "dead_end"):
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
        "questions": dict(questions),
        "evidence": {
            **evidence,
            "tier1_ratio": (
                evidence["tier1_selected"] / evidence["candidates"]
                if evidence["candidates"] else 0.0
            ),
        },
        "delivered": {
            "chars": len(report_markdown),
            "footnotes": len(_FOOTNOTE.findall(report_markdown)),
            "raw_markers": len(_RAW_MARKER.findall(report_markdown)),
            "sources_section": "## 출처" in report_markdown,
        },
        "config": dict(config_fingerprint),
    }
```

- [ ] **Step 4: 테스트를 돌려 통과를 확인한다**

Run: `HOME=/tmp/neos-test-home .venv/bin/pytest tests/workflow/deep_analysis/test_diagnostician_input.py -v`
Expected: 5 passed

- [ ] **Step 5: 집계가 표본을 모른다는 것을 단언하는 테스트를 추가한다**

```python
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
```

- [ ] **Step 6: 테스트를 돌려 통과를 확인한다**

Run: `HOME=/tmp/neos-test-home .venv/bin/pytest tests/workflow/deep_analysis/test_diagnostician_input.py -v`
Expected: 6 passed

- [ ] **Step 7: 커밋**

```bash
git add scripts/deep_analysis_diagnostician.py tests/workflow/deep_analysis/test_diagnostician_input.py
git commit -m "feat(deep-analysis): aggregate a sample into the diagnostician's fixed input

Every sample gets the same summary, derived from the ledger's own
vocabulary rather than from what the answer happens to be. A test reads
the aggregator's source and fails if a sample identifier appears in it,
because choosing the input per sample is how an author who knows the
answers leaks them."
```

---

### Task 3: 채점과 기준선 (`score`, `constant_best`)

**Files:**
- Modify: `scripts/deep_analysis_diagnostician.py`
- Test: `tests/workflow/deep_analysis/test_diagnostician_score.py`

**Interfaces:**
- Consumes: Task 1의 `answer_key.yaml`, Task 2의 모듈
- Produces:
  - `Candidate = dict` — `{"label": str, "evidence": [str], "reason": str}`
  - `score_sample(candidates, *, truth, contemporaneous, valid_event_ids) -> dict`
    반환: `{"recall": float, "hits": [str], "kept": [str], "discarded": [str],
    "reproduced_contemporaneous": bool}`
  - `constant_best(key: dict, labels: Sequence[str], k: int = 3) -> float`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
from scripts.deep_analysis_diagnostician import constant_best, score_sample


def _c(label, evidence=("r1:1",)):
    return {"label": label, "evidence": list(evidence), "reason": "왜냐하면"}


def test_recall_counts_the_fraction_of_truth_labels_found():
    result = score_sample(
        [_c("assembly_clamp"), _c("gate_definition"), _c("judge_budget")],
        truth=["assembly_clamp", "degraded_join"],
        contemporaneous=["assembly_clamp", "degraded_join"],
        valid_event_ids={"r1:1"},
    )
    assert result["recall"] == 0.5
    assert result["hits"] == ["assembly_clamp"]


def test_a_candidate_citing_an_unknown_event_is_discarded():
    """근거 없는 문장은 판정 대상이 아니라 폐기 대상이다 (설계 §13.2)."""
    result = score_sample(
        [_c("assembly_clamp", evidence=["r9:999"])],
        truth=["assembly_clamp"],
        contemporaneous=["assembly_clamp"],
        valid_event_ids={"r1:1"},
    )
    assert result["discarded"] == ["assembly_clamp"]
    assert result["recall"] == 0.0


def test_reproducing_the_contemporaneous_answer_is_recorded_separately():
    """#13처럼 두 칸이 갈리는 표본에서 '계측 부족'을 가려낸다."""
    result = score_sample(
        [_c("instrumentation")],
        truth=["assembly_clamp"],
        contemporaneous=["instrumentation"],
        valid_event_ids={"r1:1"},
    )
    assert result["recall"] == 0.0
    assert result["reproduced_contemporaneous"] is True


def test_constant_best_finds_the_strongest_fixed_prediction():
    """아무것도 읽지 않는 예측기의 점수. 이것이 구속력 있는 기준선이다."""
    key = {
        "11": {"truth": ["assembly_clamp", "degraded_join"]},
        "12": {"truth": ["budget_floor_formula"]},
        "13": {"truth": ["assembly_clamp"]},
        "14": {"truth": ["assembly_clamp", "instrumentation"]},
        "15": {"truth": ["assembly_clamp"]},
        "16": {"truth": ["subquestion_coverage"]},
    }
    labels = ["assembly_clamp", "degraded_join", "instrumentation",
              "budget_floor_formula", "subquestion_coverage", "gate_definition"]
    assert abs(constant_best(key, labels) - 4 / 6) < 1e-9
```

- [ ] **Step 2: 테스트를 돌려 실패를 확인한다**

Run: `HOME=/tmp/neos-test-home .venv/bin/pytest tests/workflow/deep_analysis/test_diagnostician_score.py -v`
Expected: FAIL — `ImportError: cannot import name 'score_sample'`

- [ ] **Step 3: 채점기를 구현한다**

```python
from itertools import combinations


def score_sample(
    candidates,
    *,
    truth,
    contemporaneous,
    valid_event_ids,
) -> dict:
    kept, discarded = [], []
    for candidate in candidates:
        evidence = candidate.get("evidence") or []
        if evidence and all(e in valid_event_ids for e in evidence):
            kept.append(candidate["label"])
        else:
            discarded.append(candidate["label"])

    hits = [label for label in truth if label in kept]
    return {
        "recall": len(hits) / len(truth) if truth else 0.0,
        "hits": hits,
        "kept": kept,
        "discarded": discarded,
        "reproduced_contemporaneous": (
            not hits and any(label in kept for label in contemporaneous)
        ),
    }


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
```

- [ ] **Step 4: 테스트를 돌려 통과를 확인한다**

Run: `HOME=/tmp/neos-test-home .venv/bin/pytest tests/workflow/deep_analysis/test_diagnostician_score.py -v`
Expected: 4 passed

- [ ] **Step 5: 실제 정답키의 기준선을 기록하는 테스트를 추가한다**

```python
from pathlib import Path

import yaml


def test_the_real_key_baseline_matches_what_the_key_records():
    """기준선이 조용히 바뀌면 관문의 의미가 바뀐다.

    `answer_key.yaml` 이 `baseline_constant_best` 를 스스로 적어두고, 이
    테스트가 계산값과 대조한다. 정답키를 고치면 여기서 실패하고, 그때는
    스펙 §6의 관문(>= constant_best + 1/6)을 다시 계산해야 한다.

    ⚠️ 값을 손으로 박지 않는다 -- 계획 작성 중 4/6 이라고 박았다가 실제
    최선 조합이 5/6 인 것을 놓칠 뻔했다.
    """
    prereg = Path("scripts/diagnostician_backtest")
    key_doc = yaml.safe_load((prereg / "answer_key.yaml").read_text())
    labels = yaml.safe_load((prereg / "labels.yaml").read_text())["labels"]
    computed = constant_best(key_doc["samples"], labels)
    recorded = key_doc["baseline_constant_best"]
    assert abs(computed - recorded) < 1e-9, (
        f"정답키가 적은 기준선 {recorded:.3f} 과 계산값 {computed:.3f} 이 다르다"
    )
```

- [ ] **Step 6: 테스트를 돌려 통과를 확인한다**

Run: `HOME=/tmp/neos-test-home .venv/bin/pytest tests/workflow/deep_analysis/test_diagnostician_score.py -v`
Expected: 5 passed

- [ ] **Step 7: 커밋**

```bash
git add scripts/deep_analysis_diagnostician.py tests/workflow/deep_analysis/test_diagnostician_score.py
git commit -m "feat(deep-analysis): score the diagnostician against the pinned baseline

recall@3 alone would have passed a predictor that reads nothing: four of
the six samples in this window chased one bottleneck at rising
resolution, so a fixed answer of assembly_clamp scores 4/6 -- the number
the gate was originally set to. `constant_best` computes that from the
key itself and a test pins it, so changing the key fails loudly instead
of quietly moving the bar.

Candidates citing an event id that is not in the sample's ledger are
discarded rather than scored, the same rule the report writer already
lives under."
```

---

### Task 4: 진단자 (`render_prompt`, `diagnose`)

**Files:**
- Modify: `scripts/deep_analysis_diagnostician.py`
- Create: `neos/workflow/deep_analysis/prompts/diagnose_bottleneck.md`
- Test: `tests/workflow/deep_analysis/test_diagnostician_diagnose.py`

**Interfaces:**
- Consumes: Task 2의 `build_summary`, Task 1의 `labels.yaml`
- Produces:
  - `render_prompt(summary: dict, labels: Sequence[str]) -> str`
  - `async diagnose(summary, labels, *, model: str, client=None) -> dict`
    반환: `{"candidates": [Candidate, ...], "failure": str | None}`
    `failure`는 `None` 또는 `"unparseable"` / `"truncated"` / `"off_label"`

- [ ] **Step 1: 프롬프트 템플릿을 만든다**

`neos/workflow/deep_analysis/prompts/diagnose_bottleneck.md`:

```markdown
너는 심층분석 하네스의 한 표본을 읽고 **병목**을 지목한다.

주어지는 것은 그 표본의 이벤트 원장 집계와 배달된 리포트뿐이다. 다른 표본,
결정 기록, 이후에 무엇을 고쳤는지는 주어지지 않는다.

## 규칙

1. 아래 **닫힌 라벨 집합**에서만 고른다. 집합 밖의 말을 지어내지 않는다.
2. 최대 **3개**까지 고른다. 확신이 없으면 더 적게 골라도 된다.
3. 각 후보에 **근거 이벤트 id**를 최소 하나 단다. 형식은 `run_id:seq`이며,
   **주어진 요약에 실제로 등장한 것만** 쓴다. 지어낸 id를 단 후보는 폐기된다.
4. 각 후보에 한 문장으로 이유를 적는다.
5. 원인을 가릴 수 없다고 판단하면 `instrumentation`을 고른다 -- 그것도 답이다.

## 라벨 집합

{labels}

## 표본 요약

```json
{summary}
```

## 출력 형식

JSON 객체 하나만 낸다. 다른 텍스트를 붙이지 않는다.

{{"candidates": [{{"label": "<라벨>", "evidence": ["run_id:seq"], "reason": "<한 문장>"}}]}}
```

- [ ] **Step 2: 실패하는 테스트를 쓴다**

```python
import json
from pathlib import Path

import pytest
import yaml

from scripts.deep_analysis_diagnostician import diagnose, render_prompt

LABELS = yaml.safe_load(
    Path("scripts/diagnostician_backtest/labels.yaml").read_text()
)["labels"]


class _FakeClient:
    """응답을 미리 정해두는 가짜 클라이언트. 테스트는 LLM을 부르지 않는다."""

    def __init__(self, text: str):
        self.text = text
        self.prompts: list[str] = []


def test_prompt_carries_the_label_set_and_the_summary():
    prompt = render_prompt({"events": {"claim_verified": 3}}, LABELS)
    assert "assembly_clamp" in prompt
    assert "claim_verified" in prompt


def test_the_prompt_never_carries_the_answer_key():
    """작성자가 정답을 안다는 사실이 프롬프트로 새는 경로를 코드가 막는다."""
    key_text = Path("scripts/diagnostician_backtest/answer_key.yaml").read_text()
    key = yaml.safe_load(key_text)["samples"]
    prompt = render_prompt({"events": {}}, LABELS)
    for sample_id, entry in key.items():
        assert entry["quote"] not in prompt
        assert entry["artifact"] not in prompt
        assert entry["decision"] not in prompt


@pytest.mark.asyncio
async def test_labels_outside_the_closed_set_are_rejected():
    payload = json.dumps({"candidates": [
        {"label": "vibes", "evidence": ["r1:1"], "reason": "느낌"}
    ]})
    result = await diagnose({"events": {}}, LABELS, model="fake",
                            client=_FakeClient(payload))
    assert result["candidates"] == []
    assert result["failure"] == "off_label"


@pytest.mark.asyncio
async def test_more_than_three_candidates_are_truncated_to_three():
    payload = json.dumps({"candidates": [
        {"label": label, "evidence": ["r1:1"], "reason": "x"}
        for label in LABELS[:5]
    ]})
    result = await diagnose({"events": {}}, LABELS, model="fake",
                            client=_FakeClient(payload))
    assert len(result["candidates"]) == 3
```

- [ ] **Step 3: 테스트를 돌려 실패를 확인한다**

Run: `HOME=/tmp/neos-test-home .venv/bin/pytest tests/workflow/deep_analysis/test_diagnostician_diagnose.py -v`
Expected: FAIL — `ImportError: cannot import name 'diagnose'`

- [ ] **Step 4: 진단자를 구현한다**

```python
import json
from pathlib import Path

_PROMPT = Path(
    "neos/workflow/deep_analysis/prompts/diagnose_bottleneck.md"
)
_MAX_CANDIDATES = 3


def render_prompt(summary: dict, labels) -> str:
    template = _PROMPT.read_text(encoding="utf-8")
    return template.replace(
        "{labels}", "\n".join(f"- {label}" for label in labels)
    ).replace("{summary}", json.dumps(summary, ensure_ascii=False, indent=2))


async def diagnose(summary: dict, labels, *, model: str, client=None) -> dict:
    """표본 요약 하나로 병목 후보를 낸다. LLM 호출 1회.

    `retries=0`이다 -- 파싱될 때까지 다시 묻는 것은 점수를 부풀린다(스펙 §8).
    실패는 삼키지 않고 `failure`에 사유를 남긴다.
    """
    from neos.workflow.deep_analysis.llm import (
        JSONParseError,
        LLMProviderError,
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
    except JSONParseError:
        return {"candidates": [], "failure": "unparseable"}
    except LLMProviderError:
        return {"candidates": [], "failure": "truncated"}

    allowed = set(labels)
    candidates, off_label = [], False
    for raw in data.get("candidates", []):
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
        failure = "off_label" if off_label else "unparseable"
    return {"candidates": truncated, "failure": failure,
            "output_tokens": getattr(response, "output_tokens", None)}
```

- [ ] **Step 5: 테스트를 돌려 통과를 확인한다**

Run: `HOME=/tmp/neos-test-home .venv/bin/pytest tests/workflow/deep_analysis/test_diagnostician_diagnose.py -v`
Expected: 4 passed

> 가짜 클라이언트가 `call_json`의 클라이언트 계약과 맞지 않으면, 그 계약을
> `neos/workflow/deep_analysis/llm.py`에서 확인해 `_FakeClient`를 맞춘다.
> 기존 테스트의 가짜 클라이언트를 찾으려면:
> `rg -n "client=" tests/workflow/deep_analysis | head`

- [ ] **Step 6: 커밋**

```bash
git add scripts/deep_analysis_diagnostician.py \
        neos/workflow/deep_analysis/prompts/diagnose_bottleneck.md \
        tests/workflow/deep_analysis/test_diagnostician_diagnose.py
git commit -m "feat(deep-analysis): ask the model for bottleneck labels, once

The diagnostician picks from a closed set and cites event ids, so its
output can be scored without reading prose. It gets one call with
retries=0: asking again until the JSON parses would quietly turn a
failure into a score.

A test renders the prompt and asserts no string from the answer key
appears in it -- the author of this backtest has read the answers, and
that is the path by which they would leak."
```

---

### Task 5: CLI와 영수증

**Files:**
- Modify: `scripts/deep_analysis_diagnostician.py`
- Test: `tests/workflow/deep_analysis/test_diagnostician_cli.py`

**Interfaces:**
- Consumes: Task 1~4 전부
- Produces:
  - `load_sample(sample_id, *, session) -> tuple[list[EventRow], str, dict]`
  - `write_artifacts(root: Path, *, manifest, inputs, outputs, score) -> Path`
  - `main()` — `python scripts/deep_analysis_diagnostician.py --repeats 3`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
import json
from pathlib import Path

from scripts.deep_analysis_diagnostician import write_artifacts


def test_artifacts_keep_the_input_the_diagnostician_actually_saw(tmp_path):
    """빗나갔을 때 '그 신호가 요약에 있었나'를 사람이 확인해야 한다.

    입력을 남기지 않으면 그 질문에 영원히 답할 수 없다 (스펙 §7).
    """
    out = write_artifacts(
        tmp_path,
        manifest={"model": "claude-opus-5", "repeats": 3},
        inputs={"11": {"events": {"claim_verified": 3}}},
        outputs={"11": [{"candidates": [], "failure": None}]},
        score={"mean_recall": 0.5, "constant_best": 4 / 6},
    )
    assert (out / "manifest.json").exists()
    assert json.loads((out / "inputs/11.json").read_text())["events"][
        "claim_verified"
    ] == 3
    assert json.loads((out / "score.json").read_text())["constant_best"] > 0


def test_manifest_records_what_would_change_the_score(tmp_path):
    out = write_artifacts(
        tmp_path,
        manifest={"model": "claude-opus-5", "repeats": 3,
                  "answer_key_sha": "abc123", "git_tree_clean": True},
        inputs={}, outputs={}, score={},
    )
    manifest = json.loads((out / "manifest.json").read_text())
    for field in ("model", "repeats", "answer_key_sha", "git_tree_clean"):
        assert field in manifest
```

- [ ] **Step 2: 테스트를 돌려 실패를 확인한다**

Run: `HOME=/tmp/neos-test-home .venv/bin/pytest tests/workflow/deep_analysis/test_diagnostician_cli.py -v`
Expected: FAIL — `ImportError: cannot import name 'write_artifacts'`

- [ ] **Step 3: 산출물 기록을 구현한다**

```python
from datetime import UTC, datetime


def write_artifacts(root: Path, *, manifest, inputs, outputs, score) -> Path:
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
```

- [ ] **Step 4: 테스트를 돌려 통과를 확인한다**

Run: `HOME=/tmp/neos-test-home .venv/bin/pytest tests/workflow/deep_analysis/test_diagnostician_cli.py -v`
Expected: 2 passed

- [ ] **Step 5: `main()`과 원장 조회를 붙인다**

`load_sample`은 `answer_key.yaml`의 `artifact` 타임스탬프로
`artifacts/deep-analysis-funnel/<ts>/manifest.json`을 읽어 run_id를 얻고,
`deep_analysis_events`에서 그 run들의 행을 가져온다. DB URL은 `.env`의
`DATABASE_URL`을 쓴다 (§10.4의 검증 명령과 같은 경로).

```python
import argparse
import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

ARTIFACT_ROOT = Path("artifacts/deep-analysis-funnel")
BACKTEST_ROOT = Path("artifacts/diagnostician-backtest")


async def load_sample(sample_id: str, entry: dict, *, connection):
    sample_dir = ARTIFACT_ROOT / entry["artifact"]
    manifest = json.loads((sample_dir / "manifest.json").read_text())
    run_ids = [r["run_id"] for r in manifest.get("dev_runs", [])]
    if manifest.get("default_run"):
        run_ids.append(manifest["default_run"]["run_id"])

    clauses = " or ".join(f"run_id like :p{i}" for i in range(len(run_ids)))
    rows = (
        await connection.execute(
            text(
                "select run_id, seq, kind, payload from deep_analysis_events "
                f"where {clauses} order by run_id, seq"
            ),
            {f"p{i}": f"{rid}%" for i, rid in enumerate(run_ids)},
        )
    ).all()
    report = (sample_dir / "report.md").read_text(encoding="utf-8")
    return [tuple(r) for r in rows], report, manifest.get(
        "config_fingerprint", {}
    )
```

- [ ] **Step 6: 스크립트가 임포트되는지 확인한다**

Run: `PYTHONPATH=. .venv/bin/python -c "import scripts.deep_analysis_diagnostician as m; print(m.main)"`
Expected: 함수 객체가 출력된다

- [ ] **Step 7: 커밋**

```bash
git add scripts/deep_analysis_diagnostician.py tests/workflow/deep_analysis/test_diagnostician_cli.py
git commit -m "feat(deep-analysis): run the backtest and keep what it saw

The run writes the summary handed to each sample alongside the answer,
because the first question after a miss is whether the signal was in the
input at all, and that question is unanswerable later if only the answer
was kept.

The manifest records the model, the repeat count, the answer key's hash
and whether the tree was clean -- the four things that move the score
without any code changing."
```

---

### Task 6: 백테스트 실행과 판정

⚠️ **이 태스크는 실제 LLM 호출 18회를 쓴다** (표본 6 × 반복 3). 라이브 표본이
아니므로 §10.2에 걸리지 않지만, **실행 전에 사람의 승인을 받는다.**

**Files:**
- Create: `artifacts/diagnostician-backtest/<UTC>/` (gitignore)
- Modify: `docs/DEEP_ANALYSIS_HARNESS_ROADMAP.md` §13.3의 F1 행
- Modify: `neos/workflow/deep_analysis/DECISIONS.md` (판정 기록)

**Interfaces:**
- Consumes: Task 1~5 전부
- Produces: F1 관문의 판정

- [ ] **Step 1: 사전 게이트를 돌린다**

Run: `HOME=/tmp/neos-test-home .venv/bin/python -m pytest -q`
Expected: 실패 0건. 수치를 영수증에 적는다.

- [ ] **Step 2: 트리가 깨끗한지 확인한다**

Run: `git status --short`
Expected: 출력 없음. 깨끗하지 않으면 커밋하거나 스태시한 뒤 진행한다.

- [ ] **Step 3: 백테스트를 돌린다**

Run: `PYTHONPATH=. .venv/bin/python scripts/deep_analysis_diagnostician.py --repeats 3`
Expected: `artifacts/diagnostician-backtest/<UTC>/`가 생기고 `score.json`에
`mean_recall`과 `constant_best`가 들어 있다.

- [ ] **Step 4: 관문을 판정한다**

통과 조건은 **Task 1 에서 확정한 값**을 쓴다 -- 초안 정답키에서는
`constant_best` 가 83.3% 라 스펙 §6 의 `+1/6` 을 그대로 쓰면 100% 가 된다.
Task 1 의 상자에 적힌 후보 (a)/(b) 중 무엇을 택했는지 여기서 인용한다.

세 갈래로 나눠 읽는다:
- `truth` 적중 → 진단자가 작동한다
- `contemporaneous`만 적중(`reproduced_contemporaneous`) → **부족한 것은 계측**
- 둘 다 빗나감 → `signal_map.yaml`에서 그 라벨의 필드를 찾아 요약에서 확인한다.
  비어 있거나 평평하면 **입력에 없었던 것**이고 진단자 탓이 아니다.

- [ ] **Step 5: DECISIONS에 판정을 기록한다**

D79로 적는다. 반드시 포함할 것: 아티팩트 경로 · 모델 id · 사전 게이트 수치 ·
`mean_recall` · `constant_best` · 표본별 세 갈래 분류 · 신호 지도 판정 ·
**빗나간 표본에서 요약에 그 신호가 있었는지**.

- [ ] **Step 6: 로드맵 §13.3의 F1 행을 실측으로 갱신한다**

- [ ] **Step 7: 커밋**

```bash
git add docs/DEEP_ANALYSIS_HARNESS_ROADMAP.md neos/workflow/deep_analysis/DECISIONS.md
git commit -m "docs(deep-analysis): judge F1 -- the diagnostician backtest

<실측 수치로 채운다: mean_recall vs constant_best, 세 갈래 분류,
 그리고 빗나간 표본이 계측 부족이었는지 에이전트 부족이었는지>"
```

---

## 자체 검토

**스펙 커버리지:**

| 스펙 절 | 태스크 |
|---|---|
| §2 오염 방어 (스크립트·표본 무지·누출 금지) | Task 2 Step 5, Task 4 Step 2 |
| §3 구성 요소·사전 등록 우선 | Task 1 |
| §4 고정 스키마 집계 | Task 2 |
| §5 라벨·기준선·근거 id 무결성·반복 3회 | Task 1, Task 3, Task 5 |
| §6 두 칸 정답키·세 갈래·신호 지도·관문 | Task 1, Task 3, Task 6 |
| §7 산출물·영수증 | Task 5 |
| §8 테스트 전략·실패 삼키지 않기 | Task 2~4 |

**미해결로 남기는 것:** 스펙 §10의 네 위험(라벨 입도·정답 개수·당시의 사람
4/6·표본 6개)은 첫 실행이 답한다. Task 6 Step 5가 그것을 기록한다.
