"""`/evidence` 한도 판단 (계약 §9 결정 4, 2026-09-20).

질문별 blob 합계가 한도에 닿으면 **새 fetch 를 거절한다.** 이미 있는 blob 은
빼지 않는다 -- 축출하면 사라진 blob 을 `inputs` 로 가진 계산 클레임이 채점 때
`E_COMPUTE_INPUT_UNFETCHED` 로 **나중에 조용히** 죽는다. 제출될 때는 멀쩡했던
증거가 뒤늦게 무효가 되는 모양이고, 이 저장소는 그때마다 "조용히 바뀌는 것이
시끄럽게 깨지는 것보다 위험하다" 쪽을 골라 왔다.

**왜 순수 함수인가.** 원장 경로는 Postgres 를 요구해서 개발 기계에서 돌지
않는다. 그런데 이 결정의 전부는 "무엇을 얼마나 청구하는가" 이므로, 그 부분만
DB 없이 고정해 두면 한도 정책은 언제나 검사할 수 있다. 원장 쪽에는 세는 일만
남긴다.

**그 "세는 일" 이 `LedgerEvidenceStore` 다.** 둘이 한 파일에 있는 이유는 같은
관심사이기 때문이고, 나뉘는 지점은 Postgres 가 필요한가 하나다 -- 판단은
순수하고, 적용은 원장을 만진다. 적용 쪽도 원장 자리에 가짜를 넣으면 **무엇을
어떤 순서로 부르는지**까지는 DB 없이 고정할 수 있다.

이 어댑터는 **오케스트레이터 쪽**이다. 원장을 들고 있어도 되고, 그래야 워커
쪽 포트(`ResearchToolPort`)가 원장을 모를 수 있다 (I2 · P2).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .script_blob import script_blob

#: 한도에 닿아 거절할 때 원장에 남기는 이유. 거절은 조용하면 안 된다 --
#: 조사가 멈춘 자리가 보여야 멈췄다는 것을 알 수 있다.
CAP_REACHED = "evidence_cap_reached"


@dataclass(frozen=True, slots=True)
class FetchAdmission:
    admitted: bool
    bytes_charged: int
    reason: str = ""


def decide_fetch_admission(
    *,
    cap_bytes: int,
    spent_bytes: int,
    incoming_bytes: int,
    already_stored: bool,
) -> FetchAdmission:
    """이 fetch 를 `/evidence` 에 들일 것인가, 그리고 몇 바이트를 청구할 것인가.

    `already_stored` 는 `Ledger._store_blob` 이 `(run_id, content_hash)` 로
    일찍 돌아가는 경우다. 그 바이트를 또 세면 **쓰지도 않은 한도**를 까먹는다
    -- 미러 URL 이 같은 본문으로 dedup 되는 것은 의도된 동작이라(`fetch.py`
    의 `_blob_hash`) 드문 경로가 아니다. 이미 있는 것을 다시 읽는 데에는
    새 공간이 들지 않으므로, 한도가 이미 찼더라도 거절하지 않는다.

    한도를 **넘지** 않으면 통과다. 정확히 채우는 fetch 는 들어온다 -- 한도는
    "넘지 않는다" 이지 "닿지 않는다" 가 아니다.

    blob 은 통째로 있거나 없다. 남은 공간에 맞춰 잘라 담지 않는다 -- 잘린
    본문은 재실행에서 같은 digest 를 내지 못하므로 증거가 될 수 없다(I5).
    """
    if already_stored:
        return FetchAdmission(admitted=True, bytes_charged=0)
    if spent_bytes + incoming_bytes > cap_bytes:
        return FetchAdmission(admitted=False, bytes_charged=0, reason=CAP_REACHED)
    return FetchAdmission(admitted=True, bytes_charged=incoming_bytes)


class LedgerEvidenceStore:
    """위 판단을 실제 원장에 적용한다. `ResearchToolPort` 의 `EvidenceStore`.

    쓴 바이트를 `DAQuestion.evidence_bytes` 에 두는 이유는 `spent_tokens` 와
    같다 -- run 이 재개돼도 한도를 잊지 않아야 하므로 메모리가 아니라 행에
    있어야 한다.
    """

    def __init__(self, ledger: Any, *, question_id: str) -> None:
        self._ledger = ledger
        self._question_id = question_id
        # 이 샌드박스에 지금 놓인 증거 -- 복원한 것과 이번에 가져온 것.
        # 실행 기록(`record_execution`)이 싣는다.
        self._present: list[str] = []

    async def _question(self) -> Any:
        question = await self._ledger.get_question(self._question_id)
        if question is None:
            # 0 으로 읽으면 한도가 조용히 사라진다. 셀 수 없으면 멈춘다.
            raise KeyError(self._question_id)
        return question

    async def spent_bytes(self) -> int:
        return int((await self._question()).evidence_bytes)

    async def is_stored(self, content_hash: str) -> bool:
        return await self._ledger.get_blob(content_hash) is not None

    async def commit(self, blob: Any, *, bytes_charged: int) -> None:
        """blob 을 먼저 넣고, 그 다음에 바이트를 청구한다.

        순서가 뒤집히면 커밋이 실패했을 때 한도만 깎인 채 증거는 없다.

        이미 있는 blob 이어도 `commit_blobs` 를 부른다 -- 중복 판단은 원장의
        `_store_blob` 이 `(run_id, content_hash)` 로 이미 하고 있고, 여기서
        한 번 더 판단하면 같은 규칙이 두 곳에 생긴다.
        """
        await self._ledger.commit_blobs([blob])
        question = await self._question()
        question.evidence_bytes = int(question.evidence_bytes) + bytes_charged
        await self._ledger.db.flush()

    async def restore(self, sandbox: Any) -> list[str]:
        """앞 라운드가 이 질문에 가져온 증거를 새 샌드박스에 다시 놓는다 (J1.5).

        질문의 샌드박스는 라운드마다 새로 열린다. 다시 놓지 않으면 `/evidence`
        는 라운드마다 비고, 계산 클레임은 **ID 를 볼 수 있는 둘째 라운드부터만**
        쓸 수 있으므로(briefing) 계산이 읽을 증거는 언제나 사라진 뒤다. 결정
        4(계약 §9)의 "그 집합은 줄지 않는다" 가 라운드 경계에서 깨지는 자리다.

        다시 청구하지 않고(이미 냈다), 다시 기록하지도 않는다(가져온 것이
        아니다). 원장 접근자는 방어적으로 읽는다 -- 최소 test double 은
        복원 없이 이전과 같다.
        """
        refs_fn = getattr(self._ledger, "sandbox_evidence_refs", None)
        refs = await refs_fn(self._question_id) if refs_fn is not None else []
        restored: list[str] = []
        for raw_ref in refs:
            blob = await self._ledger.get_blob(raw_ref)
            if blob is None:
                # 기록은 커밋 뒤에만 적히므로 여기 오면 원장이 깨진 것이다.
                # 조용히 건너뛰면 그 증거를 읽는 계산이 이유 없이 죽는다.
                raise KeyError(raw_ref)
            await sandbox.materialize_evidence(raw_ref, blob.raw_text or "")
            restored.append(raw_ref)
        self._note_present(restored)
        return restored

    async def commit_script(self, text: str, *, path: str) -> str:
        """워커가 돌리려는 스크립트를 원장 blob 으로 넣고 주소를 돌려준다 (J1.5).

        **돌리기 전에** 넣는다 -- 원장에 없는 바이트로 나온 출력은 계산
        클레임의 근거가 될 수 없다(계약 §4 `script_ref`, S8). 실행이 실패해도
        blob 은 남는다; 남는 것은 무해하고, 빠지는 것은 재실행을 불가능하게
        만든다.

        `/evidence` 한도에 **청구하지 않는다.** 스크립트는 `/evidence` 에
        놓이지 않고, 한도가 막으려는 것은 원문 수집의 폭이다. 워커가 쓴
        스크립트로 수집 한도가 닳으면 조사가 엉뚱한 이유로 멈춘다.
        """
        blob = script_blob(text, question_id=self._question_id, path=path)
        await self._ledger.commit_blobs([blob])
        return blob.content_hash

    async def record_fetched(self, raw_ref: str, path: str) -> None:
        """증거가 샌드박스에 나타났다고 원장에 적는다 (계약 §6).

        커밋과 따로인 이유는 **경로가 그때 생기기 때문**이다 -- blob 이
        원장에 들어간 뒤에야 샌드박스에 놓이고, 그 순서가 계약이다.

        포트가 아니라 여기서 적는 이유는 I2 다. 포트는 원장을 모른다.
        """
        await self._ledger.log(
            "evidence_fetched_for_sandbox",
            self._question_id,
            {"raw_ref": raw_ref, "path": path},
        )
        self._note_present([raw_ref])

    def _note_present(self, refs: list[str]) -> None:
        for raw_ref in refs:
            if raw_ref not in self._present:
                self._present.append(raw_ref)

    async def record_execution(
        self,
        *,
        script_ref: str,
        output_digest: str | None,
        exit_code: int | None,
        timed_out: bool,
        stdout_truncated: bool,
    ) -> None:
        """`execute.v1` 한 번을 원장에 적는다 (S8, 2026-09-28).

        스크립트 바이트는 `commit_script` 가 이미 넣었다. 그것만으로는 **그
        실행이 무엇을 냈는지**가 원장에 없다 -- 클레임이 인용한 실행만
        `output_digest` 를 남겼다. 인용되지 않은 실행(버린 시도, 틀린 계산)이
        사라지면 원장은 워커가 무엇을 해 봤는지 말하지 못한다.

        `evidence_refs` 는 그 실행 때 샌드박스에 **놓여 있던** 증거다. 스크립트가
        실제로 연 파일은 샌드박스 밖에서 알 수 없으므로 상한 집합이다 --
        입력은 이 안에 있다. 클레임의 `inputs` 가 정확한 목록을 따로 싣는다.

        `output_digest` 가 None 이면 한도에 걸린 실행이다(답을 내지 못했다).
        """
        await self._ledger.log(
            "script_executed",
            self._question_id,
            {
                "script_ref": script_ref,
                "output_digest": output_digest,
                "exit_code": exit_code,
                "timed_out": timed_out,
                "stdout_truncated": stdout_truncated,
                "evidence_refs": list(self._present),
            },
        )
