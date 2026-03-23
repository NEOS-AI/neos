"""MermaidDiagramRenderer — 인용 소스를 Mermaid 다이어그램으로 시각화

순수 문자열 생성이므로 외부 의존성 없음.
브라우저에서 Mermaid CDN이 렌더링한다.
"""

import re
from neos.exporters.base import ResearchReport


class MermaidDiagramRenderer:
    """ResearchReport.citations → Mermaid mindmap 문법 문자열 변환기.

    반환 예시 (citations 3개):
        mindmap
          root((연구 주제))
            Source A
            Source B
            Source C
    """

    MAX_NODES = 12  # Mermaid 가독성 한계

    def render(self, report: ResearchReport) -> str:
        citations = (report.citations or [])[:self.MAX_NODES]

        if not citations:
            return self._empty_diagram(report.query)

        root_label = _truncate(report.query, 30)
        lines = ["mindmap", f"  root(({root_label}))"]

        for c in citations:
            title = _truncate(c.get("title") or c.get("url") or "Unknown", 40)
            safe = _sanitize_mermaid(title)
            lines.append(f"    {safe}")

        return "\n".join(lines)

    @staticmethod
    def _empty_diagram(query: str) -> str:
        label = _truncate(query, 30)
        return f"mindmap\n  root(({label}))\n    (데이터 없음)"


def _truncate(text: str, max_len: int) -> str:
    return text if len(text) <= max_len else text[:max_len - 1] + "…"


def _sanitize_mermaid(text: str) -> str:
    """Mermaid mindmap 노드 레이블 생성 (CR-P6-10).

    쿼트 구문으로 특수문자를 보존한다.
    큰따옴표와 백틱만 제거 (쿼트 내에서 문제를 일으키는 문자).
    예: 'Reuters (reuters.com)' → '"Reuters (reuters.com)"'
    """
    safe = re.sub(r'["`]', "", text).strip() or "Source"
    return f'"{safe}"'
