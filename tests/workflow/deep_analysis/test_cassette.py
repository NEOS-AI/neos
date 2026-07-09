import json

import pytest

from neos.workflow.deep_analysis.cassette import Cassette


pytestmark = pytest.mark.no_db


@pytest.mark.asyncio
async def test_record_then_replay_does_not_call_producer(tmp_path):
    path = tmp_path / "cassette.json"
    calls = {"count": 0}

    async def producer():
        calls["count"] += 1
        return {"value": 42}

    record = Cassette(path, "record")
    assert await record.remember("llm", {"prompt": "x"}, producer) == {
        "value": 42
    }
    record.save()

    replay = Cassette(path, "replay")

    async def must_not_run():
        raise AssertionError("producer ran during replay")

    assert await replay.remember(
        "llm",
        {"prompt": "x"},
        must_not_run,
    ) == {"value": 42}
    assert calls["count"] == 1


def test_key_is_stable_for_equivalent_payload_order(tmp_path):
    cassette = Cassette(tmp_path / "cassette.json", "off")

    assert cassette.key("fetch", {"url": "x", "k": 3}) == cassette.key(
        "fetch",
        {"k": 3, "url": "x"},
    )


@pytest.mark.asyncio
async def test_replay_miss_is_explicit(tmp_path):
    path = tmp_path / "cassette.json"
    path.write_text(json.dumps({}), encoding="utf-8")
    cassette = Cassette(path, "replay")

    async def producer():
        return {}

    with pytest.raises(KeyError, match="cassette miss"):
        await cassette.remember("search", {"query": "x"}, producer)
