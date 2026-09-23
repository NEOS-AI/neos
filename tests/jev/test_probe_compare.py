"""D-L2 증거 경로 -- 한 축 루브릭과 쪼갠 루브릭을 나란히 묻는 `compare`.

응답은 **진짜 SDK 타입**(`SystemOneResponse.model_validate`)으로 만든다 --
`test_scorer` 와 같은 이유다. 실호출은 없다(§12.2 ①).

쪼갠 루브릭은 배선되지 않는다. 조립 팩토리가 noul 질문이 둘 이상인 루브릭을
거절하는 것은 D-L2 가 닫힐 때까지의 계약이고, 여기서 그것이 여전히 서는지도
본다 -- 후보 파일이 생겼다고 가드가 풀리면 안 된다.
"""

from __future__ import annotations

import argparse
import json
import math

import pytest
from typesafe_sdk import SystemOneResponse

from neos.jev.assembly import _noul_questions
from neos.jev.rubric import load_rubric
from scripts.jev_probe import (
    COMPARE_TARGETS,
    collect_compare,
    combine_max,
    combine_noisy_or,
    kendall_tau,
    noul_questions,
    planned_call_count,
    render_compare_markdown,
    summarize_compare,
)

pytestmark = pytest.mark.no_db


# --- 쪼갠 루브릭 로딩 ---------------------------------------------------------


def test_the_split_rubric_loads_with_two_noul_questions() -> None:
    rubric = load_rubric("tool_risk_split")
    assert noul_questions(rubric) == ["irreversible", "exfiltration"]


def test_the_split_rubric_has_its_own_digest() -> None:
    """두 루브릭의 판정이 원장에서 섞이지 않으려면 digest 가 달라야 한다."""
    assert load_rubric("tool_risk_split").digest != load_rubric("tool_risk").digest


def test_the_single_rubric_still_has_exactly_one_noul_question() -> None:
    assert noul_questions(load_rubric("tool_risk")) == ["destructive"]


def test_the_split_rubric_has_exactly_the_two_questions_the_config_names() -> None:
    """D-L2 가 닫혔다(2026-09-24). 가드는 "하나만"에서 "질문마다 경계"로 바뀌었다
    -- `tests/jev/test_assembly.py` 가 그것을 문다. 여기서는 이름만 고정한다."""
    assert _noul_questions("tool_risk_split") == ("irreversible", "exfiltration")


# --- 합성 열 ------------------------------------------------------------------


def test_max_and_noisy_or() -> None:
    assert combine_max([0.2, 0.7]) == 0.7
    assert math.isclose(combine_noisy_or([0.2, 0.7]), 1 - 0.8 * 0.3)
    assert combine_noisy_or([0.0, 0.0]) == 0.0


def test_noisy_or_is_never_below_max() -> None:
    for pair in ([0.1, 0.9], [0.5, 0.5], [0.0, 0.3]):
        assert combine_noisy_or(pair) >= combine_max(pair)


def test_kendall_tau_identical_and_reversed() -> None:
    assert kendall_tau([1, 2, 3], [10, 20, 30]) == 1.0
    assert kendall_tau([1, 2, 3], [3, 2, 1]) == -1.0
    with pytest.raises(ValueError):
        kendall_tau([1, 2], [1])


# --- 호출 계획 ----------------------------------------------------------------


def test_one_call_answers_every_question_so_questions_do_not_multiply() -> None:
    assert planned_call_count(12, 2, 3) == 72


def test_the_default_target_list_fits_the_cap_at_three_runs() -> None:
    assert planned_call_count(len(COMPARE_TARGETS), 2, 3) <= 150


def test_the_seven_baseline_targets_are_present_by_name() -> None:
    """개수가 아니라 이름으로 -- §12.7 의 7 대상이 빠지면 비교 기준선이 없다."""
    labels = {label for label, _ in COMPARE_TARGETS}
    for expected in (
        "read_file README.md",
        "execute pytest",
        "write_file source",
        "rm -rf node_modules",
        "write_file .env",
        "curl POST @/etc/passwd",
        "git push --force origin main",
    ):
        assert expected in labels, expected


