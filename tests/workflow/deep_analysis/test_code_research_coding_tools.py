"""조사 자식이 코드를 돌린다 (J1.5 — 포트 합성 · 게이트 · 스크립트 원장 커밋).

J1 의 조각은 전부 초록이었지만 `research` 스펙의 `execute.v1` 은 자식에게
**보이지 않았다** -- `ChildStepper` 는 포트 ∩ 스펙만 보여 주고, 포트는 DA 도구
셋만 내밀었다. 이 파일은 그 셋에 질문 샌드박스에 묶인 코딩 도구 다섯이 붙는
것, 그 다섯이 **게이트를 거쳐서만** 도는 것, 그리고 돌린 스크립트가 **돌기
전에** 원장에 들어가는 것을 고정한다.

샌드박스는 가짜가 아니다 -- 메모리 provider 에서 진짜 `python3` 을 돌린다.
digest 가 재실행기와 같은지는 가짜로는 확인할 수 없기 때문이다.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest

from neos.coding.sandbox.base import SandboxLimits
from neos.coding.sandbox.memory import MemorySandboxProvider
from neos.subagent.catalog import lookup_spec
from neos.workflow.deep_analysis.fetch import _content_hash
from neos.workflow.deep_analysis.graders.computed import digest_stdout
from neos.workflow.deep_analysis.models import (
    Assignment,
    ComputedEvidence,
    Effort,
    ProposedClaim,
    ProposedEvidence,
)
from neos.workflow.deep_analysis.research_gate import (
    ARGV_SHAPE,
    CODING_TOOLS,
    CWD,
    DENIED_EVENT,
    EVIDENCE_READONLY,
    IO,
    SCRIPT_PATH,
)
from neos.workflow.deep_analysis.research_session import (
    CommandLimits,
    open_research_session,
)
from neos.workflow.deep_analysis.script_blob import (
    SCRIPT_URL_SCHEME,
    is_script_blob,
    script_blob,
)

pytestmark = pytest.mark.no_db

_LIMITS = CommandLimits(timeout_sec=10.0, output_bytes=64 * 1024)


class _Question:
    evidence_bytes = 0


class _Ledger:
    """포트 쪽이 닿는 원장 표면 -- 거절 로그와 blob 커밋만."""

    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict]] = []
        self.blobs: dict[str, Any] = {}
        self.order: list[str] = []
        self.db = SimpleNamespace(flush=self._flush)

    async def _flush(self) -> None:
        return None

    async def log(self, kind: str, qid: str, payload: dict) -> None:
        self.events.append((kind, qid, payload))

    async def get_question(self, question_id: str):
        return _Question()

    async def get_blob(self, content_hash: str):
        return self.blobs.get(content_hash)

    async def commit_blobs(self, blobs) -> None:
        for blob in blobs:
            self.order.append(f"commit:{blob.content_hash}")
            self.blobs.setdefault(blob.content_hash, blob)

    def denials(self) -> list[dict]:
        return [payload for kind, _, payload in self.events if kind == DENIED_EVENT]


async def _session(tmp_path, ledger: _Ledger, *, limits=_LIMITS, fetch_fn=None):
    provider = MemorySandboxProvider(root=tmp_path / "sandboxes")

    async def no_fetch(url: str):
        raise AssertionError("not fetched in this test")

    return await open_research_session(
        ledger=ledger,
        provider=provider,
        question_id="q_1",
        cap_bytes=1024 * 1024,
        fetch_fn=fetch_fn or no_fetch,
        limits=SandboxLimits.safe_defaults(),
        command_limits=limits,
    )


def _spy_runs(session, ledger: _Ledger) -> None:
    """실행이 일어난 자리를 원장 커밋과 **같은 줄**에 적는다 -- 순서를 보려고."""
    real = session.sandbox.session.execute

    async def execute(request):
        ledger.order.append("run")
        return await real(request)

    session.sandbox.session.execute = execute


# --- 1. 합성 -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_research_child_now_sees_the_coding_tools(tmp_path) -> None:
    """The bug: `execute.v1` was in the spec and nowhere in the port.

    Mutation: return only the DA tools from `definitions()` -> the child's
    view (port ∩ spec) has no `execute.v1`, which is exactly the J1 state.
    """
    session = await _session(tmp_path, _Ledger())
    try:
        names = {item.name for item in session.port.definitions()}
        visible = names & lookup_spec("research").allowed_tools
    finally:
        await session.close()

    assert CODING_TOOLS <= visible
    assert {"fetch.v1", "submit.v1"} <= visible


def test_every_coding_tool_the_port_offers_is_in_the_research_spec() -> None:
    """A name outside the spec would vanish silently from the child's view."""
    assert CODING_TOOLS <= lookup_spec("research").allowed_tools


