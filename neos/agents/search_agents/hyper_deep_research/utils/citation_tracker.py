"""
Citation Tracking System for HyperDeepResearch

이 모듈은 연구 보고서의 주장과 출처를 추적하고 관리합니다.

주요 기능:
1. Source-to-Citation 매핑: 각 소스에 고유 번호 부여
2. Inline Citation 파싱: [1,2,3] 형태의 citation 추출
3. Reference List 생성: 모든 인용된 소스의 목록 생성
4. Citation 검증: 모든 citation이 유효한 소스를 가리키는지 확인

설계 원칙:
- 학술 논문 스타일 citation (numbered references)
- 명확한 출처 추적성 (claim → source)
- 자동화된 reference list 생성
"""

import re
import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from urllib.parse import urlparse

from .academic_identifier_extractor import AcademicIdentifierExtractor, AcademicIdentifiers


logger = logging.getLogger(__name__)


# ============================================================================
# Data Structures
# ============================================================================

@dataclass
class Source:
    """
    단일 소스 정보

    학술적 citation을 위한 필수 메타데이터 포함
    """
    url: str
    title: str
    content: str = ""

    # Metadata for citation formatting
    author: Optional[str] = None
    published_date: Optional[str] = None
    domain: Optional[str] = None
    source_type: Optional[str] = None  # 'academic', 'news', 'blog', 'documentation'

    # ★ NEW: Academic identifiers
    academic_ids: Optional[AcademicIdentifiers] = None

    # Quality metrics
    quality_score: float = 0.0
    credibility_score: float = 0.0

    # Citation tracking
    citation_number: Optional[int] = None
    cited_count: int = 0  # 이 소스가 몇 번 인용되었는지

    def __post_init__(self):
        """소스 초기화 후 처리"""
        if not self.domain:
            self.domain = self._extract_domain(self.url)

        if not self.source_type:
            self.source_type = self._infer_source_type(self.domain)

        # ★ NEW: Extract academic identifiers
        if not self.academic_ids:
            self.academic_ids = AcademicIdentifierExtractor.extract(
                self.url, self.content, metadata={}
            )

    def _extract_domain(self, url: str) -> str:
        """URL에서 도메인 추출"""
        try:
            parsed = urlparse(url)
            return parsed.netloc
        except Exception:
            return "unknown"

    def _infer_source_type(self, domain: str) -> str:
        """
        도메인을 기반으로 소스 타입 추론

        ★ Learning Point ─────────────────
        학술적 신뢰도를 판단하기 위해 도메인 분류
        - academic: .edu, arxiv.org, scholar.google.com
        - news: 주요 뉴스 매체
        - official: .gov, .org
        - other: 기타
        ─────────────────────────────────
        """
        domain_lower = domain.lower()

        # Academic sources
        if any(x in domain_lower for x in ['.edu', 'arxiv.org', 'scholar.google',
                                            'pubmed', 'nature.com', 'science.org']):
            return 'academic'

        # Official/Government
        if '.gov' in domain_lower:
            return 'official'

        # News sources
        if any(x in domain_lower for x in ['nytimes', 'washingtonpost', 'reuters',
                                            'bbc.com', 'cnn.com', 'theguardian']):
            return 'news'

        # Technical documentation
        if any(x in domain_lower for x in ['docs.', 'documentation', 'github.com']):
            return 'documentation'

        return 'other'

    def to_citation_format(self, style: str = "numbered") -> str:
        """
        Citation 형식으로 변환 (다양한 학술 스타일 지원)

        Args:
            style: Citation 스타일
                   - 'numbered': 기본 번호 스타일
                   - 'apa': APA 7th edition
                   - 'chicago': Chicago style
                   - 'mla': MLA 9th edition
                   - 'vancouver': Vancouver style (의학)

        Returns:
            포맷된 citation 문자열

        ★ Learning Point ─────────────────
        학술 Citation Styles 비교:

        APA (American Psychological Association):
        - 심리학, 사회과학, 교육학
        - Author (Year). Title. Publisher.

        Chicago:
        - 역사, 인문학
        - Author. Title. Publisher, Year.

        MLA (Modern Language Association):
        - 문학, 예술
        - Author. "Title." Source, Date.

        Vancouver:
        - 의학, 생명과학
        - Author. Title. Journal. Year;vol:pages.
        ─────────────────────────────────
        """
        # ★ Get academic identifier if available
        identifier_str = ""
        if self.academic_ids and self.academic_ids.has_identifiers():
            identifier_str = AcademicIdentifierExtractor.format_identifier_for_citation(
                self.academic_ids, style="default"
            )

        if style == "apa":
            # APA 7th Edition
            # Author, A. A. (Year). Title. Publisher/Source. DOI/URL
            parts = []

            # Author (or domain if no author)
            author = self.author if self.author else self.domain
            parts.append(f"{author}.")

            # Year
            year = self._extract_year(self.published_date) if self.published_date else "n.d."
            parts.append(f"({year}).")

            # Title (italicized in markdown)
            parts.append(f"*{self.title}*.")

            # Source
            if self.domain:
                parts.append(f"{self.domain}.")

            # Identifier or URL
            if identifier_str:
                parts.append(identifier_str)
            else:
                parts.append(self.url)

            return " ".join(parts)

        elif style == "chicago":
            # Chicago Manual of Style
            # Author. "Title." Source. Published Date. URL.
            parts = []

            # Author
            if self.author:
                parts.append(f"{self.author}.")

            # Title (in quotes)
            parts.append(f'"{self.title}."')

            # Source
            if self.domain:
                parts.append(f"{self.domain}.")

            # Date
            if self.published_date:
                parts.append(f"{self.published_date}.")

            # Identifier or URL
            if identifier_str:
                parts.append(identifier_str)
            else:
                parts.append(self.url)

            return " ".join(parts)

        elif style == "mla":
            # MLA 9th Edition
            # Author. "Title." Source, Date, URL.
            parts = []

            # Author
            if self.author:
                parts.append(f"{self.author}.")

            # Title (in quotes)
            parts.append(f'"{self.title}."')

            # Source
            if self.domain:
                parts.append(f"*{self.domain}*,")

            # Date
            if self.published_date:
                parts.append(f"{self.published_date},")

            # URL or identifier
            if identifier_str:
                parts.append(f"{identifier_str}.")
            else:
                parts.append(f"{self.url}.")

            return " ".join(parts)

        elif style == "vancouver":
            # Vancouver Style (for medical/scientific)
            # Author. Title. Source. Year;vol(issue):pages. DOI/PMID
            parts = []

            # Author (abbreviated)
            if self.author:
                parts.append(f"{self.author}.")

            # Title
            parts.append(f"{self.title}.")

            # Source
            if self.domain:
                parts.append(f"{self.domain}.")

            # Year
            if self.published_date:
                year = self._extract_year(self.published_date)
                parts.append(f"{year}.")

            # Identifier (preferably PMID or DOI)
            if identifier_str:
                parts.append(identifier_str)
            else:
                parts.append(f"Available from: {self.url}")

            return " ".join(parts)

        elif style == "numbered":
            # Default numbered style with identifiers
            # [1] Author. "Title". Domain, Date. DOI/URL
            parts = []

            if self.author:
                parts.append(f"{self.author}.")

            parts.append(f'"{self.title}"')

            if self.domain:
                parts.append(f"- {self.domain}")

            if self.published_date:
                parts.append(f"({self.published_date})")

            # ★ NEW: Include academic identifier if available
            if identifier_str:
                parts.append(f"[{identifier_str}]")
            else:
                parts.append(self.url)

            return " ".join(parts)

        # Fallback
        return self.url

    def _extract_year(self, date_string: Optional[str]) -> str:
        """날짜 문자열에서 연도 추출"""
        if not date_string:
            return "n.d."

        # Try to extract year (YYYY pattern)
        year_match = re.search(r'(\d{4})', date_string)
        if year_match:
            return year_match.group(1)

        return date_string


