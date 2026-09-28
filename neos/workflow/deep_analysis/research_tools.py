"""조사 워커의 도구 포트 (계약 §3).

여기 있는 것은 **DA 쪽 도구**다. 코딩 도구(`read_file.v1`·`execute.v1` 등)는
`CodingToolRegistry` 가 그대로 갖고 있고 이 모듈은 건드리지 않는다 -- 그것이
I1(플래그 off 면 워커 프롬프트·도구 목록이 바이트 단위로 이전과 같다)을
구조적으로 지키는 방법이다. 레지스트리에 새 이름을 넣으면 플래그와 무관하게
모든 코딩 워커의 도구 목록이 달라진다.

`ToolPort` 는 `definitions()` 와 `execute()` 둘뿐이라(`subagent/types.py`)
포트를 따로 두는 값이 싸다.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Mapping, Protocol

from neos.coding.model.base import ToolDefinition
from neos.coding.redact import strip_binary_payloads
from neos.coding.sandbox.base import CommandRequest, SandboxError
from neos.coding.tools.registry import ToolValidationError

from .evidence_store import CAP_REACHED, decide_fetch_admission
from .fetch import FetchUnavailable
from .graders.computed import digest_stdout
from .research_gate import CODING_TOOLS, EXECUTE_TOOL
from .submission import Submission, parse_claims, parse_submission

#: 계약 §3.1. `_RESEARCH_TOOLS` 와 **같은 이름이어야 한다** --
#: `CodingToolPort.definitions()` 가 `allowed_tools` 로 교집합을 뜨므로
#: 어긋나면 도구는 오류 없이 조용히 사라진다.
FETCH_TOOL = "fetch.v1"
SUBMIT_TOOL = "submit.v1"
CHECK_TOOL = "check_claims.v1"

#: 계산 클레임을 여기서 판별하지 못한다는 도구 수준 사유.
#:
#: 계약 §3.3 은 "계산 클레임은 재실행까지 한다" 고 적지만 재실행은 J2 다.
#: 지금 계산 클레임을 결정론 채점기에 넘기면 quote 규칙이 돌아
#: `E_NO_EVIDENCE` 가 나온다 -- 증거가 `computation` 에 있는데 "근거 없음"
#: 이라고 **자신 있게 틀린 답**을 주는 모양이다. §5 의 `E_*` 어휘를 쓰지
#: 않는 이유도 그것이다: 이것은 판정이 아니라 "판정하지 않았다" 이다.
COMPUTE_CHECK_UNAVAILABLE = "compute_check_unavailable"

#: 오프라인 섀도(J3)의 보관소에 그 URL 이 없다. **죽은 출처가 아니다** --
#: `E_SOURCE_DEAD` 어휘를 쓰지 않는 이유가 그것이다. 한도 초과
#: (`evidence_cap_reached`)와 같은 모양으로 워커에게 알리고 턴은 계속된다.
FETCH_UNAVAILABLE = "fetch_unavailable_offline"

_FETCH = ToolDefinition(
    name=FETCH_TOOL,
    description=(
        "Fetch one http(s) URL as evidence. Returns a path under /evidence, "
        "not the body -- read it with read_file.v1. "
        "This is the only way to retrieve a URL; do not use execute.v1."
    ),
    input_schema={
        "type": "object",
        "properties": {"url": {"type": "string"}},
        "required": ["url"],
    },
)

_SUBMIT = ToolDefinition(
    name=SUBMIT_TOOL,
    description=(
        "Submit this question's findings and end the turn. Call it once. "
        "Claims are proposals -- the orchestrator grades them, so do not "
        "raise confidence to make one pass."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": ["completed", "partial"]},
            "claims": {"type": "array", "items": {"type": "object"}},
            "self_assessment": {"type": "number"},
            "proposed_subquestions": {
                "type": "array",
                "items": {"type": "object"},
            },
            "dead_ends": {"type": "array", "items": {"type": "string"}},
            "repairs": {"type": "array", "items": {"type": "object"}},
            "report_path": {"type": ["string", "null"]},
        },
        "required": ["status", "claims"],
    },
)


_CHECK = ToolDefinition(
    name=CHECK_TOOL,
    description=(
        "Check claims against the deterministic grader without submitting "
        "them. Nothing is recorded -- the orchestrator grades again, so a "
        "green answer here is not a verdict. Computed claims are not "
        "checked yet."
    ),
    input_schema={
        "type": "object",
        "properties": {"claims": {"type": "array", "items": {"type": "object"}}},
        "required": ["claims"],
    },
)


class ClaimGrader(Protocol):
    """`DeterministicGrader` 가 만족한다. 원장을 **읽기만** 한다."""

    async def grade(self, claim: Any) -> Any: ...


class EvidenceStore(Protocol):
    """한도 회계와 **건별** 커밋. 오케스트레이터가 원장 위에 구현한다 (P2)."""

    async def spent_bytes(self) -> int: ...

    async def is_stored(self, content_hash: str) -> bool: ...

    async def commit(self, blob: Any, *, bytes_charged: int) -> None: ...

    async def record_fetched(self, raw_ref: str, path: str) -> None: ...

    async def commit_script(self, text: str, *, path: str) -> str: ...

    async def record_execution(
        self,
        *,
        script_ref: str,
        output_digest: str | None,
        exit_code: int | None,
        timed_out: bool,
        stdout_truncated: bool,
    ) -> None: ...


class QuestionWorkspace(Protocol):
    """`QuestionSandbox` 가 만족한다."""

    async def materialize_evidence(self, raw_ref: str, text: str) -> str: ...


#: (검증된 호출) -> (돌릴 호출, None) 또는 (None, reason_code).
#: 코딩 자식의 `ChildAuthorizer`(`neos/coding/subagent_port.py`)와 같은 모양이다.
ResearchAuthorizer = Callable[[Any], Awaitable[tuple[Any, str | None]]]

#: `execute.v1` 결과에 싣는 stdout·stderr 의 상한. **digest 는 자르기 전의
#: 전체 출력에서 만든다** -- 여기서 자르는 것은 모델에게 보여 줄 몫뿐이다.
_PREVIEW_CHARS = 16 * 1024


@dataclass(frozen=True, slots=True)
class CodingSurface:
    """질문 샌드박스에 묶인 코딩 도구 (J1.5). 오케스트레이터 쪽이 조립한다.

    `authorize` 가 None 이면 코딩 도구는 **전부 거절된다** -- 게이트 없이
    실행기에 닿는 자식이 CHILD-GATE 가 닫은 구멍이다. 필드가 Optional 인
    이유는 그 거절을 테스트가 짚을 수 있게 하려는 것이다.
    """

    registry: Any
    executor: Any
    session: Any
    authorize: ResearchAuthorizer | None


class ResearchToolPort:
    """조사 워커가 보는 도구들 -- DA 쪽 `fetch.v1` · `submit.v1` · `check_claims.v1`
    과, `coding` 이 주어지면 질문 샌드박스에 묶인 코딩 도구 다섯(J1.5).

    코딩 도구가 없던 동안 `research` 스펙의 `execute.v1` 은 **목록에서 조용히
    사라졌다** -- `ChildStepper` 가 포트 ∩ 스펙만 보여 주기 때문이다. 샌드박스는
    열렸지만 쓰이지 않았고, 계산 클레임은 합성 fixture 에서만 존재했다.

    `fetch_fn` 은 `neos.workflow.deep_analysis.fetch.fetch_url` 이다. 여기서
    HTTP 를 다시 부르지 않는 것이 핵심이다 -- 재시도 정책과 blob 해시가
    갈라지면 원장의 blob 과 워커가 읽은 본문이 달라질 수 있다.

    `check_claims.v1` 은 채점기가 주입됐을 때만 열린다.
    """

    def __init__(
        self,
        *,
        fetch_fn,
        store: EvidenceStore,
        sandbox: QuestionWorkspace,
        cap_bytes: int,
        grader: ClaimGrader | None = None,
        coding: CodingSurface | None = None,
    ) -> None:
        self._fetch_fn = fetch_fn
        self._store = store
        self._sandbox = sandbox
        self._cap_bytes = cap_bytes
        self._grader = grader
        self._coding = coding
        self._submission: Submission | None = None

    @property
    def submission(self) -> Submission | None:
        """제출이 있었는가. 없으면 오케스트레이터가 `partial` 로 처리한다.

        계약 §3.4: "`submit.v1` 을 부르지 않고 턴이 끝나면 `partial` 로
        처리하고 원장에 이유를 남긴다 -- 조용한 degrade 금지."
        """
        return self._submission

    def definitions(self) -> tuple[ToolDefinition, ...]:
        # 채점기가 없으면 내밀지 않는다 -- 부를 수 없는 도구를 목록에 두면
        # 모델은 그것을 부르고 매번 거절을 받는다.
        own = (_FETCH, _SUBMIT) if self._grader is None else (_FETCH, _SUBMIT, _CHECK)
        if self._coding is None:
            return own
        # 코딩 도구의 정의는 레지스트리의 것을 **그대로** 쓴다. 여기서 다시
        # 적으면 코딩 루프가 설명을 고칠 때 조사 자식만 옛 설명을 본다.
        coding = tuple(
            item
            for item in self._coding.registry.definitions(
                phase="implement", revealed=CODING_TOOLS
            )
            if item.name in CODING_TOOLS
        )
        return own + coding

    async def execute(
        self, name: str, input: Mapping[str, object]
    ) -> Mapping[str, Any]:
        if name in CODING_TOOLS:
            return await self._execute_coding(name, input)
        if name == SUBMIT_TOOL:
            return self._submit(input)
        if name == CHECK_TOOL:
            return await self._check_claims(input)
        if name != FETCH_TOOL:
            return {"error": "tool_not_allowed"}
        payload = dict(input) if isinstance(input, Mapping) else {}
        url = str(payload.get("url") or "").strip()
        if not url:
            return {"error": "fetch_url_missing"}

        try:
            blob = await self._fetch_fn(url)
        except FetchUnavailable:
            # J3 오프라인 섀도에서만 난다. 라이브 `fetch_url` 은 이것을 던지지
            # 않으므로 플래그 켜짐·꺼짐 어느 쪽 동작도 달라지지 않는다.
            #
            # **좁게 잡는 것이 요점이다.** 아무 예외나 삼키면 진짜 장애가
            # "그 URL 은 없었다" 로 보고되고, 그 거짓말은 섀도가 아닌 경로
            # 에서도 일어난다.
            return {"error": FETCH_UNAVAILABLE}
        # 404 도 blob 이다. `_blob_hash` 가 빈 본문에 상태·URL 을 섞어 별도
        # 해시를 만드는 이유이기도 하다 -- 원장에 기록이 있어야 나중에
        # `E_SOURCE_DEAD` 를 붙일 수 있다.
        text = blob.raw_text or ""
        incoming = len(text.encode("utf-8"))

        admission = decide_fetch_admission(
            cap_bytes=self._cap_bytes,
            spent_bytes=await self._store.spent_bytes(),
            incoming_bytes=incoming,
            already_stored=await self._store.is_stored(blob.content_hash),
        )
        if not admission.admitted:
            # 거절은 반쯤 들어가지 않는다: 커밋도 노출도 하지 않는다.
            return {"error": admission.reason or CAP_REACHED}

        # 순서가 계약이다 (§3.1): 원장에 들어간 **뒤에** `/evidence` 에
        # 나타난다. 뒤집히면 워커가 원장에 없는 증거를 인용할 수 있고, 그
        # 클레임은 채점에서 `E_COMPUTE_INPUT_UNFETCHED` 로 뒤늦게 죽는다.
        await self._store.commit(blob, bytes_charged=admission.bytes_charged)
        path = await self._sandbox.materialize_evidence(blob.content_hash, text)
        # 경로가 생긴 **뒤에** 적는다. 원장은 실제로 워커가 열 수 있는 자리를
        # 가리켜야 한다.
        await self._store.record_fetched(blob.content_hash, path)

        return {
            "raw_ref": blob.content_hash,
            "status": int(blob.http_status),
            "path": path,
            "bytes": incoming,
            # blob 은 통째로 있거나 없다 (I5). 잘린 본문은 재실행에서 같은
            # digest 를 내지 못하므로 증거가 될 수 없고, `fetch.py` 에는
            # 자르는 경로가 아예 없다. 계약의 출력 모양을 맞추는 자리다.
            "truncated": False,
        }

    async def _execute_coding(
        self, name: str, payload: Mapping[str, object]
    ) -> Mapping[str, Any]:
        """레지스트리 검증 -> 게이트 -> 실행. 순서가 계약이다 (CHILD-GATE).

        게이트는 **검증된** 입력을 본다. 날것을 보면 정규화 전의 경로로
        판정하게 되고, `./evidence/x` 와 `evidence/x` 가 다른 답을 받는다.
        """
        coding = self._coding
        if coding is None:
            return {"error": "tool_not_allowed"}
        try:
            validated = coding.registry.validate(
                name, dict(payload) if isinstance(payload, Mapping) else {}
            )
        except ToolValidationError as error:
            return {"error": error.reason_code}
        if coding.authorize is None:
            return {"error": "policy_gate_unbound"}
        validated, reason_code = await coding.authorize(validated)
        if reason_code is not None:
            return {"error": reason_code}
        if name == EXECUTE_TOOL:
            return await self._run_script(coding, validated)
        result = await coding.executor.execute(coding.session, validated)
        if hasattr(result, "to_mapping"):
            return strip_binary_payloads(dict(result.to_mapping()))
        return dict(result) if isinstance(result, Mapping) else {"value": result}

    async def _run_script(self, coding: CodingSurface, validated: Any) -> Mapping[str, Any]:
        """스크립트를 원장에 넣고, **그 바이트를** 돌리고, digest 를 돌려준다.

        실행기(`SandboxToolExecutor`)를 거치지 않는다. 실행기는 출력을 미리보기
        크기로 잘라 돌려주고, 잘린 출력의 digest 는 재실행이 만드는 digest 와
        다르다. 그래서 재실행기(`reexecutor.py`)가 하는 것과 **같은 호출**을
        여기서 한다 -- `session.execute` 에 argv 만, 그리고 digest 는 같은
        함수(`digest_stdout`)로.

        워커가 받는 `script_ref`·`output_digest` 를 계산 클레임에 그대로
        옮기면 된다. 워커가 해시를 스스로 계산할 필요가 없고, 계산할 수
        있다고 믿을 필요도 없다.
        """
        data = validated.input
        script_path = str(PurePosixPath(str(data["argv"][1])))
        try:
            raw = await coding.session.read_file(script_path)
        except SandboxError as error:
            return {"error": str(error) or "script_unreadable"}
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            # 원장 blob 은 텍스트다(`raw_text`). 바이트를 바꿔 넣으면 재실행이
            # 다른 스크립트를 돌린다.
            return {"error": "script_not_utf8"}
        # 돌리기 **전에** 원장에 넣는다(S8). 돌리는 사이 워커가 파일을 바꿀
        # 수 없다 -- 자식의 도구 호출은 한 번에 하나다(`ChildStepper._run_tools`).
        script_ref = await self._store.commit_script(text, path=script_path)
        result = await coding.session.execute(
            CommandRequest(
                argv=("python3", script_path),
                timeout_sec=float(data["timeout_sec"]),
                max_output_bytes=int(data["max_output_bytes"]),
            )
        )
        stdout, digest = digest_stdout(result.stdout)
        # 한도에 걸린 실행에는 digest 를 주지 않는다. 재실행기도 같은 자리에서
        # digest 를 비운다 -- 준다면 워커는 **답이 아닌 것**을 인용한다.
        complete = not result.timed_out and not result.stdout_truncated
        # S8: 인용되든 아니든 실행마다 원장에 남는다. 워커에게 결과를 주기
        # **전에** 적는다 -- 워커가 본 실행은 원장에도 있어야 한다.
        await self._store.record_execution(
            script_ref=script_ref,
            output_digest=digest if complete else None,
            exit_code=result.exit_code,
            timed_out=result.timed_out,
            stdout_truncated=result.stdout_truncated,
        )
        return {
            "exit_code": result.exit_code,
            "stdout": stdout[:_PREVIEW_CHARS],
            "stdout_preview_truncated": len(stdout) > _PREVIEW_CHARS,
            "stderr": result.stderr.decode("utf-8", errors="replace")[:_PREVIEW_CHARS],
            "timed_out": result.timed_out,
            "stdout_truncated": result.stdout_truncated,
            "script_ref": script_ref,
            "output_digest": digest if complete else None,
        }

    async def _check_claims(self, payload: Mapping[str, object]) -> Mapping[str, Any]:
        """채점기를 원장에 쓰지 않고 돌린다 (계약 §3.3).

        결과를 어디에도 기록하지 않는다 -- 확인은 제출이 아니고, 워커가
        초록을 봤다는 사실은 증거가 아니다. 판정은 오케스트레이터가 다시
        한다.
        """
        if self._grader is None:
            return {"error": "tool_not_allowed"}
        data = dict(payload) if isinstance(payload, Mapping) else {}
        results: list[dict[str, Any]] = []
        for index, claim in enumerate(parse_claims(data.get("claims"))):
            if claim.kind == "computed":
                # 채점기에 **닿지 않는다.** 닿으면 quote 규칙이 돈다.
                results.append(
                    {
                        "index": index,
                        "ok": False,
                        "codes": [COMPUTE_CHECK_UNAVAILABLE],
                    }
                )
                continue
            verdict = await self._grader.grade(claim)
            ok = bool(getattr(verdict, "ok", False))
            code = str(getattr(verdict, "code", "") or "")
            results.append(
                {
                    "index": index,
                    "ok": ok,
                    "codes": [] if ok or not code else [code],
                }
            )
        return {"results": results}

    def _submit(self, payload: Mapping[str, object]) -> Mapping[str, Any]:
        # 둘째 제출을 조용히 덮으면 첫 제출이 사라진다. 계약이 정하지 않은
        # 자리라 거절을 고른다 -- 한 턴에 제출은 하나다.
        if self._submission is not None:
            return {"error": "already_submitted"}
        self._submission = parse_submission(
            payload if isinstance(payload, Mapping) else {}
        )
        return {"status": "recorded", "claims": len(self._submission.claims)}