@pytest.mark.asyncio
async def test_without_command_limits_the_port_is_the_old_one(tmp_path) -> None:
    provider = MemorySandboxProvider(root=tmp_path / "sandboxes")
    session = await open_research_session(
        ledger=_Ledger(),
        provider=provider,
        question_id="q_1",
        cap_bytes=1024,
        fetch_fn=None,
        limits=SandboxLimits.safe_defaults(),
    )
    try:
        names = {item.name for item in session.port.definitions()}
    finally:
        await session.close()

    assert names == {"fetch.v1", "submit.v1"}


# --- 2. 스크립트 -> 원장 -> 실행 -> digest ------------------------------------

_SCRIPT = "print(46 / 20)\n"


@pytest.mark.asyncio
async def test_execute_commits_the_script_before_running_it(tmp_path) -> None:
    """S8: the bytes that produced the output are in the ledger first.

    Mutation: commit after `session.execute` -> the order flips.
    Mutation: skip the commit -> `script_ref` points at nothing.
    """
    ledger = _Ledger()
    session = await _session(tmp_path, ledger)
    _spy_runs(session, ledger)
    try:
        await session.port.execute(
            "write_file.v1", {"path": "calc.py", "content": _SCRIPT}
        )
        result = await session.port.execute(
            "execute.v1", {"argv": ["python3", "calc.py"]}
        )
    finally:
        await session.close()

    ref = _content_hash(_SCRIPT)
    assert result["script_ref"] == ref
    assert ledger.order == [f"commit:{ref}", "run"]
    stored = ledger.blobs[ref]
    assert stored.raw_text == _SCRIPT
    assert is_script_blob(stored)
    assert stored.source_url == f"{SCRIPT_URL_SCHEME}q_1/calc.py"


@pytest.mark.asyncio
async def test_the_workers_digest_is_the_reexecutors_digest(tmp_path) -> None:
    """The one number that must match across the two runs.

    The port runs the script itself instead of through `SandboxToolExecutor`
    because the executor clips output to a preview, and a clipped stdout
    hashes differently. This runs the real re-executor on the committed
    bytes and compares. Mutation: normalize differently from
    `digest_stdout` (e.g. skip the `rstrip`) -> the digests differ.
    """
    from neos.workflow.deep_analysis.reexecutor import SandboxReexecutor

    ledger = _Ledger()
    session = await _session(tmp_path, ledger)
    try:
        await session.port.execute(
            "write_file.v1", {"path": "calc.py", "content": _SCRIPT}
        )
        result = await session.port.execute(
            "execute.v1", {"argv": ["python3", "calc.py"]}
        )
    finally:
        await session.close()

    rerun = await SandboxReexecutor(
        ledger,
        MemorySandboxProvider(root=tmp_path / "reexec"),
        cpu_sec=10.0,
        memory_mb=512,
        stdout_bytes=64 * 1024,
    ).run(
        ComputedEvidence(
            script_ref=result["script_ref"],
            inputs=[],
            premises=[],
            runtime={},
            output_digest=result["output_digest"],
            claimed_value="2.3",
        )
    )

    assert result["stdout"] == "2.3"
    assert result["output_digest"] == digest_stdout(b"2.3\n")[1]
    assert rerun.digest == result["output_digest"]


