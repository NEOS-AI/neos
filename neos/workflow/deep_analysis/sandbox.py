"""질문 하나에 샌드박스 하나 (계약 §3.2).

코딩 루프의 `SandboxBindingService` 를 쓰지 않는다. 그 층이 하는 일은 실행
리스를 둘러싼 펜싱과 CAS 이고, 질문에는 리스가 없다. `SandboxProvider` 는
리스를 모르므로(`create(owner_id=..., limits=...)`) provider 와 프로파일
체계는 그대로 쓴다 -- 계약 §3.2 가 금지하는 "DA 전용 경로" 는 프로파일
체계를 따로 세우는 것이지, 쓸 데 없는 리스 층을 건너뛰는 것이 아니다.

⚠️ **development 경로에는 읽기 전용 마운트가 없다.** 계약 §3.2 는
`/evidence` 를 읽기 전용 마운트로 적지만, Docker provider 에는 바인드 마운트
기능이 없고(볼륨 + tmpfs 뿐) `profile` 이라는 단어조차 나오지 않는다. 그래서
여기서는 증거를 **워크스페이스 안에 쓴다.** 워커가 그 파일을 고쳐 쓰는 것을
막는 장치는 없다 -- 막는 것은 채점기다(I4: `ComputedEvidence.inputs` 가 원장
blob 이 아니면 `E_COMPUTE_INPUT_UNFETCHED`). 진짜 읽기 전용은 관리형
provider 로 가야 생기고, 그것은 B2 게이트 뒤다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

#: 워크스페이스 상대 디렉터리. 도구 결과에 실리는 절대 경로와 구별한다.
EVIDENCE_DIR = "evidence"


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

    async def materialize_evidence(self, raw_ref: str, text: str) -> str:
        """blob 하나를 샌드박스 안에 놓고, 워커에게 줄 경로를 돌려준다.

        같은 `raw_ref` 를 두 번 놓아도 파일은 하나다 -- 내용 주소가 같으면
        바이트도 같으므로 덮어써도 달라지는 것이 없다. `/evidence` 한도
        회계가 "이미 있는 것은 새 공간을 쓰지 않는다" 로 세는 것과 같은
        방향이다.
        """
        await self.session.write_file(
            f"{EVIDENCE_DIR}/{raw_ref}.txt", text.encode("utf-8")
        )
        return evidence_path(raw_ref)

    async def close(self) -> None:
        """질문이 끝나면 샌드박스도 끝난다.

        리스가 없으므로 뒤늦게 회수해 줄 층이 없다 -- 여기서 부수지 않으면
        아무도 부수지 않는다.
        """
        await self.provider.destroy(self.sandbox_id)


async def open_question_sandbox(
    provider: Any, *, question_id: str, limits: Any
) -> QuestionSandbox:
    sandbox = await provider.create(owner_id=question_id, limits=limits)
    session = await provider.open_session(sandbox.sandbox_id)
    return QuestionSandbox(sandbox.sandbox_id, session, provider)
