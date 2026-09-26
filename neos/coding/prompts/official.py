"""모델 제공사 공식 권장 문구 (로드맵 §10.5).

여기 있는 문자열은 **표현을 바꾸지 않는다.** 공식 문서가 측정한 효과는 그 문구에
붙어 있다. 문서가 갱신되면 `docs/fable-5-1-multiagent-spec.md` 를 먼저 고치고
여기를 맞춘다.

각 블록의 주석은 스펙 ID · 출처 절 · 원문을 대조한 날짜다. 이 모듈 밖의 프롬프트
문장은 NEOS 가 쓴 것이다 -- 둘을 섞지 않아야 나중에 무엇이 공식 문구인지 가릴 수
있다. `builder.py` 의 "제3자 시스템 프롬프트를 붙여넣지 않는다" 는 Claude Code·
Hermes 등의 본문에 대한 규칙이고 이 모듈에는 걸리지 않는다(§10.5).

출처: https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-fable-5-1
"""

from __future__ import annotations

# P-05 · "Tell the model what to preserve in compaction summaries" · 원문 대조 2026-09-25.
# 스펙 초안(한국어 6항목 목록)이 아니라 공식 문서의 영문 블록이다.
COMPACTION_SUMMARY_INSTRUCTION = (
    "Summarize the transcript inside <summary></summary> tags. Include relevant "
    "information in the summary such that this conversation will be continued by "
    "a new context window without needing to redo work or be reprovided with "
    "relevant constraints or context. Be sure to preserve: (1) any difficulties "
    "or problems that came up, and how they were handled or resolved; (2) any "
    "possibilities, options, or approaches that were raised, tried, or set aside, "
    "and why; (3) anything that was asked for, decided, agreed, ruled out, or "
    "established as a preference, constraint, or boundary — stated exactly; "
    "(4) exactly where things stand now — what has been covered, settled, or "
    "completed so far; (5) anything still open, unresolved, promised, or expected "
    "to happen next; (6) specific details that would be hard to reconstruct — "
    "names, numbers, dates, exact wording, links or references — kept exactly. "
    "Be complete on these even at the cost of length; keep everything else "
    "concise. Weight the two voices differently: keep what the user said, asked "
    "for, shared, or established carefully and close to their own words; your own "
    "explanations and reasoning can be condensed much further, to what they "
    "concluded or produced — as long as nothing in the six items above is "
    "dropped."
)
