"""질문 하나 분량의 조사 도구 조립 (계약 §3.1 · §3.2).

J1 의 조각들은 각자 초록이었지만 서로를 부르지 않았다 -- `fetch.v1` 도,
`decide_fetch_admission` 도, `open_question_sandbox` 도 프로덕션 호출부가
0 이었다. 이 모듈이 그 셋을 한 줄로 꿴다.

**왜 `research_tools.py` 가 아닌가.** 조립은 원장을 인자로 받는다. 워커 쪽
포트가 사는 모듈이 원장을 받으면 "코딩 워커는 원장 쓰기 경로를 갖지
않는다"(I2 · P2)가 문자열 검사만 통과하는 모양이 된다. 조립은
**오케스트레이터 쪽**이고, 그래서 여기다.

**수명은 질문 하나다.** `_run_round` 가 `asyncio.gather` 로 질문들을 **동시에**
돌리므로(오케스트레이터), 포트와 샌드박스를 공유하면 질문 A 의 fetch 가
질문 B 의 샌드박스에 증거를 놓고 한도는 엉뚱한 행에 청구된다. 늦은 바인딩
(`CodingToolPort.bind()` 같은)이 여기서 쓰이지 못하는 이유다 -- 코딩 루프는
루프당 세션 하나지만 여기는 동시에 여럿이다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .evidence_store import LedgerEvidenceStore
from .research_gate import ResearchGate
from .research_tools import CodingSurface, ResearchToolPort
from .sandbox import RESEARCH_PROFILE, QuestionSandbox, open_question_sandbox

#: 조사 자식이 돌릴 수 있는 실행 파일. 계약 §3.2 "argv allowlist: `python3` 만".
#: 설정이 아닌 이유: 이것은 배포가 고르는 값이 아니라 재실행기가 돌릴 수 있는
#: 것이다(`reexecutor.py` 는 `python3` 만 부른다).
RESEARCH_COMMANDS = frozenset({"python3"})


@dataclass(frozen=True, slots=True)
class CommandLimits:
    """워커의 `execute.v1` 한도. **재실행 한도와 같은 값**을 넘긴다.

    다르면 워커 안에서는 끝난 계산이 채점 때 한도에 걸린다 -- 제출할 때는
    멀쩡했던 클레임이 `compute_reexecution_capped` 로 멈추는 모양이다.
    """

    timeout_sec: float
    output_bytes: int


def _coding_surface(ledger: Any, *, question_id: str, session: Any, limits: CommandLimits) -> CodingSurface:
    from neos.coding.tools.executor import SandboxToolExecutor
    from neos.coding.tools.registry import CodingToolRegistry

    registry = CodingToolRegistry.default(
        command_allowlist=RESEARCH_COMMANDS,
        max_command_timeout_sec=limits.timeout_sec,
        max_command_output_bytes=limits.output_bytes,
        # 0 은 레지스트리가 받지 않는다(≥1). stdin 은 게이트가 비어 있기를
        # 요구하므로 한 바이트면 충분하다.
        max_command_stdin_bytes=1,
        allowed_env_names=frozenset(),
    )
    executor = SandboxToolExecutor(
        max_preview_bytes=limits.output_bytes, max_entries=1000
    )
    gate = ResearchGate(ledger, question_id=question_id)
    return CodingSurface(
        registry=registry,
        executor=executor,
        session=session,
        authorize=gate.authorize,
    )


@dataclass
class ResearchSession:
    """한 질문의 도구 + 그 질문의 샌드박스."""

    port: ResearchToolPort
    sandbox: QuestionSandbox

    async def close(self) -> None:
        """질문이 끝나면 샌드박스도 끝난다.

        리스가 없으므로 뒤늦게 회수해 줄 층이 없다 -- 여기서 부수지 않으면
        아무도 부수지 않는다.
        """
        await self.sandbox.close()


async def open_research_session(
    *,
    ledger: Any,
    provider: Any,
    question_id: str,
    cap_bytes: int,
    fetch_fn: Any,
    limits: Any,
    grader: Any = None,
    profile: str = RESEARCH_PROFILE,
    command_limits: CommandLimits | None = None,
) -> ResearchSession:
    """이 질문의 샌드박스를 열고 도구를 묶는다.

    `fetch_fn` 은 `neos.workflow.deep_analysis.fetch.fetch_url` 이다. 주입
    으로 받는 이유는 카세트 재생(J3 오프라인 섀도)이 같은 자리를 갈아끼우기
    때문이고, 그때도 구현은 여전히 하나다.

    `command_limits` 가 있으면 코딩 도구 다섯이 이 질문의 샌드박스에 묶여
    게이트(`ResearchGate`)와 함께 붙는다(J1.5). 없으면 DA 도구만이다 --
    오케스트레이터는 언제나 넘긴다(`_run_worker`).

    `grader` 는 오케스트레이터가 이미 들고 있는 결정론 채점기다
    (`Orchestrator.__init__` 의 네 번째 인자). 없으면 `check_claims.v1` 이
    목록에서 빠진다 -- 부를 수 없는 도구를 내밀지 않는다.
    """
    sandbox = await open_question_sandbox(
        provider, question_id=question_id, limits=limits, profile=profile
    )
    store = LedgerEvidenceStore(ledger, question_id=question_id)
    try:
        await store.restore(sandbox)
    except BaseException:
        # 여기서 터지면 부르는 쪽은 세션을 받지 못해 닫을 수 없다.
        await sandbox.close()
        raise
    port = ResearchToolPort(
        fetch_fn=fetch_fn,
        store=store,
        sandbox=sandbox,
        cap_bytes=cap_bytes,
        grader=grader,
        coding=(
            None
            if command_limits is None
            else _coding_surface(
                ledger,
                question_id=question_id,
                session=sandbox.session,
                limits=command_limits,
            )
        ),
    )
    return ResearchSession(port=port, sandbox=sandbox)
