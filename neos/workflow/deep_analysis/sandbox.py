"""질문 하나에 샌드박스 하나 (계약 §3.2).

코딩 루프의 `SandboxBindingService` 를 쓰지 않는다. 그 층이 하는 일은 실행
리스를 둘러싼 펜싱과 CAS 이고, 질문에는 리스가 없다. `SandboxProvider` 는
리스를 모르므로(`create(owner_id=..., limits=...)`) provider 와 프로파일
체계는 그대로 쓴다 -- 계약 §3.2 가 금지하는 "DA 전용 경로" 는 프로파일
체계를 따로 세우는 것이지, 쓸 데 없는 리스 층을 건너뛰는 것이 아니다.

**Docker provider (development 경로, 2026-09-23).** provider 가
`readonly_evidence` 를 선언하면 샌드박스를 `profile` 과 함께 열고, 증거는
워커 컨테이너에 **읽기 전용으로만** 붙은 별도 볼륨에 놓인다(`/evidence` 와
`/workspace/evidence` 두 자리, 같은 볼륨). 쓰기는 provider 의
`write_evidence` -- 그 볼륨을 붙인 짧은 컨테이너 -- 하나뿐이다. 워커가 증거를
고쳐 쓰거나 새 파일을 끼워 넣으면 커널이 `EROFS` 로 거절한다.

그 선언이 없는 provider(메모리 provider, 관리형 provider)는 **이전과 같다** --
증거를 워크스페이스 안(`evidence/<raw_ref>.txt`)에 쓰고, 그 파일을 막는 것은
채점기뿐이다(I4: `E_COMPUTE_INPUT_UNFETCHED`). 어느 쪽으로 열렸는지는
`QuestionSandbox.evidence_readonly` 가 말한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

#: 워크스페이스 상대 디렉터리. 도구 결과에 실리는 절대 경로와 구별한다.
EVIDENCE_DIR = "evidence"

#: 조사 샌드박스의 기본 profile. 설정(`code_research.sandbox_profile`)의
#: 기본값과 같은 이름이고, 오케스트레이터는 설정 값을 명시적으로 넘긴다.
RESEARCH_PROFILE = "research-offline-v1"


def evidence_path(raw_ref: str) -> str:
    """도구 결과가 싣는 경로 (계약 §3.1).

    세션이 파일을 다루는 경로는 **워크스페이스 상대**이고, 워커에게 주는
    경로는 절대다. 둘을 섞으면 워커가 열 수 없는 경로를 받는다.
    """
    return f"/{EVIDENCE_DIR}/{raw_ref}.txt"


@dataclass(frozen=True, slots=True)
class QuestionSandbox:
    sandbox_id: str
    session: Any
    provider: Any
    #: 참이면 증거는 워커가 쓸 수 없는 볼륨에 있다(Docker). 거짓이면
    #: 워크스페이스 안이다(메모리·관리형 provider -- 이전과 같은 경로).
    evidence_readonly: bool = False

    async def materialize_evidence(self, raw_ref: str, text: str) -> str:
        """blob 하나를 샌드박스 안에 놓고, 워커에게 줄 경로를 돌려준다.

        같은 `raw_ref` 를 두 번 놓아도 파일은 하나다 -- 내용 주소가 같으면
        바이트도 같으므로 덮어써도 달라지는 것이 없다. `/evidence` 한도
        회계가 "이미 있는 것은 새 공간을 쓰지 않는다" 로 세는 것과 같은
        방향이다.
        """
        data = text.encode("utf-8")
        if self.evidence_readonly:
            # 워커 세션을 거치지 않는다. 세션의 `write_file` 은 워커의 쓰기
            # 경로이고, 그 경로는 이 볼륨에 닿지 못해야 한다.
            await self.provider.write_evidence(
                self.sandbox_id, f"{raw_ref}.txt", data
            )
        else:
            await self.session.write_file(f"{EVIDENCE_DIR}/{raw_ref}.txt", data)
        return evidence_path(raw_ref)

    async def close(self) -> None:
        """질문이 끝나면 샌드박스도 끝난다.

        리스가 없으므로 뒤늦게 회수해 줄 층이 없다 -- 여기서 부수지 않으면
        아무도 부수지 않는다.
        """
        await self.provider.destroy(self.sandbox_id)


async def open_question_sandbox(
    provider: Any,
    *,
    question_id: str,
    limits: Any,
    profile: str = RESEARCH_PROFILE,
) -> QuestionSandbox:
    """질문의 샌드박스를 연다.

    `readonly_evidence is True` 인 provider 에는 `profile` 과 증거 볼륨을
    함께 요구한다. provider 가 profile 을 강제할 수 없으면 여기서 예외가
    난다 -- 약한 샌드박스로 다시 시도하지 않는다. `is True` 로 비교하는
    이유는 가짜 객체의 아무 속성이나 참으로 읽히지 않게 하려는 것이다.
    """
    if getattr(provider, "readonly_evidence", None) is True:
        sandbox = await provider.create(
            owner_id=question_id,
            limits=limits,
            profile=profile,
            evidence=True,
        )
        readonly = True
    else:
        sandbox = await provider.create(owner_id=question_id, limits=limits)
        readonly = False
    session = await provider.open_session(sandbox.sandbox_id)
    return QuestionSandbox(
        sandbox.sandbox_id, session, provider, evidence_readonly=readonly
    )