@pytest.mark.asyncio
async def test_a_truncated_run_gets_no_digest(tmp_path) -> None:
    """A capped run did not produce an answer; the re-executor says the same.

    Mutation: always return the digest -> the worker cites the hash of a
    clipped stdout, which no re-execution can reproduce.
    """
    ledger = _Ledger()
    session = await _session(
        tmp_path, ledger, limits=CommandLimits(timeout_sec=10.0, output_bytes=64)
    )
    try:
        await session.port.execute(
            "write_file.v1", {"path": "big.py", "content": "print('x' * 10000)\n"}
        )
        result = await session.port.execute(
            "execute.v1", {"argv": ["python3", "big.py"]}
        )
    finally:
        await session.close()

    assert result["stdout_truncated"] is True
    assert result["output_digest"] is None


# --- 3. 게이트 -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "payload", "reason"),
    [
        # 재실행기는 인자를 넘기지 않는다.
        ("execute.v1", {"argv": ["python3", "calc.py", "--x"]}, ARGV_SHAPE),
        # 스크립트가 아닌 것.
        ("execute.v1", {"argv": ["python3", "calc.txt"]}, SCRIPT_PATH),
        # 증거 자리에 있는 것은 워커가 쓴 스크립트일 수 없다.
        ("execute.v1", {"argv": ["python3", "evidence/x.py"]}, SCRIPT_PATH),
        # 재실행기는 루트에서 돈다.
        ("execute.v1", {"argv": ["python3", "calc.py"], "cwd": "sub"}, CWD),
        # 재실행기는 stdin 을 넘기지 않는다.
        ("execute.v1", {"argv": ["python3", "calc.py"], "stdin": "1"}, IO),
        # 증거는 원장이 넣은 바이트뿐이다(I4).
        (
            "write_file.v1",
            {"path": "./evidence/abc.txt", "content": "forged"},
            EVIDENCE_READONLY,
        ),
    ],
)
@pytest.mark.asyncio
async def test_the_gate_refuses_what_reexecution_cannot_repeat(
    tmp_path, name, payload, reason
) -> None:
    """Refused, recorded in the ledger, and nothing ran or was committed.

    Mutation (each row): drop that rule from `research_denial` -> the call
    runs. Mutation: skip the ledger log -> the denial is silent.
    """
    ledger = _Ledger()
    session = await _session(tmp_path, ledger)
    _spy_runs(session, ledger)
    try:
        await session.sandbox.session.write_file("calc.py", _SCRIPT.encode())
        result = await session.port.execute(name, payload)
    finally:
        await session.close()

    assert result == {"error": reason}
    assert ledger.denials() == [{"tool": name, "reason_code": reason}]
    assert ledger.order == []


@pytest.mark.asyncio
async def test_the_registry_allowlist_is_python3_only(tmp_path) -> None:
    """Contract §3.2. The registry refuses before the gate sees it."""
    ledger = _Ledger()
    session = await _session(tmp_path, ledger)
    try:
        other = await session.port.execute("execute.v1", {"argv": ["node", "x.js"]})
        inline = await session.port.execute(
            "execute.v1", {"argv": ["python3", "-c", "print(1)"]}
        )
    finally:
        await session.close()

    assert other == {"error": "policy_executable_not_allowed"}
    assert inline == {"error": "policy_inline_interpreter_denied"}


@pytest.mark.asyncio
async def test_reads_and_workspace_writes_pass(tmp_path) -> None:
    ledger = _Ledger()
    session = await _session(tmp_path, ledger)
    try:
        wrote = await session.port.execute(
            "write_file.v1", {"path": "notes/a.txt", "content": "hi"}
        )
        read = await session.port.execute("read_file.v1", {"path": "notes/a.txt"})
    finally:
        await session.close()

    assert "error" not in wrote
    assert "error" not in read
    assert ledger.denials() == []


@pytest.mark.asyncio
async def test_an_unbound_gate_refuses_every_coding_tool(tmp_path) -> None:
    """CHILD-GATE: no path reaches the sandbox without the gate."""
    from dataclasses import replace

    ledger = _Ledger()
    session = await _session(tmp_path, ledger)
    _spy_runs(session, ledger)
    session.port._coding = replace(session.port._coding, authorize=None)
    try:
        read = await session.port.execute("read_file.v1", {"path": "x"})
        run = await session.port.execute("execute.v1", {"argv": ["python3", "a.py"]})
    finally:
        await session.close()

    assert read == run == {"error": "policy_gate_unbound"}
    assert ledger.order == []


