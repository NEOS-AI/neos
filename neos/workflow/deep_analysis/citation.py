"""Deterministic citation resolution for verified claim markers."""

from __future__ import annotations

import re


_MARKER = re.compile(r"\[C:([0-9a-f]{8})\]")
_SOURCE_HEADING = re.compile(r"(?m)^## 출처\s*$")


class OrphanCitationError(ValueError):
    code = "E_ORPHAN_CITE"

    def __init__(self, claim_id: str) -> None:
        self.claim_id = claim_id
        super().__init__(f"{self.code}: {claim_id}")


class CitationRenderer:
    def __init__(self, ledger) -> None:
        self.ledger = ledger

    async def render(self, draft: str) -> str:
        """정본 렌더. orphan 이 하나라도 있으면 `OrphanCitationError`.

        **던지는 것이 이 메서드의 일이다.** 그 예외가 조립 재시도를 유발하고,
        D10 이 "orphan 인용은 숨기지 않고 실패한다" 로 정한 계약이다.
        최후 배달용 부분 렌더는 `render_best_effort` 로 따로 있다 -- 이 둘을
        섞으면 orphan 이 조용히 통과하고 재시도가 사라진다.
        """
        rendered, orphans = await self._resolve(draft)
        if orphans:
            raise OrphanCitationError(orphans[0])
        return rendered

    async def render_best_effort(self, draft: str) -> tuple[str, list[str]]:
        """**조립 캡이 소진된 최후 배달 전용.** 유효한 인용만 각주로 만든다.

        `render` 는 첫 orphan 에서 전체를 포기하므로, 모든 시도가 orphan 으로
        죽으면 렌더된 텍스트가 하나도 없고 호출자는 **렌더 전 draft** 를
        배달한다 -- 표본 #17 의 run `9d9daa8b` 가 각주 0개·원본 마커 32개로
        나간 경로다(ORPHAN1). 마커 32개 중 하나가 orphan 이면 나머지 31개도
        함께 잃는다.

        ⚠️ **orphan 마커는 지우지 않는다.** D10 이 `[미검증]` 치환을 기각한
        이유가 그것이다 -- 원시 마커를 없애면 "인용이 없는 문장" 과 "인용이
        깨진 문장" 이 구별되지 않고, 실패가 리포트 안에 숨는다. 남기고,
        호출자가 사유를 적는다.

        돌려주는 것: `(렌더된 텍스트, 고유 orphan claim id 목록)`.
        """
        return await self._resolve(draft)

    async def _resolve(self, draft: str) -> tuple[str, list[str]]:
        """마커를 각주로 바꾸고, 해소하지 못한 id 를 모아 함께 돌려준다.

        `render` 와 `render_best_effort` 가 이 한 구현을 공유한다 -- 갈라지면
        최후 배달이 평상 배달과 다른 서식을 내고, 원장의 `uncited_ratio` 가
        서술하는 대상이 둘로 갈린다(W3-a 가 고친 문제).
        """
        claim_ids = list(dict.fromkeys(_MARKER.findall(draft)))
        footnotes: list[str] = []
        orphans: list[str] = []
        number = 0

        for claim_id in claim_ids:
            claim = await self.ledger.get_claim(claim_id)
            if claim is None or claim.status != "verified":
                # 번호를 소비하지 않는다 -- orphan 이 각주 번호에 구멍을
                # 내면 배달된 리포트의 [1][3][4] 가 독자에게는 누락으로 보인다.
                orphans.append(claim_id)
                continue

            number += 1
            verified = await self.ledger.verified_claims(
                claim.question_id
            )
            urls: list[str] = []
            for stored_claim, evidence_rows in verified:
                if stored_claim.id != claim_id:
                    continue
                for evidence in evidence_rows:
                    if evidence.source_url not in urls:
                        urls.append(evidence.source_url)

            draft = draft.replace(f"[C:{claim_id}]", f"[{number}]")
            footnotes.append(
                f"[{number}] {'; '.join(urls) or '(출처 없음)'}"
            )

        if not footnotes:
            return draft, orphans

        footnote_block = "\n".join(footnotes)
        if _SOURCE_HEADING.search(draft):
            return f"{draft.rstrip()}\n{footnote_block}\n", orphans
        return f"{draft.rstrip()}\n\n## 출처\n{footnote_block}\n", orphans
