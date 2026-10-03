"""트랙 J4 -- 최종 리포트를 compose 자식이 쓴다 (계약 §2 · §3.3 · 로드맵 §4.4, DECISIONS D105).

`Synthesizer.assemble` 자리를 갈아끼운다. 렌더러 · 리포트 게이트 · 재시도 루프는 그대로다 --
바뀌는 것은 **초안이 어디서 오는가** 하나다.

왜 이것이 CITE1 의 처방인가 (D104): 인용 손실의 원인은 리덕션 노드가 자식 답을 join 할 때 그
노드 **자신의** verified 클레임을 빼먹는 것이었다. 지금 조립기는 리듀스된 요약만 본다 -- 리덕션이
떨어뜨린 클레임은 조립기에 영영 닿지 않는다. compose 자식은 리듀스된 요약에 **더해** 모든 질문의
verified 클레임을 질문별 파일로 받는다(CE ③ 선행 적재 → 점진 공개). 프롬프트에 한꺼번에 싣지
않으므로 리덕션 클램프(`input_bound`)를 지나지 않는다.

지키는 것:
- **compose 는 `final_compose` 계약 그대로다**(결정 2026-09-17) -- 마크다운 + `[C:claimid]`.
  지시문은 `final_compose` 프롬프트를 렌더한 것을 `brief.md` 로 둔다. 새 문구는 파일 위치를 알리는
  머리말뿐이다
- **자식은 원장에 쓰지 않는다**(I2). 파일을 놓는 것도, 리포트를 읽는 것도 오케스트레이터 쪽 이 모듈이다
- **`check_claims.v1` 은 비용 절감이지 판정이 아니다**(계약 §3.3) -- 게이트는 오케스트레이터에 그대로 있다
- **조용한 degrade 금지** -- 제출이 없거나 리포트 파일이 없으면 `ComposeFailed` 이고 부르는 쪽이 원장에 남긴다
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from neos.coding.model.base import ToolDefinition
from neos.subagent.types import (
    ModelPin,
    ParentBriefing,
    ParentKind,
    SandboxMode,
    StepKind,
    SubagentTicket,
)

from .prompt_loader import render
from .research_session import _coding_surface, CommandLimits
from .research_tools import CHECK_TOOL, ResearchToolPort
from .sandbox import RESEARCH_PROFILE, open_question_sandbox

COMPOSE_SPEC = "compose"
CLAIMS_DIR = "claims"
BRIEF_PATH = "brief.md"
REPORT_PATH = "report.md"
INDEX_PATH = f"{CLAIMS_DIR}/INDEX.md"

_MARKER = re.compile(r"\[C:([0-9A-Za-z_-]+)\]")

#: 브리프 머리말. **이것만** 새 문구다 -- 나머지는 `final_compose` 렌더 결과 그대로다.
COMPOSE_HEADER = (
    "이 파일은 최종 리포트 작성 지시다. 아래 지시를 따라 리포트를 `report.md` 에 쓴다.\n"
    "아래 '하위 요약' 은 리듀스된 요약이라 클레임이 빠져 있을 수 있다. **모든 verified 클레임은 "
    "`claims/` 아래 질문별 파일에 있다** -- `claims/INDEX.md` 에서 시작해 필요한 파일을 읽고, "
    "`search_text.v1` 로 찾는다. 인용은 그 파일들에 있는 `[C:claimid]` 만 쓴다.\n"
    "다 쓰면 `check_claims.v1` 에 `{\"report_path\": \"report.md\"}` 를 넘겨 고아 인용과 인용 비율을 "
    "확인하고, 고친 뒤 `submit.v1` 에 `report_path` 를 담아 제출한다.\n\n---\n\n"
)


class ComposeFailed(RuntimeError):
    """compose 자식이 리포트를 내지 못했다. `reason` 이 원장에 남는 이름이다."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class ClaimFile:
    question_id: str
    question_text: str
    claims: tuple[tuple[str, str, tuple[str, ...]], ...]  # (claim_id, text, excerpts)

    @property
    def path(self) -> str:
        return f"{CLAIMS_DIR}/{self.question_id}.md"

    def render(self) -> str:
        lines = [f"# 질문 {self.question_id}", "", self.question_text.strip(), ""]
        for claim_id, text, excerpts in self.claims:
            lines.append(f"- [C:{claim_id}] {text.strip()}")
            lines.extend(f"  <evidence>{excerpt}</evidence>" for excerpt in excerpts)
        return "\n".join(lines) + "\n"


