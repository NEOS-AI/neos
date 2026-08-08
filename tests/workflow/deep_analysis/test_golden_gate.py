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
    "worker_brief": 3,
    "judge": 1,
    "node_summary": 1,
    # v2 (W3-h, 2026-08-09): `{revision_note}` 슬롯 + 근거 없는 사항을 본문이
    # 아니라 한계 절에 적으라는 규칙. 앞의 것은 재시도가 판정을 되먹이게 하고,
    # 뒤의 것은 표본 #5 에서 인용 없는 문장의 최대 범주였던 부재 진술을
    # `_report_body` 가 이미 채점에서 빼는 절로 보낸다.
    "final_compose": 2,
    "report_judge": 1,
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
