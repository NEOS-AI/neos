"""레코드는 만들어지는 순간 디스크에 남는다 (D1b).

기존 구조에서 영속화는 `graph.py` 의 `_auto_save_dataset()` 한 곳에서만
일어났다. Celery 워커와 deep-analysis job 서비스는 그 지점을 지나가지 않는
별도 프로세스이므로, 거기서 만들어진 레코드는 프로세스와 함께 사라졌다
(로드맵 §11.1 장애물 ②).

배출구를 더 만드는 대신 없앤다. `add_record` 가 곧 영속화이므로 어느
프로세스에서 돌든 상관이 없고, 새 진입점이 생겨도 누군가 flush 를 기억할
필요가 없다 -- 잊으면 조용히 사라지는 그 실패 모드 자체를 제거한다.
"""

import json
import os
from pathlib import Path

import pytest

from neos.dataset.models import LLMCallRecord
from neos.dataset.record_sink import RecordSink


pytestmark = pytest.mark.no_db


def _record(**kwargs) -> LLMCallRecord:
    defaults = dict(
        session_id="s1",
        user_id="u1",
        workflow_step="worker_analysis",
        provider="anthropic",
        model="claude-sonnet-5",
        output_text="답",
    )
    return LLMCallRecord(**{**defaults, **kwargs})


def test_a_record_is_on_disk_before_any_flush(tmp_path: Path):
    """flush 를 부르지 않는다. 그것이 요점이다."""
    sink = RecordSink(tmp_path)

    sink.append(_record())

    lines = [
        line
        for path in tmp_path.rglob("*.jsonl")
        for line in path.read_text().splitlines()
    ]
    assert len(lines) == 1
    assert json.loads(lines[0])["model"] == "claude-sonnet-5"


def test_each_process_owns_its_file(tmp_path: Path):
    """워커가 여럿이어도 잠금이 필요 없다 -- 파일이 겹치지 않는다."""
    first = RecordSink(tmp_path)
    second = RecordSink(tmp_path)

    first.append(_record(session_id="a"))
    second.append(_record(session_id="b"))

    assert first.path != second.path
    assert str(os.getpid()) in first.path.name


def test_appending_does_not_rewrite_earlier_lines(tmp_path: Path):
    """기존 `save_jsonl` 은 매번 전량을 다시 썼다. append 는 누적한다."""
    sink = RecordSink(tmp_path)

    sink.append(_record(session_id="a"))
    sink.append(_record(session_id="b"))

    sessions = [
        json.loads(line)["session_id"]
        for line in sink.path.read_text().splitlines()
    ]
    assert sessions == ["a", "b"]


def test_a_broken_sink_never_takes_down_the_llm_call(tmp_path: Path):
    """계측이 본업을 막으면 안 된다.

    수집 실패는 데이터 손실이지만, 예외를 올려보내면 그 LLM 호출 자체가
    죽는다 -- 훨씬 나쁘다.
    """
    blocked = tmp_path / "file-where-a-directory-should-be"
    blocked.write_text("")
    sink = RecordSink(blocked)

    sink.append(_record())  # 던지지 않는다


def test_records_written_by_another_process_can_be_read_back(tmp_path: Path):
    """워커가 남긴 것을 나중에 다른 프로세스가 모아야 쓸모가 있다."""
    first = RecordSink(tmp_path)
    second = RecordSink(tmp_path)
    first.append(_record(session_id="a"))
    second.append(_record(session_id="b"))

    recovered = RecordSink.read_all(tmp_path)

    assert sorted(r.session_id for r in recovered) == ["a", "b"]
    assert all(isinstance(r, LLMCallRecord) for r in recovered)


def test_a_corrupt_line_does_not_hide_the_good_ones(tmp_path: Path):
    """프로세스가 쓰다 죽으면 마지막 줄이 잘려 있을 수 있다."""
    sink = RecordSink(tmp_path)
    sink.append(_record(session_id="a"))
    with sink.path.open("a", encoding="utf-8") as handle:
        handle.write('{"session_id": "truncat')

    recovered = RecordSink.read_all(tmp_path)

    assert [r.session_id for r in recovered] == ["a"]


def test_a_separate_process_leaves_its_records_behind(tmp_path: Path):
    """D1b 의 완료 기준 그 자체.

    Celery 워커와 deep-analysis job 서비스는 `graph.py` 의 flush 지점을
    지나가지 않는 **별도 프로세스**다. 그래서 실제로 프로세스를 하나 띄워
    레코드를 남기고 죽인 뒤, 이쪽에서 읽히는지를 본다 -- 모킹으로는 이
    성질을 증명할 수 없다.
    """
    import subprocess
    import sys

    program = (
        "import sys; sys.path.insert(0, %r)\n"
        "from neos.dataset.record_sink import RecordSink\n"
        "from neos.dataset.models import LLMCallRecord\n"
        "RecordSink(%r).append(LLMCallRecord(session_id='from-worker'))\n"
        % (str(Path.cwd()), str(tmp_path))
    )
    completed = subprocess.run(
        [sys.executable, "-c", program], capture_output=True, text=True
    )
    assert completed.returncode == 0, completed.stderr

    recovered = RecordSink.read_all(tmp_path)

    assert [r.session_id for r in recovered] == ["from-worker"]


def test_the_collector_persists_without_anyone_calling_a_flush(monkeypatch, tmp_path: Path):
    """배선 확인 -- `add_record` 가 곧 영속화다.

    `_auto_save_dataset()` 도, 어떤 teardown 도 부르지 않는다.
    """
    from neos.dataset.collector import LLMCallCollector

    collector = LLMCallCollector()
    monkeypatch.setattr(collector, "_sink", RecordSink(tmp_path))

    collector.add_record(_record(session_id="no-flush"))

    assert [r.session_id for r in RecordSink.read_all(tmp_path)] == ["no-flush"]