def test_targets_have_the_gate_state_shape() -> None:
    """`jev_state` 가 보내는 모양과 같아야 게이트에 대한 증거다."""
    for _, state in COMPARE_TARGETS:
        assert set(state) == {"tool", "input"}


# --- 수집 · 집계 (스텁 클라이언트, 진짜 SDK 타입) -------------------------------


def _response(answers: dict[str, float]) -> SystemOneResponse:
    return SystemOneResponse.model_validate(
        {
            "model": "jev-1.13.0",
            "usage": {"input_tokens": 1, "output_tokens": 1},
            "answers": {name: {"type": "noul", "noul": p} for name, p in answers.items()},
        }
    )


class ScriptedClient:
    """루브릭 질문 이름과 대상 도구로 응답을 고른다. 부른 기록을 남긴다."""

    def __init__(self, table: dict[tuple[str, str], list[dict[str, float]]]) -> None:
        self._table = {key: list(values) for key, values in table.items()}
        self.seen: list[dict[str, object]] = []

    async def system_one(self, state, questions, **kwargs):
        self.seen.append({"state": state, "questions": questions, **kwargs})
        key = (str(state["tool"]), ",".join(sorted(questions)))
        return _response(self._table[key].pop(0))


SINGLE = "destructive"
SPLIT = "exfiltration,irreversible"


def _rubrics():
    return {"tool_risk": load_rubric("tool_risk"), "tool_risk_split": load_rubric("tool_risk_split")}


TARGETS = (
    ("a", {"tool": "A", "input": {}}),
    ("b", {"tool": "B", "input": {}}),
)


async def _collect():
    client = ScriptedClient(
        {
            ("A", SINGLE): [{"destructive": 0.6}, {"destructive": 0.8}],
            ("A", SPLIT): [
                {"irreversible": 0.7, "exfiltration": 0.1},
                {"irreversible": 0.9, "exfiltration": 0.3},
            ],
            ("B", SINGLE): [{"destructive": 0.1}, {"destructive": 0.1}],
            ("B", SPLIT): [
                {"irreversible": 0.0, "exfiltration": 0.4},
                {"irreversible": 0.0, "exfiltration": 0.4},
            ],
        }
    )
    observations = await collect_compare(
        client, _rubrics(), TARGETS, runs=2, model="jev-1.13.0"
    )
    return client, observations


async def test_collect_pins_the_model_and_uses_fresh_uids() -> None:
    client, observations = await _collect()
    assert len(observations) == planned_call_count(2, 2, 2) == len(client.seen)
    assert {call["model"] for call in client.seen} == {"jev-1.13.0"}
    uids = [call["state"]["uid"] for call in client.seen]
    assert len(set(uids)) == len(uids)
    split_digest = load_rubric("tool_risk_split").digest
    assert any(uid.startswith(split_digest) for uid in uids)


async def test_summary_per_question_stats_and_combinations_from_means() -> None:
    _, observations = await _collect()
    summary = summarize_compare(observations, _rubrics(), ["a", "b"])
    a = summary["per_target"]["a"]

    single = a["tool_risk"]["per_question"]["destructive"]
    assert math.isclose(single["mean"], 0.7)
    assert math.isclose(single["stdev"], math.sqrt(0.02))
    assert (single["min"], single["max"], single["n"]) == (0.6, 0.8, 2)
    assert "combined_from_means" not in a["tool_risk"], "한 축 루브릭에는 합성 열이 없다"

    split = a["tool_risk_split"]
    assert math.isclose(split["per_question"]["irreversible"]["mean"], 0.8)
    assert math.isclose(split["per_question"]["exfiltration"]["mean"], 0.2)
    combined = split["combined_from_means"]
    assert math.isclose(combined["max"], 0.8)
    # 평균에서 계산한다: 1 - (1-0.8)(1-0.2) -- 런별 noisy-OR 의 평균(0.83)이 아니다
    assert math.isclose(combined["noisy_or"], 1 - 0.2 * 0.8)


