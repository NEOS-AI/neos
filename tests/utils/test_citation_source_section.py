"""출처 절 조립의 공용 계약 (D-6).

**통합한 것은 렌더이지 해석이 아니다.** `deep_analysis/citation.py` 의
`[C:id]` → 원장 대조와 orphan 의미론(D10)은 그 모듈에 남는다 -- 그것은 서지
렌더링이 아니라 검증된 클레임의 주소 해석이고, 합치면 조립 재시도를 유발하는
계약이 서지 포맷터에 섞인다.

셋이 실제로 공유하던 것은 하나다: **번호를 매긴 출처 줄을 본문 끝에 붙이되
제목을 중복시키지 않는 것.** deep_analysis 는 `_SOURCE_HEADING` 정규식으로,
markdown exporter 는 무조건 붙이는 방식으로 각자 하고 있었다.
"""

from neos.utils.citations import attach_source_section, numbered_source_lines


def test_numbering_starts_at_one_and_is_dense():
    assert numbered_source_lines(["a", "b"]) == ["[1] a", "[2] b"]


def test_no_entries_leaves_the_body_untouched():
    """출처가 없으면 빈 제목만 남기지 않는다.

    빈 `## 출처` 는 "출처를 못 찾았다" 가 아니라 "출처 절이 있다" 로 읽힌다.
    """
    assert attach_source_section("본문", [], heading="## 출처") == "본문"


def test_an_existing_heading_is_reused_not_duplicated():
    """작성자가 이미 제목을 썼으면 그 아래에 붙인다.

    중복시키면 배달된 리포트에 `## 출처` 가 두 번 나오고, 둘째 블록만 각주를
    갖는다 -- 독자에게는 첫째가 비어 보인다.
    """
    body = "본문\n\n## 출처\n"
    out = attach_source_section(body, ["[1] http://x"], heading="## 출처")

    assert out.count("## 출처") == 1
    assert out.endswith("[1] http://x\n")


def test_a_missing_heading_is_added_with_a_blank_line():
    out = attach_source_section("본문", ["[1] http://x"], heading="## 출처")

    assert out == "본문\n\n## 출처\n[1] http://x\n"


def test_trailing_whitespace_in_the_body_does_not_widen_the_gap():
    """본문 끝 공백이 제목 앞 간격을 늘리면 안 된다 -- 렌더 결과가 입력의
    우연한 공백에 따라 달라지면 원장의 문자 수 지표가 흔들린다."""
    assert attach_source_section("본문\n\n\n", ["[1] u"], heading="## 출처") == (
        "본문\n\n## 출처\n[1] u\n"
    )
