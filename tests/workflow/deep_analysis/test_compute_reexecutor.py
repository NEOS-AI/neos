"""샌드박스에서 계산을 다시 돌린다 (계약 §5 · §7).

여기는 **가짜가 아니다.** `test_computed_claim_grader.py` 가 규칙을 가짜
재실행기로 고정하는 동안, 이 파일은 그 가짜가 흉내 내던 것을 실제로 한다 --
메모리 샌드박스에서 진짜 파이썬을 돌리고 진짜 stdout 을 해시한다. 규칙과
실행을 나눈 이유는 규칙이 샌드박스 없이도 전부 검사 가능하기 때문이고,
그렇다고 실행을 검사하지 않으면 **한도가 실제로 걸리는지**를 아무도 모른다.

## 실행마다 새 샌드박스인 이유

두 번 돌려 digest 를 비교하는 것이 재현성 검사의 전부다(§5). 그런데 같은
샌드박스에서 두 번 돌리면 첫 실행이 남긴 파일을 둘째가 본다 -- 상태를 쌓는
스크립트는 그래서 **서로 다른 답**을 내고, 채점기는 멀쩡한 계산을
`E_COMPUTE_NONDETERMINISTIC` 로 기각한다. 반대로 첫 실행이 결과를 캐시에
써 두면 둘째가 그것을 읽어 **비결정적인 계산이 결정론적으로 보인다.** 둘 다
판정을 뒤집으므로 격리는 취향이 아니라 정확성이다.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from neos.coding.sandbox.memory import MemorySandboxProvider
from neos.workflow.deep_analysis.models import ComputedEvidence

pytestmark = pytest.mark.no_db

SCRIPT_REF = "f" * 64
INPUT_REF = "a" * 64


@dataclass
class _Blob:
    raw_text: str
    http_status: int = 200


class _FakeLedger:
    """blob 저장소만. 재실행기는 원장을 **읽기만** 한다."""

    def __init__(self, blobs: dict[str, str]) -> None:
        self._blobs = {ref: _Blob(text) for ref, text in blobs.items()}

    async def get_blob(self, content_hash: str):
        return self._blobs.get(content_hash)


class _SpyProvider:
    """만든 샌드박스와 부순 샌드박스를 센다.

    "finally 에서 부순다" 는 호출 기록으로만 확인할 수 있다 -- 부수지 않아도
    테스트는 초록이고, 새는 것은 프로덕션에서만 보인다.
    """

    def __init__(self, inner) -> None:
        self._inner = inner
        self.created: list[str] = []
        self.destroyed: list[str] = []

    async def create(self, **kwargs):
        sandbox = await self._inner.create(**kwargs)
        self.created.append(sandbox.sandbox_id)
        return sandbox

    async def open_session(self, sandbox_id: str):
        return await self._inner.open_session(sandbox_id)

    async def destroy(self, sandbox_id: str) -> None:
        self.destroyed.append(sandbox_id)
        await self._inner.destroy(sandbox_id)


def _provider(tmp_path: Path) -> _SpyProvider:
    return _SpyProvider(MemorySandboxProvider(root=tmp_path / "reexec"))


def _reexecutor(ledger, provider, **overrides):
    from neos.workflow.deep_analysis.reexecutor import SandboxReexecutor

    limits: dict[str, Any] = {
        "cpu_sec": 10.0,
        "memory_mb": 512,
        "stdout_bytes": 1_048_576,
    }
    limits.update(overrides)
    return SandboxReexecutor(ledger, provider, **limits)


def _computation(**overrides) -> ComputedEvidence:
    values: dict[str, Any] = {
        "script_ref": SCRIPT_REF,
        "inputs": [],
        "premises": ["c1"],
        "runtime": {"profile": "research-offline-v1", "image_digest": "sha256:x"},
        "output_digest": "",
        "claimed_value": "",
    }
    values.update(overrides)
    return ComputedEvidence(**values)


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---- 실행 --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_script_runs_and_its_output_is_hashed(tmp_path) -> None:
    ledger = _FakeLedger({SCRIPT_REF: "print(42.5)"})
    provider = _provider(tmp_path)

    run = await _reexecutor(ledger, provider).run(_computation())

    # `stdout` 은 **정규화된** 출력이다 (계약 §4). 날것을 돌려주고 정규화를
    # 채점기에 미루면 digest 를 만든 문자열과 `claimed_value` 를 찾는 문자열이
    # 서로 다른 함수를 거치게 되고, 둘이 갈라지는 날 "해시가 덮지 않은 값" 이
    # 통과한다. 한 문자열에서 둘 다 나오게 묶는다.
    assert run.stdout == "42.5"
    assert run.digest == _digest("42.5")
    assert run.capped == ""


@pytest.mark.asyncio
async def test_the_digest_survives_a_windows_line_ending(tmp_path) -> None:
    """정규화가 실제로 digest 경로에 걸려 있는가.

    `normalize_stdout` 의 단위 테스트는 따로 있다. 여기서 보는 것은 그것이
    **해시 앞에** 놓였는가다 -- 순서가 뒤집히면 같은 계산이 플랫폼마다 다른
    digest 를 낸다.
    """
    ledger = _FakeLedger({SCRIPT_REF: "import sys; sys.stdout.write('42.5\\r\\n')"})

    run = await _reexecutor(ledger, _provider(tmp_path)).run(_computation())

    assert run.digest == _digest("42.5")


@pytest.mark.asyncio
async def test_the_inputs_are_where_the_worker_left_them(tmp_path) -> None:
    """재현은 **같은 자리**에서 같은 바이트를 읽는 것이다.

    워커의 샌드박스와 이 샌드박스가 같은 배치 함수를 쓰므로
    (`materialize_evidence`), 워커가 쓴 경로가 여기서도 그대로 열린다.
    자리가 어긋나면 모든 계산 클레임이 재현 실패로 죽는다.
    """
    script = f"print(open('evidence/{INPUT_REF}.txt').read().strip())"
    ledger = _FakeLedger({SCRIPT_REF: script, INPUT_REF: "본문 42.5"})

    run = await _reexecutor(ledger, _provider(tmp_path)).run(
        _computation(inputs=[INPUT_REF])
    )

    assert run.stdout.strip() == "본문 42.5"


@pytest.mark.asyncio
async def test_each_run_gets_a_sandbox_of_its_own(tmp_path) -> None:
    """두 번 돌리는 것이 재현성 검사의 전부다 -- 서로를 보면 안 된다."""
    script = (
        "import os\n"
        "print('seen' if os.path.exists('marker') else 'fresh')\n"
        "open('marker', 'w').write('x')\n"
    )
    ledger = _FakeLedger({SCRIPT_REF: script})
    provider = _provider(tmp_path)
    reexecutor = _reexecutor(ledger, provider)

    first = await reexecutor.run(_computation())
    second = await reexecutor.run(_computation())

    assert first.stdout.strip() == "fresh"
    assert second.stdout.strip() == "fresh"
    assert len(set(provider.created)) == 2


@pytest.mark.asyncio
async def test_the_sandbox_is_destroyed_when_the_run_ends(tmp_path) -> None:
    ledger = _FakeLedger({SCRIPT_REF: "print(1)"})
    provider = _provider(tmp_path)

    await _reexecutor(ledger, provider).run(_computation())

    assert provider.destroyed == provider.created


@pytest.mark.asyncio
async def test_the_sandbox_is_destroyed_when_the_script_blows_up(tmp_path) -> None:
    """실패한 실행이 샌드박스를 남기면 새는 것은 프로덕션에서만 보인다."""
    ledger = _FakeLedger({SCRIPT_REF: "raise SystemExit(3)"})
    provider = _provider(tmp_path)

    await _reexecutor(ledger, provider).run(_computation())

    assert provider.destroyed == provider.created
    assert len(provider.created) == 1


# ---- 한도 (계약 §7) -----------------------------------------------------------


@pytest.mark.asyncio
async def test_a_slow_script_is_capped_by_name(tmp_path) -> None:
    """이름이 그대로 `compute_reexecution_capped` 의 payload 가 된다."""
    ledger = _FakeLedger({SCRIPT_REF: "import time; time.sleep(30)"})
    provider = _provider(tmp_path)

    run = await _reexecutor(ledger, provider, cpu_sec=0.5).run(_computation())

    assert run.capped == "cpu_sec"
    # 한도에 걸린 실행은 답을 내지 못했다. digest 를 지어내지 않는다 --
    # 빈 stdout 의 해시를 돌려주면 채점기가 그것을 진짜 답으로 비교한다.
    assert run.digest == ""
    assert provider.destroyed == provider.created


@pytest.mark.asyncio
async def test_a_chatty_script_is_capped_by_name(tmp_path) -> None:
    ledger = _FakeLedger({SCRIPT_REF: "print('x' * 100000)"})
    provider = _provider(tmp_path)

    run = await _reexecutor(ledger, provider, stdout_bytes=256).run(_computation())

    assert run.capped == "stdout_bytes"
    assert run.digest == ""
    assert provider.destroyed == provider.created


@pytest.mark.asyncio
async def test_a_run_reports_how_long_it_took(tmp_path) -> None:
    """`compute_reexecuted` 의 "소요" 다. 0 이면 이벤트가 비용을 말하지 못한다."""
    ledger = _FakeLedger({SCRIPT_REF: "import time; time.sleep(0.05); print(1)"})

    run = await _reexecutor(ledger, _provider(tmp_path)).run(_computation())

    assert run.duration_sec >= 0.05


# ---- 없는 스크립트 -------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_script_that_is_not_in_the_ledger_is_refused_loudly(tmp_path) -> None:
    """채점기의 규칙 1 이 이미 막는다 -- 여기 오면 배선이 틀린 것이다.

    조용히 빈 결과를 돌려주면 그 계산은 `E_COMPUTE_NOT_REPRODUCED` 를 받는다.
    돌려 보지도 않고 "다른 답이 나왔다" 고 말하는 모양이고, 그것이 이 트랙이
    반복해서 피해 온 실패다.
    """
    provider = _provider(tmp_path)

    with pytest.raises(KeyError):
        await _reexecutor(_FakeLedger({}), provider).run(_computation())

    # 원장부터 읽으므로 샌드박스는 만들지도 않았다 -- 샌드박스는 비싸다.
    assert provider.created == []
