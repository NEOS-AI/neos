"""Shared component contracts for the Deep Analysis Harness."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal


class Effort(Enum):
    SCOUT = "scout"
    DIG = "dig"
    SPLIT = "split"
    SYNTH = "synth"


@dataclass
class Assignment:
    question_id: str
    brief: str
    effort: Effort
    repairs: list = field(default_factory=list)
    # 검색어로 쓸 원 질문. brief는 템플릿이 렌더링된 프롬프트 전문(~1KB)이라
    # 그대로 검색하면 결과가 0건이다. 비어 있으면 워커가 brief로 되돌아간다.
    question_text: str = ""


@dataclass
class ProposedBlob:
    """Content-addressed fetch output proposed by a stateless worker."""

    content_hash: str
    source_url: str
    http_status: int
    raw_text: str


@dataclass
class ProposedEvidence:
    source_url: str
    excerpt: str
    raw_ref: str


@dataclass
class ComputedEvidence:
    """계산 클레임의 증거 (계약 §4).

    quote 클레임이 `ProposedEvidence`(출처·발췌·raw_ref)를 갖듯, 계산
    클레임은 **재현에 필요한 전부**를 갖는다 -- 스크립트 바이트, 입력 blob,
    전제 클레임, 런타임, 그리고 정규화된 stdout 의 digest.

    채점은 J2 지만 모양은 제출이 받는 순간 필요하다. 여기를 비워 두면
    `submit.v1` 이 계산 클레임을 아예 받지 못한다.
    """

    script_ref: str
    inputs: list[str] = field(default_factory=list)
    premises: list[str] = field(default_factory=list)
    runtime: dict[str, Any] = field(default_factory=dict)
    output_digest: str = ""
    claimed_value: str = ""


@dataclass
class ProposedClaim:
    text: str
    confidence: float
    evidence: list[ProposedEvidence] = field(default_factory=list)
    #: 계약 §3.4. 기존 경로가 만드는 클레임은 전부 quote 라 기본값이 그것이다 --
    #: 이 필드가 생겨도 플래그 off 경로의 동작은 달라지지 않는다. `ProposedClaim`
    #: 은 통째로 직렬화되는 곳이 없고(`asdict` 대상이 아니다), 원장은
    #: `_upsert_claim` 에서 필드를 하나씩 읽는다.
    kind: Literal["quote", "computed"] = "quote"
    #: `kind == "computed"` 일 때만 채워진다.
    computation: ComputedEvidence | None = None


@dataclass
class EntailmentOutcome:
    """Result of applying one entailment batch.

    ``discarded`` carries the claims the batch dropped so the orchestrator can
    record them. A ``narrow`` action is not a discard — the narrowed claim
    appears in ``refined``.
    """

    refined: list[ProposedClaim] = field(default_factory=list)
    discarded: list[ProposedClaim] = field(default_factory=list)


@dataclass
class ProposedSubquestion:
    """조사 중 워커가 "이것도 봐야 한다" 고 남긴 질문.

    `value_est` 는 워커가 스스로 매긴다. 원 설계 §6.3.2 는 중복 병합과 상대
    value 산정을 **독립 LLM 심사자**에게 맡기는데, 그 심사자는 별도 프롬프트와
    검증 하네스를 요구해 D11 · D13 이 두 번 연기했다. 자기 채점은 그보다
    공정하지 않지만 **공짜**이고, 중복 제거는 오케스트레이터에서 결정론적으로
    한다(D65).
    """

    text: str
    value_est: float = 0.0


@dataclass
class RepairResult:
    claim_id: str
    action: Literal["fixed", "weakened", "abandoned"]
    new_text: str | None = None
    new_evidence: list[ProposedEvidence] = field(default_factory=list)


#: `WorkerResult.entailment_skipped` 의 어휘 (C4).
#:
#: 넷은 호출이 실패한 것이고 마지막 하나는 **성공한 호출의 응답 모양이 틀린**
#: 것이다. 이 구별이 실질적인 이유: 앞의 넷은 재시도나 상한 조정으로 줄일 수
#: 있고, `schema_invalid` 는 프롬프트나 파서의 문제라 고칠 곳이 다르다.
#: 옛 단일 사유 `"entailment_unavailable"` 은 다섯을 전부 같은 이름으로 적었다.
ENTAILMENT_BUDGET_EXHAUSTED = "budget_exhausted"
ENTAILMENT_PROVIDER_FAILED = "provider_failed"
ENTAILMENT_TRUNCATED = "truncated"
ENTAILMENT_UNPARSEABLE = "unparseable"
ENTAILMENT_SCHEMA_INVALID = "schema_invalid"

ENTAILMENT_SKIP_CAUSES = frozenset(
    {
        ENTAILMENT_BUDGET_EXHAUSTED,
        ENTAILMENT_PROVIDER_FAILED,
        ENTAILMENT_TRUNCATED,
        ENTAILMENT_UNPARSEABLE,
        ENTAILMENT_SCHEMA_INVALID,
    }
)


@dataclass
class WorkerResult:
    question_id: str
    status: Literal["completed", "partial", "failed"]
    claims: list[ProposedClaim] = field(default_factory=list)
    discarded_claims: list[ProposedClaim] = field(default_factory=list)
    blobs: list[ProposedBlob] = field(default_factory=list)
    repairs: list[RepairResult] = field(default_factory=list)
    proposed_subquestions: list[ProposedSubquestion] = field(default_factory=list)
    dead_ends: list[str] = field(default_factory=list)
    tokens_spent: int = 0
    model: str = ""
    self_assessment: float = 0.0
    fail_reason: str = ""
    confidence_clamped_count: int = 0
    confidence_clamped_by_source_count: dict[str, int] = field(default_factory=dict)
    # entailment 배치가 필터를 적용하지 못하고 원본 claim을 그대로 통과시켰다면
    # **왜** 그랬는가 (`ENTAILMENT_SKIP_CAUSES` 중 하나), 정상 동작했으면 `None`.
    #
    # discard 0건의 두 원인("버릴 게 없었다" / "필터가 안 돌았다")을 가르는 것이
    # 원래 목적이었고 그때는 bool 이었다. 그런데 후자가 다시 다섯 갈래로
    # 갈라진다 -- 그중 넷은 호출이 실패한 것이고 하나(`schema_invalid`)는
    # 호출이 성공한 것이라, 뭉뚱그리면 C1 재측정이 "필터가 왜 안 돌았는지"에
    # 답하지 못한다 (C4).
    #
    # `str | None` 이라 진리값은 bool 시절과 같다 -- `if result.entailment_skipped:`
    # 로 읽는 호출부가 그대로 동작한다.
    entailment_skipped: str | None = None
    # 1차 출처 증강 질의가 무엇을 바꿨는가. 키:
    # `base_candidates`/`base_tier1` (기저 질의가 가져온 것),
    # `added_candidates`/`added_tier1` (증강 질의만 가져온 것),
    # `selected_tier1` (슬라이스를 통과해 실제 fetch 된 tier1 수).
    #
    # `added_tier1` 이 표본 전체에서 0 이면 평문 키워드 증강은 효과가 없고
    # `site:` 문법이나 다른 기전이 필요하다는 뜻이다 -- 이 필드가 있어야
    # 그 반증이 가능하다.
    search_augmentation: dict[str, int] = field(default_factory=dict)
    # HTTP 시도 하나당 한 칸 (트랙 A D2). 키: `ok`/`retrying`/`exhausted`/
    # `refused`/`transport_error`, 그리고 각각의 `_<status>` 판.
    #
    # 이 필드가 없던 시절 `fetch_url` 에는 재시도가 없었고 429 한 번이 그
    # 출처를 영구히 잃게 만들었는데, 잃었다는 사실이 어디에도 남지 않았다 --
    # 실패한 fetch 는 `raw_text=""` 인 blob 이 되고 그것은 **정말로 빈
    # 페이지**와 구별되지 않는다. D2 가 "403 잔존·429 backoff 없음" 으로
    # 적어둔 두 질문은 이 수 없이는 답이 나오지 않는다.
    retrieval_outcomes: dict[str, int] = field(default_factory=dict)
    # Folded explore-child text. Unverified — graders remain the only
    # verified path. Empty on the Worker / call_json path.
    unverified_brief: str = ""
    # Child pointer for the orchestrator to log after gather (P2).
    subagent_run_id: str = ""
    subagent_checkpoint_id: str = ""
    subagent_step_kind: str = ""
    # 트랙 J. compose 자식이 워크스페이스에 쓴 리포트 경로 (계약 §3.4).
    # `code_worker_submitted` 가 "report_path 여부" 를 싣는데, 그 값이 결과에
    # 없으면 있지도 않은 것을 없다고 적게 된다. research·analyze 에서는 None.
    report_path: str | None = None


@dataclass
class Verdict:
    ok: bool
    code: str = ""
    detail: str = ""
    salvage: str | None = None
    label: str | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)
    # What the next attempt should change, in the rejected draft's own words
    # (W3-h). In-process only: the orchestrator logs `code` and
    # `diagnostics`, never this, so report prose stays out of the ledger.
    revision_hints: list[str] = field(default_factory=list)
    # 이 판정을 만드는 데 판정자(judge)가 쓴 토큰 (C3-m1). 기본값 0 은
    # `Verdict` 를 짓는 곳이 결정론 채점기 등 여럿이라 전부 고칠 일이 아니기
    # 때문이다 -- 판정자가 관여하지 않은 verdict 은 0 이 정확한 값이다.
    # `AgenticGrader` 가 채우는 값은 `_diagnostics()` 의 `judge_tokens` 와
    # 항상 같아야 한다: 두 수가 갈라지면 원장(`judge_tokens` 로 보이는 값)과
    # 실제 청구액(`tokens_spent` 로 나가는 값)이 서로 다른 이야기를 하게 된다.
    tokens_spent: int = 0


@dataclass
class ConflictNote:
    claim_a: str
    claim_b: str
    nature: str


@dataclass
class NodeSummary:
    question_id: str
    answer: str
    key_claim_ids: list[str]
    confidence: float
    caveats: list[str]
    # The question this answers, in the words it was asked (W3-i). Optional
    # because `reduce_node` builds summaries before the orchestrator pairs
    # them with the ledger's questions; `_child_summaries` fills it in.
    question_text: str = ""
    # The ledger's status for that question, filled in beside the text. The
    # report gate demands coverage of `resolved` children specifically, so
    # the harness needs to know which ones those are (W3-l).
    question_status: str = ""
    conflicts: list[ConflictNote] = field(default_factory=list)