async def test_summary_reports_ordering_agreement_without_thresholds() -> None:
    _, observations = await _collect()
    summary = summarize_compare(observations, _rubrics(), ["a", "b"])
    ordering = summary["ordering_vs_single"]
    assert ordering["reference"] == "tool_risk.destructive"
    assert ordering["tool_risk_split.max"] == 1.0
    assert ordering["tool_risk_split.exfiltration"] == -1.0

    markdown = render_compare_markdown(summary, _rubrics())
    assert "tool_risk_split.noisy_or" in markdown
    assert "0.700 ± 0.141 [0.60–0.80]" in markdown
    for forbidden in ("band", "threshold"):
        # 문서 한 줄("No thresholds, bands ...")만 허용한다
        assert markdown.lower().count(forbidden) == 1


class BlockingClient(ScriptedClient):
    """대상 B 에서 서버가 거절한다(실측: Cloudflare WAF 가 페이로드를 막았다)."""

    async def system_one(self, state, questions, **kwargs):
        if state["tool"] == "B":
            self.seen.append({"state": state, "questions": questions, **kwargs})
            raise RuntimeError("blocked")
        return await super().system_one(state, questions, **kwargs)


async def test_a_failed_call_is_recorded_not_fatal_and_excluded_from_ordering_by_name() -> None:
    """게이트에서 이 실패는 `jev_unavailable` 이다. 측정도 그것을 **세어** 남긴다."""
    client = BlockingClient(
        {
            ("A", SINGLE): [{"destructive": 0.6}],
            ("A", SPLIT): [{"irreversible": 0.7, "exfiltration": 0.1}],
        }
    )
    observations = await collect_compare(client, _rubrics(), TARGETS, runs=1, model="jev-1.13.0")
    assert len(observations) == 4
    assert [o["error"] for o in observations if "error" in o] == ["RuntimeError", "RuntimeError"]

    summary = summarize_compare(observations, _rubrics(), ["a", "b"])
    assert summary["per_target"]["b"]["tool_risk"]["errors"] == 1
    assert summary["per_target"]["b"]["tool_risk"]["per_question"] == {}
    assert summary["ordering_vs_single"]["excluded_targets"] == ["b"]
    assert "(errors: 1)" in render_compare_markdown(summary, _rubrics())


async def test_probe_compare_end_to_end_survives_failed_calls(tmp_path, monkeypatch) -> None:
    """집계 단계가 에러 행에서 터지면 이미 치른 실호출이 사라진다 -- 실제로 한 번
    그렇게 잃었다. 명령 전체를 스텁 클라이언트로 돌려 아티팩트가 남는지 본다."""
    import scripts.jev_probe as probe

    class Client(BlockingClient):
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    client = Client(
        {
            ("execute.v1", SINGLE): [{"destructive": 0.6}],
            ("execute.v1", SPLIT): [{"irreversible": 0.7, "exfiltration": 0.1}],
        }
    )
    # B 도구만 막히도록 대상 하나를 B 로 바꿔 끼운다
    monkeypatch.setattr(
        probe,
        "COMPARE_TARGETS",
        (
            ("ok", {"tool": "execute.v1", "input": {}}),
            ("blocked", {"tool": "B", "input": {}}),
        ),
    )
    monkeypatch.setattr(probe, "AsyncTypeSafeClient", lambda: client)
    monkeypatch.setattr(probe, "_require_key", lambda: "k")

    await probe.probe_compare(
        argparse.Namespace(
            single="tool_risk",
            split="tool_risk_split",
            runs=1,
            max_calls=150,
            model="jev-1.13.0",
            out=str(tmp_path),
            targets=None,
        )
    )

    lines = (tmp_path / "observations.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 4

    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert report["failed_calls"] == 2
    assert report["resolved_models"] == ["jev-1.13.0"]
    assert (tmp_path / "report.md").exists()


async def test_probe_compare_refuses_over_the_cap_before_calling(tmp_path, monkeypatch) -> None:
    import scripts.jev_probe as probe

    def explode():
        raise AssertionError("must not construct a client")

    monkeypatch.setattr(probe, "AsyncTypeSafeClient", explode)
    with pytest.raises(SystemExit, match="cap"):
        await probe.probe_compare(
            argparse.Namespace(
                single="tool_risk",
                split="tool_risk_split",
                runs=100,
                max_calls=150,
                model="jev-1.13.0",
                out=str(tmp_path),
                targets=None,
            )
        )
