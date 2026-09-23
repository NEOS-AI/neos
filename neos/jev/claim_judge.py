"""Choice 판정 경로 -- 로드맵 §12.5 L4 (Jev-as-Judge 오프라인 백테스트).

`scorer.py` 의 Noul 도구 위험 경로와 **나란히** 선다. 그 경로를 고치지 않고,
같은 SDK 경계(`SystemOneCaller`)와 같은 uid 규율(digest + 난수)을 쓴다.

**역할 라우팅에 등록하지 않는다**(§9). 이 모듈을 부르는 것은 오프라인
백테스트 스크립트뿐이고, 원장의 판정은 여전히 `AgenticGrader` 가 낸다.
`DeterministicGrader` 는 어떤 일치율이 나와도 대체 대상이 아니다.
"""

from __future__ import annotations

from dataclasses import dataclass
from secrets import token_hex
from typing import Sequence

from neos.jev.rubric import Rubric
from neos.jev.scorer import SystemOneCaller

#: 판정자 프롬프트가 증거가 하나도 없을 때 넣는 문자열.
NO_EVIDENCE = "(증거 없음)"


def render_evidence_block(excerpts: Sequence[str]) -> str:
    """`AgenticGrader.grade()` 가 판정자 프롬프트에 넣는 증거 블록과 같은 문자열.

    사본이다 -- 그 grader 는 이 렌더링을 인라인으로 한다. 그래서 두 쪽이
    같은 바이트를 낸다는 것을 `tests/jev/test_claim_judge.py` 가 **판정자에게
    실제로 간 프롬프트를 붙잡아** 확인한다. 한쪽만 바뀌면 거기서 빨개진다.
    """
    return "\n".join(f"<evidence>{excerpt}</evidence>" for excerpt in excerpts) or NO_EVIDENCE


@dataclass(frozen=True, slots=True)
class ClaimJudgement:
    """Jev 의 Choice 답 하나. S13: 해소된 모델 id 와 루브릭 digest 를 같이 싣는다."""

    choice: str
    probabilities: dict[str, float]
    confidence: float
    model: str
    rubric_digest: str
    uid: str


class TypeSafeClaimJudge:
    """클레임 판정 루브릭을 Jev 에 Choice 로 묻는다."""

    def __init__(
        self,
        *,
        client: SystemOneCaller,
        model: str,
        rubric: Rubric,
        question: str,
        timeout_sec: float,
    ) -> None:
        if rubric.questions.get(question, {}).get("type") != "choice":
            raise ValueError(f"rubric {rubric.name!r} question {question!r} is not a choice")
        self._client = client
        self._model = model
        self._rubric = rubric
        self._question = question
        self._timeout_sec = timeout_sec

    @property
    def labels(self) -> tuple[str, ...]:
        return tuple(self._rubric.questions[self._question]["criteria"])

    async def judge(self, claim_text: str, excerpts: Sequence[str]) -> ClaimJudgement:
        """판정자가 본 것(클레임 + 증거 블록)만 보내고 Choice 답을 돌려준다.

        실패를 삼키지 않는다 -- 호출부가 실패를 **센다**. 여기서 삼키면
        "대답하지 않았다"가 행렬에서 조용히 빠진다.
        """
        uid = f"{self._rubric.digest}:{token_hex(4)}"
        response = await self._client.system_one(
            {
                "uid": uid,
                "claim": claim_text,
                "evidence": render_evidence_block(excerpts),
            },
            self._rubric.questions,
            model=self._model,
            timeout=self._timeout_sec,
        )
        answer = response.choices[self._question]
        return ClaimJudgement(
            choice=answer.choice,
            probabilities=dict(answer.probabilities),
            confidence=answer.confidence,
            model=response.model,
            rubric_digest=self._rubric.digest,
            uid=uid,
        )
