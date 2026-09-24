"""루브릭은 파일이고, digest 를 가진다 -- 로드맵 §12.5 L2 · S13.

루브릭을 코드에 문자열로 박으면 "어떤 질문으로 물었는가"가 커밋 메시지에만
남는다. 파일로 두고 **내용의 digest 를 판정 이벤트에 실어야** 과거 판정을
재현할 수 있다.

파일 형식은 SDK 의 질문 딕셔너리(`NoulModel`/`ChoiceModel`) **그대로**다.
번역 층을 두지 않는 것이 요점이다 -- 번역이 있으면 그 층이 드리프트한다.
"""

from __future__ import annotations

import pytest

from neos.jev.rubric import Rubric, load_rubric, rubric_digest

pytestmark = pytest.mark.no_db


def test_the_tool_risk_rubric_loads() -> None:
    rubric = load_rubric("tool_risk")
    assert isinstance(rubric, Rubric)
    assert rubric.questions, "루브릭에 질문이 하나도 없다"


def test_every_question_is_a_shape_the_sdk_accepts() -> None:
    """`type` 이 빠진 질문은 SDK 가 아니라 **서버**에서 터진다 -- 여기서 잡는다."""
    rubric = load_rubric("tool_risk")
    for name, question in rubric.questions.items():
        assert question.get("type") in {"noul", "choice", "score"}, name


def test_the_digest_is_sha256_of_the_file_bytes() -> None:
    rubric = load_rubric("tool_risk")
    assert len(rubric.digest) == 64
    assert rubric.digest == rubric_digest(rubric.source.read_bytes())


def test_a_changed_rubric_changes_the_digest() -> None:
    """digest 가 내용을 따라오지 않으면 S13 은 종이다."""
    assert rubric_digest(b"a") != rubric_digest(b"a ")


def test_an_unknown_rubric_name_is_refused() -> None:
    with pytest.raises(ValueError, match="rubric"):
        load_rubric("../../etc/passwd")
