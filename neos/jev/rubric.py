"""루브릭 파일 로딩과 digest -- 로드맵 §12.5 L2 · S13.

루브릭은 **파일**이다. 코드에 박힌 질문은 "어떤 질문으로 물었는가"를 커밋
메시지에만 남기고, 그러면 과거 판정을 재현할 수 없다 = 그 런은 표본이 아니다.

파일 형식은 SDK 의 질문 딕셔너리(`typesafe_sdk` 의 `NoulModel`/`ChoiceModel`/
`ScoreModel`) **그대로**다. `Questions` 가 `Mapping[str, Question]` 이고
`Question` 이 raw dict 를 받으므로 번역 층이 필요 없다 -- 그리고 번역 층이
없으면 드리프트할 층도 없다.

`prompt_loader` 와 닮았지만 사본이 아니다. 저쪽은 DA 프롬프트 디렉터리의
마크다운에 치환 자리를 채우고, 이쪽은 구조화된 질문을 읽어 **바이트 digest** 를
같이 돌려준다 -- 겹치는 동작이 없다.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

import yaml

_RUBRIC_DIR = Path(__file__).parent / "rubrics"

#: SDK 가 아는 질문 타입. 여기 없는 `type` 은 서버가 아니라 **로딩에서** 막는다.
_QUESTION_TYPES = frozenset({"noul", "choice", "score"})


@dataclass(frozen=True, slots=True)
class Rubric:
    """질문 묶음과 그 파일의 digest."""

    name: str
    questions: Mapping[str, dict[str, Any]]
    digest: str
    source: Path


def rubric_digest(raw: bytes) -> str:
    """파일 **바이트**의 sha256.

    파싱 결과가 아니라 바이트를 해싱한다. 주석과 공백도 사람이 읽는 루브릭의
    일부이고, 그것이 바뀐 판정을 "같은 루브릭"이라고 부르면 재현이 깨진다.
    """
    return hashlib.sha256(raw).hexdigest()


@lru_cache(maxsize=None)
def load_rubric(name: str) -> Rubric:
    """이름으로 루브릭을 읽는다. 경로 조립에 쓰이므로 이름을 좁게 검사한다."""
    if not name.replace("_", "").isalnum():
        raise ValueError(f"invalid rubric name: {name!r}")
    source = _RUBRIC_DIR / f"{name}.yaml"
    raw = source.read_bytes()
    parsed = yaml.safe_load(raw)
    if not isinstance(parsed, dict):
        raise ValueError(f"rubric {name!r} is not a mapping")
    questions = parsed.get("questions")
    if not isinstance(questions, dict) or not questions:
        raise ValueError(f"rubric {name!r} has no questions")
    for question_name, question in questions.items():
        if not isinstance(question, dict):
            raise ValueError(f"rubric {name!r} question {question_name!r} is not a mapping")
        if question.get("type") not in _QUESTION_TYPES:
            raise ValueError(
                f"rubric {name!r} question {question_name!r} has unknown type "
                f"{question.get('type')!r}"
            )
    return Rubric(
        name=name,
        questions=questions,
        digest=rubric_digest(raw),
        source=source,
    )
