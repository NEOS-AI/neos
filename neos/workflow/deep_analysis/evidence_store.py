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
"""

from __future__ import annotations

from dataclasses import dataclass

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
        return FetchAdmission(
            admitted=False, bytes_charged=0, reason=CAP_REACHED
        )
    return FetchAdmission(admitted=True, bytes_charged=incoming_bytes)