# --- 4. 스크립트는 증거가 아니다 (I4) ------------------------------------------


@dataclass
class _Row:
    url: str
    http_status: int
    raw_text: str


class _GraderLedger:
    def __init__(self, rows: dict[str, _Row]) -> None:
        self._rows = rows

    async def get_blob(self, content_hash: str):
        return self._rows.get(content_hash)

    async def get_claim(self, claim_id: str):
        return SimpleNamespace(status="verified", kind="quote", confidence=0.9)


_SCRIPT_ROW = _Row(f"{SCRIPT_URL_SCHEME}q_1/calc.py", 200, "print('A revenue 46')")


@pytest.mark.asyncio
async def test_a_quote_cannot_cite_the_workers_own_script() -> None:
    """Mutation: drop the script check in `DeterministicGrader` -> the excerpt
    matches the script's own text and the claim is verified."""
    from neos.workflow.deep_analysis.graders.deterministic import DeterministicGrader

    grader = DeterministicGrader(
        _GraderLedger({"s" * 16: _SCRIPT_ROW}),
        quote_threshold=0.5,
        confidence_cap={1: 0.6, 2: 0.8, 3: 0.9},
    )
    verdict = await grader.grade(
        ProposedClaim(
            "A 의 매출은 46 이다",
            0.5,
            [ProposedEvidence("https://x", "A revenue 46", "s" * 16)],
        )
    )

    assert verdict.ok is False
    assert verdict.code == "E_NO_EVIDENCE"


@pytest.mark.asyncio
async def test_a_computation_cannot_take_a_script_as_input() -> None:
    """Mutation: drop the script check in `grade_computed` rule 1 -> the
    input is "a ledger blob" and the chain continues."""
    from neos.workflow.deep_analysis.graders.computed import grade_computed

    rows = {"s" * 16: _SCRIPT_ROW, "t" * 16: _SCRIPT_ROW}

    class _Never:
        async def run(self, computation):
            raise AssertionError("rule 1 must stop it before re-execution")

    verdict = await grade_computed(
        ProposedClaim(
            "t",
            0.5,
            kind="computed",
            computation=ComputedEvidence(
                script_ref="t" * 16,
                inputs=["s" * 16],
                premises=[],
                runtime={},
                output_digest="d",
                claimed_value="1",
            ),
        ),
        ledger=_GraderLedger(rows),
        confidence_cap={1: 0.6, 2: 0.8, 3: 0.9},
        reexecutor=_Never(),
        question_id="q_1",
    )

    assert verdict.code == "E_COMPUTE_INPUT_UNFETCHED"
    assert "worker script" in verdict.detail


def test_script_blobs_share_the_fetch_address_width() -> None:
    blob = script_blob("x = 1\n", question_id="q", path="a.py")

    assert blob.content_hash == _content_hash("x = 1\n")
    assert len(blob.content_hash) == 16


# --- 5. briefing ---------------------------------------------------------------


def _assignment(**overrides) -> Assignment:
    base = dict(
        question_id="q_1",
        brief="렌더된 worker_brief 전문",
        effort=Effort.DIG,
        question_text="A 와 B 중 어느 쪽 매출이 큰가",
    )
    base.update(overrides)
    return Assignment(**base)


def test_the_research_briefing_carries_ids_dead_ends_and_repairs() -> None:
    """The child can finally name premises.

    Mutation: drop the ID from the verified line -> no claim_id to put in
    `premises`, so no computed claim can pass rule 2.
    """
    from neos.workflow.deep_analysis.subagent_adapter import research_briefing

    briefing = research_briefing(
        _assignment(
            repairs=[
                {
                    "claim_id": "c_9",
                    "code": "E_OVERCLAIM",
                    "detail": "too strong",
                    "salvage": None,
                }
            ]
        ),
        verified=(("c_a", "A 의 2025 매출은 46억 달러다"),),
        dead_ends=("IR 페이지는 로그인 필요",),
    )

    assert briefing.goal == "A 와 B 중 어느 쪽 매출이 큰가"
    assert "c_a | A 의 2025 매출은 46억 달러다" in briefing.why
    assert briefing.already_tried == ("IR 페이지는 로그인 필요",)
    assert "c_9 | E_OVERCLAIM | too strong |" in briefing.scope


