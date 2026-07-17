from dataclasses import dataclass

import pytest

from neos.workflow.deep_analysis.citation import (
    CitationRenderer,
    OrphanCitationError,
)


pytestmark = pytest.mark.no_db


@dataclass
class Claim:
    id: str
    question_id: str
    status: str


@dataclass
class Evidence:
    source_url: str


class FakeLedger:
    def __init__(self):
        self.claims = {
            "c1a1c1a1": Claim(
                id="c1a1c1a1",
                question_id="q1",
                status="verified",
            )
        }

    async def get_claim(self, claim_id):
        return self.claims.get(claim_id)

    async def verified_claims(self, question_id):
        claim = self.claims["c1a1c1a1"]
        return [
            (
                claim,
                [
                    Evidence("https://example.com/a"),
                    Evidence("https://example.com/a"),
                ],
            )
        ]


@pytest.mark.asyncio
async def test_verified_marker_becomes_deduplicated_numbered_source():
    draft = (
        "## 요약\nFact [C:c1a1c1a1].\n\n"
        "## 본문\nAgain [C:c1a1c1a1].\n\n"
        "## 한계와 미확인 사항\n없음\n\n## 출처"
    )

    rendered = await CitationRenderer(FakeLedger()).render(draft)

    assert "[C:" not in rendered
    assert rendered.count("[1]") == 3
    assert rendered.count("https://example.com/a") == 1
    assert rendered.count("## 출처") == 1


@pytest.mark.asyncio
async def test_orphan_marker_raises_machine_readable_error():
    with pytest.raises(OrphanCitationError) as captured:
        await CitationRenderer(FakeLedger()).render(
            "Unsupported [C:deadbeef]"
        )

    assert captured.value.code == "E_ORPHAN_CITE"
    assert captured.value.claim_id == "deadbeef"
