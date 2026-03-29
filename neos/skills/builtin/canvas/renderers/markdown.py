"""StructuredMarkdownRenderer — 연구 결과를 구조화된 마크다운으로 렌더링

섹션 헤더, 주요 발견 요약, 인용 목록, 품질 정보를 포함한
표준 마크다운 캔버스를 생성한다. 외부 의존성 없음.
"""

from neos.exporters.base import ResearchReport


class StructuredMarkdownRenderer:
    """ResearchReport → 구조화된 마크다운 문자열 변환기."""

    def render(self, report: ResearchReport) -> str:
        lines = []

        # 헤더
        lines.append(f"# {report.query}\n")
        lines.append(f"*생성일: {report.created_at.strftime('%Y-%m-%d %H:%M')} UTC*\n")

        if report.quality_score is not None:
            badge = self._quality_badge(report.quality_score)
            lines.append(f"**품질 점수**: {badge} `{report.quality_score:.2f}`\n")

        lines.append("---\n")

        # 주요 발견
        lines.append("## 주요 발견\n")
        lines.append(f"{report.response}\n")

        # 검색 결과 요약 테이블 (최대 10개)
        if report.search_results:
            lines.append("## 참고 자료 요약\n")
            lines.append("| # | 제목 | 출처 |")
            lines.append("|---|------|------|")
            for i, r in enumerate(report.search_results[:10], 1):
                title = r.get("title", "Untitled").replace("|", "\\|")
                source = (r.get("source") or r.get("url") or "N/A").replace("|", "\\|")
                lines.append(f"| {i} | {title} | {source} |")
            lines.append("")

        # 인용 목록
        if report.citations:
            lines.append("## 인용\n")
            for i, c in enumerate(report.citations, 1):
                title = c.get("title", "Untitled")
                url = c.get("url", "#")
                lines.append(f"{i}. [{title}]({url})")
            lines.append("")

        # fact-check 결과
        if report.fact_check_result:
            contradictions = report.fact_check_result.get("contradictions", [])
            if contradictions:
                lines.append("## 팩트체크 — 주의 사항\n")
                for c in contradictions:
                    lines.append(f"- ⚠️ {c.get('description', '')}")
                lines.append("")

        lines.append("---")
        lines.append(f"*세션 ID: `{report.session_id}`  |  NEOS Research Engine*")

        return "\n".join(lines)

    @staticmethod
    def _quality_badge(score: float) -> str:
        if score >= 0.8:
            return "🟢"
        if score >= 0.5:
            return "🟡"
        return "🔴"
