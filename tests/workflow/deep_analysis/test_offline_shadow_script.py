"""J3 스크립트의 보고서 모양 (로드맵 J3).

스크립트 전체는 DB·샌드박스·LLM 을 요구하지만, **보고서가 자기가 무엇인지
말하는가**는 그것들 없이 고정할 수 있고 고정해야 한다. 이 섀도의 brief 는
지금 원장 상태로 조립되므로 "그때 그 실행" 의 재현이 아니다 -- 보고서가
그 말을 하지 않으면 읽는 쪽이 앞엣것으로 읽는다.
"""

from __future__ import annotations

import importlib.util
import pathlib

import pytest

pytestmark = pytest.mark.no_db

_SCRIPT = (
    pathlib.Path(__file__).resolve().parents[3]
    / "scripts"
    / "deep_analysis_offline_shadow.py"
)


def _module():
    spec = importlib.util.spec_from_file_location("_offline_shadow", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_replay_is_the_default_mode() -> None:
    """녹음은 **진짜 LLM 호출을 하고 돈을 쓴다.** 실수로 들어가면 안 된다."""
    args = _module()._parse_args(
        ["--run-id", "r", "--question-id", "q", "--cassette", "c.json"]
    )

    assert args.mode == "replay"


def test_split_is_not_an_effort_the_script_offers() -> None:
    """분할은 지시가 아니다 -- `build_assignment` 가 받지 않는다."""
    module = _module()

    with pytest.raises(SystemExit):
        module._parse_args(
            [
                "--run-id", "r", "--question-id", "q",
                "--cassette", "c.json", "--effort", "split",
            ]
        )


def test_the_report_says_what_it_is_not(capsys) -> None:
    """brief 가 지금 원장 상태로 조립된다는 사실이 보고서에 있어야 한다."""
    module = _module()

    module._print(
        {
            "run_id": "run00001",
            "question_id": "q_1",
            "asks": "이 run 이 쌓은 지식을 주면 조사 워커는 무엇을 제안하는가 "
            "(그 패스의 brief 를 되짚은 것이 아니다)",
            "shared": ["A"],
            "only_recorded": [],
            "only_shadow": [],
            "missed_urls": [],
            "evidence_was_complete": True,
        }
    )

    printed = capsys.readouterr().out
    assert "되짚은 것이 아니다" in printed
    assert "판단 차이" in printed


def test_an_incomplete_archive_is_shouted_not_whispered(capsys) -> None:
    """섀도가 적은 증거로 돌았다면 그것을 워커 탓으로 읽지 말라고 말해야 한다."""
    module = _module()

    module._print(
        {
            "run_id": "run00001",
            "question_id": "q_1",
            "asks": "...",
            "shared": [],
            "only_recorded": [{"text": "A", "status": "verified"}],
            "only_shadow": [],
            "missed_urls": ["https://a", "https://b"],
            "evidence_was_complete": False,
        }
    )

    printed = capsys.readouterr().out
    assert "2개" in printed
    assert "워커 탓으로 읽지 말 것" in printed