async def claim_files(ledger: Any) -> list[ClaimFile]:
    """원장의 **모든** 질문에서 verified 클레임을 모은다. 클레임이 없는 질문은 파일을 만들지 않는다.

    리듀스 트리를 거치지 않는 것이 요점이다 -- 루트·직계 자식만이 아니라 깊은 노드의 클레임도,
    리덕션이 떨어뜨린 노드 자신의 클레임도 여기 있다.
    """
    files: list[ClaimFile] = []
    for question in await ledger.questions():
        pairs = await ledger.verified_claims(question.id)
        if not pairs:
            continue
        files.append(
            ClaimFile(
                question_id=str(question.id),
                question_text=str(question.text or ""),
                claims=tuple(
                    (
                        str(claim.id),
                        str(claim.text),
                        tuple(str(row.excerpt) for row in evidence_rows),
                    )
                    for claim, evidence_rows in pairs
                ),
            )
        )
    return files


def render_index(files: Sequence[ClaimFile]) -> str:
    lines = ["# verified 클레임 색인", "", "| 파일 | 클레임 수 | 질문 |", "|---|---:|---|"]
    for item in files:
        question = item.question_text.strip().replace("\n", " ").replace("|", "/")
        lines.append(f"| `{item.path}` | {len(item.claims)} | {question} |")
    return "\n".join(lines) + "\n"


def render_brief(
    *,
    root_summary: str,
    child_blocks: Sequence[str],
    caveats: Sequence[str],
    revision_hints: Sequence[str],
) -> str:
    """`Synthesizer.assemble` 의 `render_assembly` 와 같은 자리표시자 규칙으로 `final_compose` 를 렌더한다.

    클램프는 하지 않는다 -- 자식은 파일로 읽으므로 프롬프트 한도가 이 텍스트를 자르지 않는다.
    """
    has_content = bool(root_summary.strip()) or bool(child_blocks)
    caveats_text = (
        "\n".join(caveats)
        if caveats
        else ("(없음)" if has_content else "검증된 클레임을 확보하지 못함")
    )
    return COMPOSE_HEADER + render(
        "final_compose",
        root_summary=root_summary or "(요약 없음)",
        child_summaries="\n".join(child_blocks) or "(검증된 발견 없음)",
        caveats=caveats_text,
        revision_note="\n".join(revision_hints) or "(없음 -- 첫 시도)",
    )


def check_report(text: str, verified_ids: set[str]) -> dict[str, Any]:
    """`check_claims.v1` 의 compose 모양 -- 결정론, 원장에 쓰지 않는다.

    게이트가 실제로 반려하는 두 축을 미리 보인다: 고아 인용(`E_ORPHAN_CITE`)과 인용 비율.
    """
    cited = set(_MARKER.findall(text))
    orphans = sorted(cited - verified_ids)
    used = cited & verified_ids
    available = len(verified_ids)
    return {
        "orphan_claim_ids": orphans,
        "cited_verified": len(used),
        "available_verified": available,
        "cited_ratio": (len(used) / available) if available else None,
        "uncited_claim_ids": sorted(verified_ids - used)[:50],
    }


#: compose 의 `check_claims.v1`. 조사 쪽 정의(클레임 배열)와 이름은 같고 입력이 다르다 --
#: 계약 §2 의 compose 도구 열이 같은 이름을 쓰기 때문이다.
_COMPOSE_CHECK = ToolDefinition(
    name=CHECK_TOOL,
    description=(
        "Check a report file you wrote: orphan [C:...] citations and how many "
        "verified claims it cites. Read-only; the harness grades again."
    ),
    input_schema={
        "type": "object",
        "properties": {"report_path": {"type": "string"}},
        "required": ["report_path"],
        "additionalProperties": False,
    },
)


class ComposeToolPort(ResearchToolPort):
    """조사 포트를 그대로 쓰되 `check_claims.v1` 만 리포트 검사로 바꾼다.

    `fetch.v1`·`execute.v1` 은 포트에 있어도 compose 스펙에 없으므로 `ChildStepper` 가 보여 주지
    않는다(포트 ∩ 스펙). 파일 도구와 제출은 조사 포트의 것을 **그대로** 쓴다 -- 사본을 두지 않는다.
    """

    def __init__(self, *, session: Any, verified_ids: set[str], **kwargs: Any) -> None:
        super().__init__(grader=None, **kwargs)
        self._session = session
        self._verified_ids = verified_ids

    def definitions(self) -> tuple[ToolDefinition, ...]:
        return tuple(d for d in super().definitions() if d.name != CHECK_TOOL) + (_COMPOSE_CHECK,)

    async def execute(self, name: str, input: Mapping[str, object]) -> Mapping[str, Any]:
        if name != CHECK_TOOL:
            return await super().execute(name, input)
        path = str((input or {}).get("report_path") or "").strip().lstrip("/")
        if not path:
            return {"error": "report_path_missing"}
        try:
            raw = await self._session.read_file(path)
        except Exception:  # noqa: BLE001 -- 없는 파일은 자식에게 이름으로 돌려준다
            return {"error": "report_not_found", "report_path": path}
        return check_report(raw.decode("utf-8", errors="replace"), self._verified_ids)