@dataclass
class CitationContext:
    """
    특정 citation의 컨텍스트 정보

    어떤 주장에서 어떤 소스가 사용되었는지 추적
    """
    claim: str  # 주장 내용
    source_numbers: List[int]  # 인용된 소스 번호들
    section_title: str  # 어느 섹션에서 사용되었는지
    confidence: Optional[float] = None  # Multi-hop의 경우 신뢰도

    def __str__(self):
        return f'"{self.claim}" [{",".join(map(str, self.source_numbers))}]'


# ============================================================================
# Citation Tracker
# ============================================================================

class CitationTracker:
    """
    연구 보고서의 citation을 추적하고 관리

    주요 책임:
    1. 소스에 고유 번호 할당 (1부터 시작)
    2. Inline citation 파싱 ([1], [2,3] 등)
    3. Citation 컨텍스트 저장
    4. Reference list 생성
    5. Citation 통계 제공
    """

    def __init__(self):
        """Initialize citation tracker"""
        # Source management
        self._sources: List[Source] = []  # 모든 소스 (순서 유지)
        self._url_to_source: Dict[str, Source] = {}  # URL → Source 매핑
        self._number_to_source: Dict[int, Source] = {}  # Citation number → Source

        # Citation contexts
        self._citation_contexts: List[CitationContext] = []

        # Statistics
        self.stats = {
            "total_sources": 0,
            "cited_sources": 0,
            "total_citations": 0,
            "citations_per_section": {},
        }

    # ========================================================================
    # Source Registration
    # ========================================================================

    def register_sources(self, sources: List[Dict[str, Any]]) -> int:
        """
        소스들을 등록하고 citation 번호 할당

        Args:
            sources: SearchResult 딕셔너리 리스트

        Returns:
            등록된 소스 개수

        ★ Learning Point ─────────────────
        중복 제거 전략:
        - URL을 기준으로 중복 체크
        - 이미 등록된 소스는 기존 번호 유지
        - 새 소스만 번호 할당

        Trade-off:
        - URL 정규화 (www 제거, trailing slash 등)을 할 수도 있지만
        - 단순성을 위해 정확한 URL 매칭만 수행
        ─────────────────────────────────
        """
        registered_count = 0

        for source_data in sources:
            url = source_data.get('url', '')
            if not url:
                continue

            # 중복 체크
            if url in self._url_to_source:
                logger.debug(f"Source already registered: {url}")
                continue

            # Source 객체 생성
            source = Source(
                url=url,
                title=source_data.get('title', 'Untitled'),
                content=source_data.get('content', ''),
                author=source_data.get('author'),
                published_date=source_data.get('published_date'),
                quality_score=source_data.get('score', 0.0),
            )

            # Citation 번호 할당 (1부터 시작)
            source.citation_number = len(self._sources) + 1

            # 등록
            self._sources.append(source)
            self._url_to_source[url] = source
            self._number_to_source[source.citation_number] = source

            registered_count += 1

        self.stats["total_sources"] = len(self._sources)
        logger.info(f"Registered {registered_count} new sources. Total: {len(self._sources)}")

        return registered_count

    def get_source_list_for_prompt(self, max_sources: int = 100) -> str:
        """
        LLM 프롬프트에 포함할 소스 목록 생성

        Args:
            max_sources: 최대 포함 소스 개수

        Returns:
            포맷된 소스 목록 문자열

        ★ Learning Point ─────────────────
        LLM Context Window 관리:
        - 모든 소스를 포함하면 토큰 초과 가능
        - 품질 점수 기준으로 상위 N개만 선택
        - Comprehensive 모드: 더 많은 소스 포함

        Output Format:
        [1] "Title" - domain.com (quality: 0.95)
        [2] "Title" - domain.com (quality: 0.90)
        ...
        ─────────────────────────────────
        """
        # 품질 점수 기준 정렬
        sorted_sources = sorted(
            self._sources[:max_sources],
            key=lambda s: s.quality_score,
            reverse=True
        )

        lines = ["Available Sources for Citation:\n"]
        for source in sorted_sources:
            quality_indicator = "⭐" if source.quality_score > 0.8 else ""
            lines.append(
                f"[{source.citation_number}] {quality_indicator}\"{source.title}\" "
                f"- {source.domain} (quality: {source.quality_score:.2f})"
            )

        return "\n".join(lines)

    # ========================================================================
    # Citation Parsing
    # ========================================================================

    def parse_citations_from_text(
        self,
        text: str,
        section_title: str = "Unknown"
    ) -> List[CitationContext]:
        """
        텍스트에서 inline citation을 파싱

        Args:
            text: 분석할 텍스트
            section_title: 섹션 제목

        Returns:
            추출된 citation 컨텍스트 리스트

        ★ Learning Point ─────────────────
        Citation Pattern:
        - [1] : 단일 소스
        - [1,2,3] : 여러 소스
        - [1-3] : 범위 (선택적 지원)

        정규표현식:
        \[(\d+(?:,\s*\d+)*)\]
        - \[ : 여는 대괄호
        - (\d+(?:,\s*\d+)*) : 숫자들 (쉼표로 구분)
        - \] : 닫는 대괄호
        ─────────────────────────────────
        """
        # Citation 패턴: [1] or [1,2,3] or [1, 2, 3]
        citation_pattern = r'\[(\d+(?:,\s*\d+)*)\]'

        # 문장 단위로 분리 (간단한 방식)
        sentences = re.split(r'[.!?]\s+', text)

        contexts = []

        for sentence in sentences:
            # Citation 찾기
            citations = re.findall(citation_pattern, sentence)

            if not citations:
                continue

            # Citation 번호 추출
            for citation in citations:
                numbers = [int(n.strip()) for n in citation.split(',')]

                # Citation 제거한 순수 주장
                claim = re.sub(citation_pattern, '', sentence).strip()

                if claim:
                    context = CitationContext(
                        claim=claim,
                        source_numbers=numbers,
                        section_title=section_title
                    )
                    contexts.append(context)

                    # 통계 업데이트
                    self._update_citation_stats(numbers, section_title)

        self._citation_contexts.extend(contexts)
        return contexts

    def _update_citation_stats(self, numbers: List[int], section_title: str):
        """Citation 통계 업데이트"""
        for num in numbers:
            if num in self._number_to_source:
                source = self._number_to_source[num]
                source.cited_count += 1
                self.stats["total_citations"] += 1

        if section_title not in self.stats["citations_per_section"]:
            self.stats["citations_per_section"][section_title] = 0
        self.stats["citations_per_section"][section_title] += len(numbers)

    # ========================================================================
    # Reference List Generation
    # ========================================================================

    def generate_reference_list(
        self,
        style: str = "numbered",
        only_cited: bool = True
    ) -> str:
        """
        Reference list 생성

        Args:
            style: Citation 스타일
            only_cited: True면 인용된 소스만, False면 모든 소스

        Returns:
            Markdown 형식의 reference list

        ★ Learning Point ─────────────────
        Reference List 전략:

        Option A: 인용된 소스만 (only_cited=True)
        - 장점: 깔끔, 관련성 높음
        - 단점: 사용하지 않은 고품질 소스 숨김

        Option B: 모든 소스 (only_cited=False)
        - 장점: 투명성, 연구 범위 표시
        - 단점: 목록이 매우 길어짐

        권장: Comprehensive 모드에서는 A,
              투명성 우선 시 B
        ─────────────────────────────────
        """
        # 필터링
        if only_cited:
            sources_to_list = [s for s in self._sources if s.cited_count > 0]
        else:
            sources_to_list = self._sources

        # Citation 번호 순으로 정렬
        sources_to_list.sort(key=lambda s: s.citation_number)

        # 업데이트 통계
        self.stats["cited_sources"] = sum(1 for s in self._sources if s.cited_count > 0)

        # Reference list 생성
        lines = ["## 📚 References\n"]

        for source in sources_to_list:
            citation_text = source.to_citation_format(style)
            cited_indicator = f" (cited {source.cited_count}x)" if source.cited_count > 1 else ""

            lines.append(f"[{source.citation_number}] {citation_text}{cited_indicator}")

        lines.append(f"\n**Total Sources: {len(sources_to_list)}** (Cited: {self.stats['cited_sources']})")

        return "\n".join(lines)

    # ========================================================================
    # Validation & Statistics
    # ========================================================================

    def validate_citations(self, text: str) -> Dict[str, Any]:
        """
        텍스트의 citation이 유효한지 검증

        Returns:
            검증 결과 딕셔너리
        """
        citation_pattern = r'\[(\d+(?:,\s*\d+)*)\]'
        all_citations = re.findall(citation_pattern, text)

        invalid_citations = []
        valid_count = 0

        for citation in all_citations:
            numbers = [int(n.strip()) for n in citation.split(',')]

            for num in numbers:
                if num not in self._number_to_source:
                    invalid_citations.append(num)
                else:
                    valid_count += 1

        return {
            "valid": len(invalid_citations) == 0,
            "total_citations": valid_count + len(invalid_citations),
            "valid_citations": valid_count,
            "invalid_citations": invalid_citations,
            "coverage": valid_count / (valid_count + len(invalid_citations)) if (valid_count + len(invalid_citations)) > 0 else 0
        }

    def get_citation_statistics(self) -> Dict[str, Any]:
        """Citation 통계 반환"""
        # Most cited sources
        most_cited = sorted(
            [s for s in self._sources if s.cited_count > 0],
            key=lambda s: s.cited_count,
            reverse=True
        )[:10]

        # Source type distribution
        type_dist = {}
        for source in self._sources:
            type_dist[source.source_type] = type_dist.get(source.source_type, 0) + 1

        return {
            **self.stats,
            "most_cited_sources": [
                {
                    "number": s.citation_number,
                    "title": s.title,
                    "cited_count": s.cited_count,
                    "domain": s.domain
                }
                for s in most_cited
            ],
            "source_type_distribution": type_dist,
            "average_citations_per_source": (
                self.stats["total_citations"] / self.stats["cited_sources"]
                if self.stats["cited_sources"] > 0 else 0
            )
        }

    # ========================================================================
    # Helper Methods
    # ========================================================================

    def get_sources_by_numbers(self, numbers: List[int]) -> List[Source]:
        """Citation 번호로 소스 조회"""
        return [
            self._number_to_source[num]
            for num in numbers
            if num in self._number_to_source
        ]

    def get_source_by_url(self, url: str) -> Optional[Source]:
        """URL로 소스 조회"""
        return self._url_to_source.get(url)

    def clear(self):
        """모든 데이터 초기화"""
        self._sources.clear()
        self._url_to_source.clear()
        self._number_to_source.clear()
        self._citation_contexts.clear()
        self.stats = {
            "total_sources": 0,
            "cited_sources": 0,
            "total_citations": 0,
            "citations_per_section": {},
        }

    # ========================================================================
    # ★ NEW: Citation Recommendation Methods
    # ========================================================================

    def recommend_citations_for_claim(
        self,
        claim: str,
        top_k: int = 3,
        min_score: float = 0.3
    ) -> List[Any]:  # List[CitationRecommendation]
        """
        주장에 대한 citation 추천

        Args:
            claim: 주장 텍스트
            top_k: 추천할 소스 개수
            min_score: 최소 점수

        Returns:
            추천 소스 리스트

        Example:
            >>> recommendations = tracker.recommend_citations_for_claim(
            ...     "Quantum computers achieved 1000 qubits in 2023",
            ...     top_k=3
            ... )
            >>> for rec in recommendations:
            ...     print(f"[{rec.source_number}] {rec.source_title} (score: {rec.combined_score:.2f})")
        """
        # Lazy import to avoid circular dependency
        from .citation_recommender import CitationRecommender

        recommender = CitationRecommender()
        return recommender.recommend_for_claim(
            claim, self._sources, top_k, min_score
        )

    def evaluate_citation_quality(
        self,
        claim: str,
        source_number: int
    ) -> Dict[str, Any]:
        """
        특정 citation의 품질 평가

        Args:
            claim: 주장 텍스트
            source_number: 평가할 소스 번호

        Returns:
            {
                'overall_score': 0-1,
                'relevance': 0-1,
                'authority': 0-1,
                'grade': 'A'|'B'|'C'|'D',
                'issues': [...]
            }

        Example:
            >>> quality = tracker.evaluate_citation_quality(
            ...     "Quantum computers use superposition",
            ...     source_number=1
            ... )
            >>> print(f"Grade: {quality['grade']}, Score: {quality['overall_score']:.2f}")
        """
        # Lazy import
        from .citation_recommender import CitationQualityScorer

        if source_number not in self._number_to_source:
            return {
                'overall_score': 0.0,
                'error': f"Source {source_number} not found"
            }

        source = self._number_to_source[source_number]
        scorer = CitationQualityScorer()

        return scorer.score_citation(claim, source)

    def get_citation_suggestions_for_section(
        self,
        section_text: str,
        min_citations_per_claim: int = 2
    ) -> Dict[str, Any]:
        """
        섹션 전체에 대한 citation 제안

        Args:
            section_text: 섹션 텍스트
            min_citations_per_claim: 주장당 최소 추천 수

        Returns:
            {
                'total_claims': int,
                'suggestions': {claim: [recommendations]},
                'summary': str
            }

        ★ Learning Point ─────────────────
        LLM 후처리(Post-processing):
        1. LLM이 섹션 생성 (citation 누락 가능)
        2. 이 메서드로 누락된 citation 감지
        3. 추천 소스 제공
        4. 사용자/LLM에게 피드백

        Use Case:
        - Citation 품질 검증
        - 누락된 citation 발견
        - 대안 소스 제안
        ─────────────────────────────────
        """
        # Lazy import
        from .citation_recommender import CitationRecommender

        recommender = CitationRecommender()
        suggestions = recommender.recommend_for_section(
            section_text,
            self._sources,
            min_citations_per_claim
        )

        # Generate summary
        total_claims = len(suggestions)
        total_recommendations = sum(len(recs) for recs in suggestions.values())

        summary = (
            f"Found {total_claims} claims that could benefit from citations. "
            f"Generated {total_recommendations} citation recommendations."
        )

        return {
            'total_claims': total_claims,
            'suggestions': suggestions,
            'summary': summary
        }

    # ========================================================================
    # ★ NEW: Hop-Level Citation Tracking (MultiHopSearch Integration)
    # ========================================================================

    def register_hop_citations(
        self,
        hop_citations: List[Dict[str, Any]],
        query: str
    ) -> Dict[str, Any]:
        """
        MultiHopSearch의 hop-level citations 등록

        Args:
            hop_citations: Hop citation 리스트
                [
                    {
                        "hop_number": 1,
                        "question": "Who founded OpenAI?",
                        "answer": "Sam Altman, Elon Musk, ...",
                        "source_count": 3,
                        "source_urls": [...]
                    },
                    ...
                ]
            query: 원본 질문

        Returns:
            등록 결과 및 통계

        ★ Learning Point ─────────────────
        Hop-Level Citation Tracking:

        MultiHopSearch의 장점:
        1. Chain-of-thought 추론 과정 기록
        2. 각 hop마다 사용된 소스 추적
        3. 중간 추론 단계의 검증 가능

        Use Case:
        - "Who founded the company that created ChatGPT?"
          Hop 1: ChatGPT → OpenAI
          Hop 2: OpenAI → Sam Altman, ...

        각 hop의 소스를 별도로 citation 가능
        ─────────────────────────────────
        """
        hop_citation_map = {}
        total_hop_sources = 0

        for hop_data in hop_citations:
            hop_number = hop_data.get("hop_number", 0)
            source_urls = hop_data.get("source_urls", [])

            # Register sources from this hop
            hop_source_numbers = []
            for url in source_urls:
                # Check if source already registered
                if url in self._url_to_source:
                    source = self._url_to_source[url]
                    hop_source_numbers.append(source.citation_number)
                else:
                    # Source not registered yet (shouldn't happen normally)
                    logger.warning(f"Hop source not found in registry: {url}")

            hop_citation_map[hop_number] = {
                "question": hop_data.get("question", ""),
                "answer": hop_data.get("answer", ""),
                "source_numbers": hop_source_numbers,
                "source_count": len(hop_source_numbers),
            }
            total_hop_sources += len(hop_source_numbers)

        return {
            "query": query,
            "total_hops": len(hop_citations),
            "total_hop_sources": total_hop_sources,
            "hop_citation_map": hop_citation_map,
        }

    def format_hop_citations_for_report(
        self,
        hop_citation_map: Dict[int, Dict[str, Any]],
        query: str
    ) -> str:
        """
        Hop citations를 보고서 형식으로 포맷

        Args:
            hop_citation_map: register_hop_citations의 결과
            query: 원본 질문

        Returns:
            포맷된 hop citation 문자열 (마크다운)

        Example Output:
            ### Chain-of-Thought Reasoning: "Who founded the company that created ChatGPT?"

            **Hop 1**: "What company created ChatGPT?"
            - Answer: OpenAI [1, 2, 3]
            - Sources: 3

            **Hop 2**: "Who founded OpenAI?"
            - Answer: Sam Altman, Elon Musk, Greg Brockman [4, 5]
            - Sources: 2
        """
        if not hop_citation_map:
            return ""

        lines = [
            f"### Chain-of-Thought Reasoning: \"{query}\"",
            ""
        ]

        for hop_number in sorted(hop_citation_map.keys()):
            hop_data = hop_citation_map[hop_number]

            # Format source numbers as citation
            source_numbers = hop_data.get("source_numbers", [])
            citation_str = f"[{', '.join(map(str, source_numbers))}]" if source_numbers else ""

            lines.append(f"**Hop {hop_number}**: \"{hop_data.get('question', 'N/A')}\"")
            lines.append(f"- Answer: {hop_data.get('answer', 'N/A')} {citation_str}")
            lines.append(f"- Sources: {hop_data.get('source_count', 0)}")
            lines.append("")

        return "\n".join(lines)

    def get_hop_level_statistics(
        self,
        hop_citations_list: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        여러 hop citations의 통계 생성

        Args:
            hop_citations_list: register_hop_citations 결과 리스트

        Returns:
            통계 정보
        """
        if not hop_citations_list:
            return {
                "total_queries": 0,
                "total_hops": 0,
                "total_hop_sources": 0,
                "avg_hops_per_query": 0.0,
                "avg_sources_per_hop": 0.0,
            }

        total_queries = len(hop_citations_list)
        total_hops = sum(hc.get("total_hops", 0) for hc in hop_citations_list)
        total_hop_sources = sum(hc.get("total_hop_sources", 0) for hc in hop_citations_list)

        return {
            "total_queries": total_queries,
            "total_hops": total_hops,
            "total_hop_sources": total_hop_sources,
            "avg_hops_per_query": total_hops / total_queries if total_queries > 0 else 0.0,
            "avg_sources_per_hop": total_hop_sources / total_hops if total_hops > 0 else 0.0,
        }
