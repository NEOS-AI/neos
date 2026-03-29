"""ChartRenderer — 연구 결과 데이터를 차트 이미지로 변환

matplotlib이 설치되어 있으면 PNG를 base64로 인코딩하여 반환.
설치되지 않은 경우 빈 리스트를 반환하며 전체 파이프라인은 정상 동작한다.
"""

import base64
import io
import logging
from collections import Counter
from typing import Any

from neos.exporters.base import ResearchReport

logger = logging.getLogger(__name__)

# CR-P6-04: pyplot 임포트 전 최초 1회만 백엔드 설정 (모듈 수준)
try:
    import matplotlib
    matplotlib.use("Agg")  # 헤드리스 환경용 백엔드
    from matplotlib.figure import Figure  # CR-P6-09: pyplot 전역 상태 우회
    _MATPLOTLIB_AVAILABLE = True
except ImportError:
    _MATPLOTLIB_AVAILABLE = False
    logger.debug("matplotlib not installed — chart generation skipped")


class ChartRenderer:
    """ResearchReport → [{title, image_b64, alt}] 차트 목록 변환기.

    반환 구조:
        [
            {"title": "소스 분포", "image_b64": "<base64 PNG>", "alt": "Source distribution chart"},
        ]
    """

    def render(self, report: ResearchReport) -> list[dict[str, Any]]:
        if not _MATPLOTLIB_AVAILABLE:
            return []

        charts = []

        source_chart = self._source_distribution_chart(report)
        if source_chart:
            charts.append(source_chart)

        return charts

    def _source_distribution_chart(
        self, report: ResearchReport
    ) -> dict[str, Any] | None:
        if not report.search_results:
            return None

        # 도메인 단위 소스 집계
        sources = [
            r.get("source") or _extract_domain(r.get("url", ""))
            for r in report.search_results
            if r.get("source") or r.get("url")
        ]
        if not sources:
            return None

        counter = Counter(sources)
        top = counter.most_common(8)
        labels, values = zip(*top)

        # CR-P6-09: matplotlib.figure.Figure 직접 사용 (pyplot 전역 상태 우회)
        fig = Figure(figsize=(7, 4))
        ax = fig.add_subplot(1, 1, 1)
        bars = ax.barh(labels, values, color="#3498db")
        ax.set_xlabel("결과 수")
        ax.set_title("소스별 검색 결과 분포")
        ax.bar_label(bars, padding=3)
        fig.tight_layout()

        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=100)
        # plt.close() 불필요 — Figure 객체는 GC에 의해 해제
        buf.seek(0)
        image_b64 = base64.b64encode(buf.read()).decode("utf-8")

        return {
            "title": "소스 분포",
            "image_b64": image_b64,
            "alt": "Source distribution bar chart",
        }


def _extract_domain(url: str) -> str:
    """URL에서 도메인 추출 (표준 라이브러리만 사용)."""
    try:
        from urllib.parse import urlparse
        return urlparse(url).netloc or url
    except Exception:
        return url