def build_compose_ticket(
    *,
    root_id: str,
    root_text: str,
    parent_id: str,
    model: ModelPin,
    run_id: str | None = None,
    expected_checkpoint_id: str | None = None,
) -> SubagentTicket:
    return SubagentTicket(
        parent_kind=ParentKind.DEEP_ANALYSIS,
        parent_id=parent_id,
        parent_run_id=parent_id,
        parent_tool_call_id=f"compose:{root_id}",
        spec=COMPOSE_SPEC,
        briefing=ParentBriefing(
            goal=(
                f"최종 리포트를 쓴다: {root_text.strip()}\n"
                f"`{BRIEF_PATH}` 의 지시를 따른다. 리포트는 `{REPORT_PATH}` 에 쓴다."
            ),
        ),
        model=model,
        sandbox_mode=SandboxMode.NONE,
        run_id=run_id,
        expected_checkpoint_id=expected_checkpoint_id,
    )


async def run_compose_worker(
    *,
    ledger: Any,
    provider: Any,
    root_id: str,
    root_text: str,
    root_summary: str,
    child_blocks: Sequence[str],
    caveats: Sequence[str],
    revision_hints: Sequence[str],
    runtime_factory: Any,
    model: ModelPin,
    parent_id: str,
    limits: Any,
    command_limits: CommandLimits,
    max_steps: int,
    profile: str = RESEARCH_PROFILE,
) -> tuple[str, dict[str, Any]]:
    """샌드박스를 열고, 파일을 놓고, 자식을 끝까지(걸음 상한 안에서) 돌리고, 리포트를 읽는다.

    돌려주는 것: (리포트 본문, 원장에 남길 요약). 실패는 `ComposeFailed(reason)`.
    """
    files = await claim_files(ledger)
    verified_ids = {claim_id for item in files for claim_id, _t, _e in item.claims}
    sandbox = await open_question_sandbox(
        provider, question_id=root_id, limits=limits, profile=profile
    )
    try:
        session = sandbox.session
        await session.write_file(
            BRIEF_PATH,
            render_brief(
                root_summary=root_summary,
                child_blocks=child_blocks,
                caveats=caveats,
                revision_hints=revision_hints,
            ).encode("utf-8"),
        )
        await session.write_file(INDEX_PATH, render_index(files).encode("utf-8"))
        for item in files:
            await session.write_file(item.path, item.render().encode("utf-8"))

        from .evidence_store import LedgerEvidenceStore

        port = ComposeToolPort(
            session=session,
            verified_ids=verified_ids,
            fetch_fn=_no_fetch,
            store=LedgerEvidenceStore(ledger, question_id=root_id),
            sandbox=sandbox,
            cap_bytes=0,
            coding=_coding_surface(
                ledger, question_id=root_id, session=session, limits=command_limits
            ),
        )
        runtime = runtime_factory(port)
        run_id: str | None = None
        checkpoint_id: str | None = None
        steps = 0
        tokens = 0
        while True:
            ticket = build_compose_ticket(
                root_id=root_id,
                root_text=root_text,
                parent_id=parent_id,
                model=model,
                run_id=run_id,
                expected_checkpoint_id=checkpoint_id,
            )
            outcome = await runtime.advance(ticket)
            steps += 1
            tokens += int(getattr(outcome, "tokens_delta", 0) or 0)
            if outcome.kind is not StepKind.CONTINUING:
                break
            if steps >= max_steps:
                raise ComposeFailed("compose_step_cap")
            run_id = str(getattr(outcome, "run_id", "") or "") or None
            checkpoint_id = str(getattr(outcome, "checkpoint_id", "") or "") or None

        submission = port.submission
        if submission is None:
            raise ComposeFailed("submit_not_called")
        path = (submission.report_path or REPORT_PATH).strip().lstrip("/")
        try:
            raw = await session.read_file(path)
        except Exception as exc:  # noqa: BLE001
            raise ComposeFailed("report_not_found") from exc
        text = raw.decode("utf-8", errors="replace")
        if not text.strip():
            raise ComposeFailed("report_empty")
        check = check_report(text, verified_ids)
        return text, {
            "steps": steps,
            "tokens": tokens,
            "claim_files": len(files),
            "available_verified": check["available_verified"],
            "cited_verified": check["cited_verified"],
            "orphan_claims": len(check["orphan_claim_ids"]),
        }
    finally:
        await sandbox.close()


async def _no_fetch(url: str):  # pragma: no cover -- compose 스펙에 fetch.v1 이 없다
    raise RuntimeError("compose child cannot fetch")
