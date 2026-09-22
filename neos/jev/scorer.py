"""TypeSafe SDK 어댑터 -- 확률을 구해 오는 유일한 자리(로드맵 §12.5 L1).

이 모듈만 SDK 를 안다. 나머지(`banding`·`gate`)는 `RiskScore` 라는 NEOS 자신의
타입만 보고, 그래서 SDK 가 바뀌어도 단조 축소 불변식은 그 자리에 남는다.

**패키지 이름 주의.** 진짜 SDK 는 `typesafe-sdk` 다. `typesafe-ai` 는 모델이
지어내는 이름을 선점당하지 않으려고 등록된 리다이렉트 shim 이고 기능이 없다.

설치된 0.7.1 기준 사실 (로드맵 §12.1 의 설계와 어긋나는 곳이 있어 적어 둔다 --
설계와 코드가 어긋나면 코드가 이긴다):

- `system_one(state, questions, *, model=..., timeout=...)` -- 앞의 둘은 **위치
  인자**이고, `questions` 는 이름 → 질문의 **매핑**이다.
- 응답형은 둘이 아니라 **셋**이다: `noul` · `choice` · `score`.
- `SystemOneResponse.model` 은 **API 가 실제로 쓴** 모델 id 다. S13 이 요구하는
  "해소된 모델 id" 는 우리가 보낸 값이 아니라 이 값이다.
"""

from __future__ import annotations

from secrets import token_hex
from typing import Any, Mapping, Protocol

from neos.jev.gate import RiskScore
from neos.jev.rubric import Rubric


class SystemOneCaller(Protocol):
    """`AsyncTypeSafeClient` 중 이 어댑터가 쓰는 부분.

    클라이언트 전체가 아니라 부르는 메서드만 요구한다 -- 테스트가 실호출 없이
    이 경계를 채울 수 있어야 하고(§12.2 ①), 채우는 쪽이 SDK 클라이언트의
    생성자 요구사항까지 흉내 낼 이유는 없다.
    """

    async def system_one(
        self,
        state: Any,
        questions: Any,
        **kwargs: Any,
    ) -> Any: ...


class TypeSafeToolRiskScorer:
    """도구 위험 루브릭을 Jev 에 물어 `RiskScore` 로 돌려준다."""

    def __init__(
        self,
        *,
        client: SystemOneCaller,
        model: str,
        rubric: Rubric,
        question: str,
        timeout_sec: float,
    ) -> None:
        self._client = client
        self._model = model
        self._rubric = rubric
        self._question = question
        self._timeout_sec = timeout_sec

    async def score_tool_risk(self, state: Mapping[str, object]) -> RiskScore:
        """한 호출에 대한 P(파괴적).

        실패를 삼키지 않는다. "대답하지 않았다"를 처리하는 곳은 `gate` 이고,
        거기서만 `jev_unavailable` 이 나온다 -- 여기서 한 번 더 삼키면 그
        이벤트가 사라진다(S12).
        """
        response = await self._client.system_one(
            {**state, "uid": self._fresh_uid()},
            self._rubric.questions,
            model=self._model,
            timeout=self._timeout_sec,
        )
        answer = response.nouls[self._question]
        return RiskScore(
            probability=answer.noul,
            model=response.model,
            rubric_digest=self._rubric.digest,
        )

    def _fresh_uid(self) -> str:
        """루브릭 digest + 난수.

        digest 를 앞에 두는 것은 사람이 원장에서 "어떤 루브릭으로 물었는가"를
        바로 읽기 위해서고, 난수를 뒤에 두는 것은 **캐시가 일관성을 대신 만들어
        주지 못하게** 하기 위해서다 -- 쿡북의 일관성 프로토콜이 신선한 uid 를
        요구하는 이유가 그것이다.
        """
        return f"{self._rubric.digest}:{token_hex(4)}"
