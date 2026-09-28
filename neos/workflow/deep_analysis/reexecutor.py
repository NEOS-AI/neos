"""계산 클레임을 샌드박스에서 다시 돌린다 (계약 §5 · §7).

채점기(`graders/computed.py`)는 이 모듈을 모른다 -- 재실행기를 **주입**받고
`run(computation)` 하나만 부른다. 규칙과 실행을 나눈 이유는 규칙이 샌드박스
없이 전부 검사 가능하기 때문이고, 그 경계가 여기다.

## 실행마다 새 샌드박스다

두 번 돌려 digest 를 비교하는 것이 재현성 검사의 전부다(§5). 같은 샌드박스를
재사용하면 두 방향으로 판정이 뒤집힌다 -- 상태를 쌓는 스크립트는 둘째 실행이
첫 실행의 파일을 봐서 **멀쩡한 계산이 비결정적으로** 보이고, 결과를 캐시에
쓰는 스크립트는 반대로 **비결정적인 계산이 결정론적으로** 보인다. 격리는
취향이 아니라 정확성이다.

## 증거는 워커가 뒀던 자리에 놓는다

워커의 샌드박스와 같은 `materialize_evidence` 를 쓴다. 배치가 어긋나면
스크립트가 입력을 못 찾고, 그러면 **모든** 계산 클레임이 재현 실패로 죽는다
-- 계산이 틀려서가 아니라 채점기가 자리를 옮겨서.

## 한도는 이름을 잃지 않는다

`capped` 는 불리언이 아니라 **넘은 한도의 이름**이다. 계약 §6 의
`compute_reexecution_capped` payload 가 그것을 요구하고, 화면의 문구도 그것을
싣는다 -- "한도 초과" 만으로는 계산을 줄여야 하는지 출력을 줄여야 하는지
알 수 없다.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from neos.coding.sandbox.base import CommandRequest, SandboxLimits

from .graders.computed import digest_stdout
from .sandbox import RESEARCH_PROFILE, open_question_sandbox

#: `capped` 에 실리는 이름. 설정 키(`code_research.reexecution.*`)와 같은
#: 철자다 -- 화면에서 읽은 이름으로 설정을 찾을 수 있어야 한다.
CPU_LIMIT = "cpu_sec"
STDOUT_LIMIT = "stdout_bytes"

#: 워크스페이스 안의 스크립트 자리. `/evidence` 와 겹치지 않는다.
SCRIPT_PATH = "script.py"


@dataclass(frozen=True, slots=True)
class Reexecution:
    """한 번 돌린 결과.

    `stdout` 은 **정규화된** 출력이고 `digest` 는 바로 그 문자열의 해시다
    (계약 §4). 날것을 돌려주고 정규화를 채점기에 미루면 digest 를 만든
    문자열과 `claimed_value` 를 찾는 문자열이 서로 다른 함수를 거치게 되고,
    둘이 갈라지는 날 **해시가 덮지 않은 값**이 통과한다.

    `capped` 가 비어 있지 않으면 `digest` 와 `stdout` 은 비어 있다 -- 한도에
    걸린 실행은 **답을 내지 못한 것**이고, 빈 출력의 해시를 돌려주면 채점기가
    그것을 진짜 답으로 비교한다.
    """

    digest: str
    stdout: str
    capped: str = ""
    duration_sec: float = 0.0


class SandboxReexecutor:
    """`research-offline-v1` 샌드박스 위의 재실행기.

    원장은 **읽기만** 한다 (`get_blob`). 이벤트는 `Ledger._apply_verdict` 가
    낸다 -- 여기에는 claim_id 가 없기 때문이다(계약 §6 주석 참조).
    """

    def __init__(
        self,
        ledger: Any,
        provider: Any,
        *,
        cpu_sec: float,
        memory_mb: int,
        stdout_bytes: int,
        profile: str = RESEARCH_PROFILE,
    ) -> None:
        self._ledger = ledger
        self._provider = provider
        # 워커가 돈 것과 같은 profile 에서 다시 돌린다. 다른 격리에서 같은
        # digest 가 나와도 그것은 재현이 아니라 우연이다.
        self._profile = profile
        self._cpu_sec = float(cpu_sec)
        self._stdout_bytes = int(stdout_bytes)
        # `cpu_sec` 은 설정의 이름이지만 샌드박스 층에는 CPU 시간 한도가
        # 없고 **벽시계 타임아웃**뿐이다(`SandboxLimits.command_timeout_sec`).
        # 이름을 바꾸지 않는 이유는 계약 §7 의 설정 키이기 때문이고, 다르다는
        # 사실은 여기 적어 둔다 -- 느린 I/O 가 CPU 초과로 보고될 수 있다.
        self._limits = SandboxLimits(
            cpu_count=1.0,
            memory_bytes=int(memory_mb) * 1024 * 1024,
            pids=128,
            workspace_bytes=1024 * 1024 * 1024,
            command_timeout_sec=self._cpu_sec,
            max_output_bytes=self._stdout_bytes,
            max_stdin_bytes=1024 * 1024,
        )

    async def _blob_text(self, content_hash: str) -> str:
        blob = await self._ledger.get_blob(content_hash)
        if blob is None:
            # 조용히 빈 결과를 돌려주면 그 계산은 `E_COMPUTE_NOT_REPRODUCED`
            # 를 받는다 -- 돌려 보지도 않고 "다른 답이 나왔다" 고 말하는
            # 모양이다. 채점기의 규칙 1 이 이미 막으므로 여기 오면 배선 오류다.
            raise KeyError(content_hash)
        return blob.raw_text or ""

    async def run(self, computation: Any) -> Reexecution:
        # 원장부터 읽는다. 스크립트가 없으면 샌드박스를 만들지도 않는다.
        script = await self._blob_text(computation.script_ref)
        inputs = {
            raw_ref: await self._blob_text(raw_ref)
            for raw_ref in computation.inputs
        }

        sandbox = await open_question_sandbox(
            self._provider,
            # 리스가 없으므로 owner 는 회계용 이름일 뿐이다. 질문이 아니라
            # 채점이 주인이라는 것을 남긴다.
            question_id=f"regrade_{computation.script_ref[:8]}",
            limits=self._limits,
            profile=self._profile,
        )
        try:
            for raw_ref, text in inputs.items():
                await sandbox.materialize_evidence(raw_ref, text)
            await sandbox.session.write_file(
                SCRIPT_PATH, script.encode("utf-8")
            )

            started = time.monotonic()
            result = await sandbox.session.execute(
                CommandRequest(
                    argv=("python3", SCRIPT_PATH),
                    timeout_sec=self._cpu_sec,
                    max_output_bytes=self._stdout_bytes,
                )
            )
            duration = time.monotonic() - started
        finally:
            # 실패한 실행이 샌드박스를 남기면 새는 것은 프로덕션에서만 보인다.
            await sandbox.close()

        if result.timed_out:
            return Reexecution(
                digest="", stdout="", capped=CPU_LIMIT, duration_sec=duration
            )
        if result.stdout_truncated:
            return Reexecution(
                digest="", stdout="", capped=STDOUT_LIMIT, duration_sec=duration
            )

        # 0 이 아닌 종료 코드는 따로 다루지 않는다. 터진 스크립트는 주장한
        # 출력을 내지 못했으므로 digest 비교에서 `E_COMPUTE_NOT_REPRODUCED`
        # 로 죽고, 그것이 정확한 진단이다 -- 돌렸고, 다른 답이 나왔다.
        stdout, digest = digest_stdout(result.stdout)
        return Reexecution(digest=digest, stdout=stdout, duration_sec=duration)
