"""exporters 의 출처 렌더 -- 이 디렉터리의 첫 테스트다.

**착수 배경.** 로드맵 §11.2 가 "exporters 가 `UniversalCitationTracker` 를 안 쓰고
링크 목록을 손으로 만든다" 를 남은 위생 항목으로 적었다. 실측해 보니 그 전제가
틀렸다 -- §11.2 가 이미 한 번 저지른 것과 같은 오류다(파일을 센 것이지 재료를 잰
것이 아니다):

- `ResearchReport.citations` 의 원소는 `{title, url, source}` 뿐이다
  (`export_service._extract_citations`). tracker 는 APA/MLA/Chicago **서지**
  엔진이라 저자·발행연도·접근일을 요구한다. 통합하려면 없는 값을 지어내야 하고,
  이 저장소는 그것을 금지한다.

**대신 실측이 셋을 드러냈다.**

1. `neos/exporters/` 를 임포트하는 테스트가 저장소 전체에 **0건**이었다.
   출력 형식을 바꾸는 작업을 안전망 없이 할 뻔했다.
2. `canvas_exporter` 는 `report.citations` 를 **한 번도 참조하지 않는다** --
   차트와 "소스 관계도" 는 그리면서 출처 목록은 통째로 빠뜨린다.
3. `html_exporter` 가 URL 을 **이스케이프도 스킴 검증도 없이** `href` 에 넣는다.
   같은 저장소의 `canvas_exporter._safe_url` 이 정확히 그것을 막는 헬퍼이고
   주석이 `CR-P6-02: javascript: URI 차단` 이라고 적는다 -- 그 수정이 한 호출부에만
   도착했다. citations 의 url 은 웹 검색 결과에서 오는 **외부 데이터**다.
"""

import pytest

from neos.exporters.base import ResearchReport
from neos.exporters.canvas_exporter import CanvasExporter
from neos.exporters.html_exporter import HTMLExporter
from neos.exporters.markdown_exporter import MarkdownExporter


def _report(citations) -> ResearchReport:
    return ResearchReport(
        session_id="s1",
        query="테스트 질의",
        response="본문",
        citations=citations,
    )


@pytest.mark.asyncio
async def test_markdown_numbers_the_sources_it_was_given() -> None:
    """현재 출력을 고정한다 -- 통합을 하든 안 하든 이 핀이 먼저 있어야 한다."""
    out = (
        await MarkdownExporter().export(
            _report(
                [
                    {"title": "첫 자료", "url": "https://a.example/1"},
                    {"title": "둘째 자료", "url": "https://b.example/2"},
                ]
            )
        )
    ).decode()

    assert "## Sources" in out
    assert "1. [첫 자료](https://a.example/1)" in out
    assert "2. [둘째 자료](https://b.example/2)" in out


@pytest.mark.asyncio
async def test_html_escapes_the_title_it_renders() -> None:
    """제목 쪽 이스케이프는 이미 있다 -- 회귀 방지로 고정한다."""
    out = (
        await HTMLExporter().export(
            _report([{"title": "<script>alert(1)</script>", "url": "https://a.example"}])
        )
    ).decode()

    assert "<script>alert(1)</script>" not in out
    assert "&lt;script&gt;" in out


@pytest.mark.asyncio
async def test_html_does_not_emit_a_javascript_url_in_the_href() -> None:
    """`javascript:` URL 이 그대로 실리면 열어 본 사람의 브라우저에서 돈다.

    `canvas_exporter._safe_url` 이 같은 저장소에서 이미 막는 것이고
    (`CR-P6-02`), citations 의 url 은 검색 결과에서 온 외부 데이터다.
    """
    out = (
        await HTMLExporter().export(
            _report([{"title": "낚시", "url": "javascript:alert(document.cookie)"}])
        )
    ).decode()

    assert "javascript:" not in out


@pytest.mark.asyncio
async def test_html_url_cannot_break_out_of_the_href_attribute() -> None:
    """따옴표가 살아서 나가면 속성을 닫고 새 속성을 붙일 수 있다."""
    out = (
        await HTMLExporter().export(
            _report(
                [
                    {
                        "title": "낚시",
                        "url": 'https://a.example" onmouseover="alert(1)',
                    }
                ]
            )
        )
    ).decode()

    assert 'onmouseover="alert(1)"' not in out


@pytest.mark.asyncio
async def test_canvas_renders_sources_through_the_skill_renderer() -> None:
    """canvas 는 **네 번째 렌더 자리**를 거친다 -- `neos/exporters/` 밖이다.

    `rg citations neos/exporters/` 로는 canvas 가 안 걸려서 "출처를 빠뜨린다" 로
    읽었는데 **틀렸다.** `CanvasExporter.export` 가
    `neos.skills.builtin.canvas.renderers.StructuredMarkdownRenderer` 에 위임하고
    거기서 출처가 만들어진 뒤 `_markdown_to_html` 로 변환된다.

    §11.2 가 렌더 경로를 셋으로 셌던 목록에 이 자리는 없다. 파일 이름으로
    세면 위임 뒤에 있는 자리는 보이지 않는다.
    """
    out = (
        await CanvasExporter().export(
            _report([{"title": "인용 자료", "url": "https://a.example/1"}])
        )
    ).decode()

    assert "인용 자료" in out
    assert "https://a.example/1" in out


@pytest.mark.asyncio
async def test_canvas_neutralizes_a_javascript_url() -> None:
    """canvas 경로는 `_safe_url` 을 거치므로 이미 안전하다 -- 회귀 방지로 고정한다.

    이 테스트가 있는 이유는 html 쪽과의 **대조**다: 같은 위험을 한쪽은 막고
    다른 쪽은 막지 않았다는 사실이 이 항목의 실제 내용이다.
    """
    out = (
        await CanvasExporter().export(
            _report([{"title": "낚시", "url": "javascript:alert(document.cookie)"}])
        )
    ).decode()

    assert "javascript:alert" not in out


@pytest.mark.asyncio
async def test_html_search_results_urls_are_also_neutralized() -> None:
    """🔴 같은 파일에 같은 구멍이 하나 더 있었다.

    citations 만 고치고 끝냈다면 `search_results` 블록이 그대로 남았다 --
    같은 외부 데이터(검색 결과)를 같은 방식으로 `href` 에 넣는다. 게다가 이쪽은
    URL 을 **본문 텍스트로도** 출력하므로 이스케이프가 두 자리에서 필요하다.
    """
    report = ResearchReport(
        session_id="s1",
        query="q",
        response="본문",
        search_results=[
            {
                "title": "낚시",
                "url": "javascript:alert(1)",
                "content": "내용",
            }
        ],
    )
    out = (await HTMLExporter().export(report)).decode()

    assert "javascript:alert(1)" not in out
