"""L5 golden regression gate — prompt-version manifest (§10).

The append-only event log and the record/replay determinism test
(`test_golden_integration`) are the runtime side of the L5 gate. This
manifest is the *change-control* side: every prompt carries a
`<!-- version: N -->` header (§7.1) that MUST be bumped when its content
changes. Bumping a version fails this test until the manifest below is
updated — the deliberate checkpoint at which the golden replay must be
re-recorded and the improvement signals reviewed before shipping a prompt
change.
"""

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.no_db

_PROMPT_DIR = Path("neos/workflow/deep_analysis/prompts")
_VERSION_RE = re.compile(r"<!--\s*version:\s*(\d+)\s*-->")

# Prompt content baseline. Bump a value here ONLY together with an
# intentional prompt change + a fresh golden replay recording.
EXPECTED_PROMPT_VERSIONS = {
    "claim_entailment": 1,
    "decompose": 1,
    # v4 (D65, 2026-08-13): 서브질문마다 `value_est`. 채택 임계값
    # (`subq_adopt_threshold`)을 적용할 값이 없어 D11·D13 이 두 번 연기한
    # 트리 채택이 계속 불가능했다. 표본 #16 에서 고유 제안 161건이 버려지고
    # 실제 조사된 질문은 82건이었다.
    #
    # v5 (D73, 2026-08-18): `self_assessment` 규칙. 이 수 하나가 질문이 닫히는지를
    # 결정하는데(`verified_any AND max(self_assessment) >= resolve_threshold`)
    # 프롬프트는 그것을 **JSON 예시에 한 번 보여줄 뿐** 무엇인지도, 무엇을
    # 결정하는지도 말하지 않았다. 표본 #16~#19 에서 645개 질문 중 9개만 문턱을
    # 넘었고, 판정자의 반려 사유는 계속 "핵심 축이 미확인으로 남았다" 였다.
    "worker_brief": 5,
    "judge": 1,
    "node_summary": 1,
    # v1 (D68, 2026-08-15): §6.3.2 의 독립 심사자. D11 -> D13 -> D65 가 세 번
    # 미룬 자리이며, 기본은 꺼져 있다(`subq_reviewer_enabled`).
    "subq_review": 1,
    # v2 (W3-h, 2026-08-09): `{revision_note}` 슬롯 + 근거 없는 사항을 본문이
    # 아니라 한계 절에 적으라는 규칙. 앞의 것은 재시도가 판정을 되먹이게 하고,
    # 뒤의 것은 표본 #5 에서 인용 없는 문장의 최대 범주였던 부재 진술을
    # `_report_body` 가 이미 채점에서 빼는 절로 보낸다.
    #
    # v3 (W3-i, 2026-08-09): 자식 요약 블록이 질문 텍스트를 함께 싣게 되면서,
    # 그 질문을 본문에 그대로 옮겨 적고 답하라는 규칙을 더했다. 게이트의
    # "resolved 자식 질문은 모두 언급돼야 한다" 검사는 작성자가 본 적 없는
    # 문자열을 요구하고 있었다.
    #
    # v4 (2026-08-09): `## 출처` 를 모델의 필수 섹션에서 뺐다. CitationRenderer
    # 가 항상 붙이고 모델은 URL 을 모르므로, 모델이 쓰는 출처 절은 claim id
    # 나열에 그친다 -- 표본 #9 카세트에서 666자가 거기로 갔다.
    #
    # v5 (2026-08-09): 반려 사유를 "고칠 대상"으로 규정하고 직전 초안보다
    # 길게 쓰지 말라는 규칙을 더했다. `assemble` 은 직전 초안을 받지 않으므로
    # 힌트에 실린 문장이 프롬프트 안에서 "넣을 재료"로 읽혔다 -- 표본 #10 의
    # 재시도 3건 모두 주장 수가 늘고(19->60, 31->46, 16->42) 인용 비율이
    # 나빠졌다(.400/.435/.714).
    "final_compose": 5,
    "report_judge": 1,
    # v2 (2026-08-21): 근거 단위를 `run_id:seq` 이벤트 id에서 요약 필드
    # 경로(`clamp.exhausted` 같은 점 표기)로 바꿨다. `build_summary`가
    # 만드는 요약에는 이벤트 id가 아예 없어서, 순응하는 모델도 채점기가
    # id 하나를 못 찾아 후보를 전부 폐기당했다 -- 진단이 아무리 맞아도
    # 표본마다 0점이었다. 필드 경로는 모델이 실제로 읽은 요약 안에 있어
    # 기계적으로 검증 가능하다.
    "diagnose_bottleneck": 2,
}


def _prompt_version(name: str) -> int:
    text = (_PROMPT_DIR / f"{name}.md").read_text(encoding="utf-8")
    match = _VERSION_RE.search(text)
    assert match is not None, f"{name}.md is missing a <!-- version: N --> header"
    return int(match.group(1))


def test_every_prompt_has_a_version_header():
    for path in _PROMPT_DIR.glob("*.md"):
        assert _VERSION_RE.search(path.read_text(encoding="utf-8")), (
            f"{path.name} is missing a <!-- version: N --> header (§7.1)"
        )


def test_prompt_versions_match_golden_manifest():
    for name, expected in EXPECTED_PROMPT_VERSIONS.items():
        actual = _prompt_version(name)
        assert actual == expected, (
            f"prompt '{name}' is version {actual}, manifest expects {expected}. "
            "A prompt version bump is a deliberate change: update "
            "EXPECTED_PROMPT_VERSIONS, re-record the golden replay, and review "
            "the L5 improvement signals before merging."
        )


def test_manifest_covers_all_prompt_files():
    on_disk = {p.stem for p in _PROMPT_DIR.glob("*.md")}
    assert on_disk == set(EXPECTED_PROMPT_VERSIONS), (
        "a prompt file was added/removed without updating the golden manifest: "
        f"on disk={sorted(on_disk)}, manifest={sorted(EXPECTED_PROMPT_VERSIONS)}"
    )