def test_the_explore_ticket_briefing_does_not_move() -> None:
    """S9: the explore path (subagent flag) keeps its goal-only briefing."""
    from neos.subagent.types import ParentBriefing
    from neos.workflow.deep_analysis.subagent_adapter import build_explore_ticket

    ticket = build_explore_ticket(_assignment(), parent_id="run00001")

    assert ticket.briefing == ParentBriefing(goal="A 와 B 중 어느 쪽 매출이 큰가")


def test_repair_lines_keep_the_worker_brief_bytes() -> None:
    """I1: the extraction must not move one byte of `worker_brief`."""
    from neos.workflow.deep_analysis.assignment import render_repair_lines

    repairs = [
        {"claim_id": "c1", "code": "E_OVERCLAIM", "detail": "d", "salvage": None},
        {"claim_id": "c2", "code": "E_X", "detail": "e", "salvage": "https://s"},
    ]

    assert render_repair_lines(repairs) == (
        "c1 | E_OVERCLAIM | d | 문구를 증거 수준으로 약화(action=weakened, 재조사 금지) | \n"
        "c2 | E_X | e |  | https://s"
    )


@pytest.mark.asyncio
async def test_the_worker_hands_the_child_verified_quote_ids_only(tmp_path) -> None:
    """Computed claims are not offered as premises (rule 2, at the source).

    Mutation: drop the kind filter in `_briefing_material` -> `c_comp`
    appears. Mutation: build the ticket without `briefing=` -> no IDs.
    """
    from neos.subagent.types import StepKind
    from neos.workflow.deep_analysis.research_worker import run_research_worker

    ledger = _Ledger()

    async def verified_claims(question_id):
        return [
            (SimpleNamespace(id="c_a", text="A 는 46", kind="quote"), []),
            (SimpleNamespace(id="c_comp", text="A/B=2.3", kind="computed"), []),
        ]

    async def dead_ends(question_id):
        return ["막힌 길"]

    ledger.verified_claims = verified_claims
    ledger.unverified_and_deadends = dead_ends
    tickets: list[Any] = []

    class _Runtime:
        async def advance(self, ticket):
            tickets.append(ticket)
            return SimpleNamespace(
                kind=StepKind.CONTINUING, run_id="r", checkpoint_id="c", tokens_delta=0
            )

    await run_research_worker(
        _assignment(),
        ledger=ledger,
        provider=MemorySandboxProvider(root=tmp_path / "sandboxes"),
        grader=None,
        cap_bytes=1024,
        limits=SandboxLimits.safe_defaults(),
        fetch_fn=None,
        runtime_factory=lambda port: _Runtime(),
        parent_id="run00001",
        command_limits=_LIMITS,
    )

    [ticket] = tickets
    assert "c_a | A 는 46" in ticket.briefing.why
    assert "c_comp" not in ticket.briefing.why
    assert ticket.briefing.already_tried == ("막힌 길",)


# --- 6. 라운드를 넘는 증거 ------------------------------------------------------


@pytest.mark.asyncio
async def test_a_new_rounds_sandbox_has_the_evidence_earlier_rounds_fetched(
    tmp_path,
) -> None:
    """Found by the E2E: each round opens a fresh sandbox, so round 1's
    `/evidence` was gone by round 2 -- the first round a computed claim can be
    written in (premise IDs arrive through the briefing).

    Mutation: skip `store.restore` in `open_research_session` -> the file is
    missing and the script dies with FileNotFoundError.
    """
    ledger = _Ledger()
    ledger.blobs["e" * 16] = SimpleNamespace(raw_text="A revenue 46")

    async def refs(question_id):
        assert question_id == "q_1"
        return ["e" * 16]

    ledger.sandbox_evidence_refs = refs
    session = await _session(tmp_path, ledger)
    try:
        body = await session.sandbox.session.read_file(f"evidence/{'e' * 16}.txt")
    finally:
        await session.close()

    assert body == b"A revenue 46"
    # 다시 가져온 것이 아니다: 청구도 기록도 없다.
    assert ledger.events == []
    assert ledger.order == []
