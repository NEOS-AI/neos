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

from typing import Any, Mapping, Protocol

from neos.coding.model.base import ToolDefinition

from .evidence_store import CAP_REACHED, decide_fetch_admission
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


class QuestionWorkspace(Protocol):
    """`QuestionSandbox` 가 만족한다."""

    async def materialize_evidence(self, raw_ref: str, text: str) -> str: ...


class ResearchToolPort:
    """조사 워커가 보는 DA 도구들 -- `fetch.v1` · `submit.v1` · `check_claims.v1`.

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
    ) -> None:
        self._fetch_fn = fetch_fn
        self._store = store
        self._sandbox = sandbox
        self._cap_bytes = cap_bytes
        self._grader = grader
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
        if self._grader is None:
            return (_FETCH, _SUBMIT)
        return (_FETCH, _SUBMIT, _CHECK)

    async def execute(
        self, name: str, input: Mapping[str, object]
    ) -> Mapping[str, Any]:
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

        blob = await self._fetch_fn(url)
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
