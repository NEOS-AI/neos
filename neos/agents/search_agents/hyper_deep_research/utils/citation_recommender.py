"""
Citation Recommendation System

주장(claim)의 내용을 분석하여 가장 적합한 소스를 자동으로 추천합니다.

기능:
1. Claim-Source Matching: 주장과 소스의 의미적 유사도 계산
2. Source Quality Weighting: 고품질 소스 우선 추천
3. Academic Preference: 학술 소스 우선순위
4. Diversity Consideration: 다양한 소스 추천

★ Learning Point ─────────────────
Citation Recommendation의 핵심:

1. Semantic Similarity (의미적 유사도):
   - 주장의 내용과 소스 내용의 관련성
   - Embedding 기반 유사도 계산

2. Source Quality (소스 품질):
   - 학술 소스 > 뉴스 > 블로그
   - DOI/arXiv 있는 소스 우선
   - Domain authority

3. Citation Appropriateness (적합성):
   - Factual claims → 데이터 중심 소스
   - Opinions → 전문가 의견/분석
   - Statistics → 공식 통계/연구

─────────────────────────────────
"""

import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
import re

logger = logging.getLogger(__name__)


@dataclass
class CitationRecommendation:
    """Citation 추천 결과"""
    source_number: int
    source_title: str
    relevance_score: float  # 0-1: 주장과의 관련성
    quality_score: float    # 0-1: 소스 품질
    combined_score: float   # 0-1: 종합 점수
    reason: str            # 추천 이유
    source_type: str       # academic, news, etc.
    has_identifier: bool   # DOI/arXiv 등 존재 여부

    def __str__(self):
        return (
            f"[{self.source_number}] {self.source_title[:50]}... "
            f"(score: {self.combined_score:.2f}, {self.source_type})"
        )


class CitationRecommender:
    """
    Citation 추천 시스템

    주장의 특성을 분석하여 가장 적합한 소스를 추천
    """

    # Claim type patterns
    FACTUAL_PATTERNS = [
        r'\d+%',           # Percentages
        r'\d+\s*million',  # Numbers with units
        r'\d+\s*billion',
        r'according to',
        r'research shows',
        r'study found',
        r'data indicates',
    ]

    OPINION_PATTERNS = [
        r'believe',
        r'suggest',
        r'argue',
        r'propose',
        r'recommend',
        r'should',
        r'would',
        r'could',
    ]

    STATISTICAL_PATTERNS = [
        r'\d+\.?\d*%',
        r'\d+\.\d+',
        r'average',
        r'median',
        r'mean',
        r'correlation',
        r'p\s*[<>=]\s*0\.\d+',
    ]

    def __init__(self, embedding_service: Optional[Any] = None):
        """
        Initialize citation recommender

        Args:
            embedding_service: Optional embedding service for semantic similarity
                              If None, uses keyword-based matching
        """
        self.embedding_service = embedding_service
        self.use_embeddings = embedding_service is not None

    def recommend_for_claim(
        self,
        claim: str,
        sources: List[Any],  # List of Source objects
        top_k: int = 3,
        min_score: float = 0.3
    ) -> List[CitationRecommendation]:
        """
        주장에 대한 소스 추천

        Args:
            claim: 주장 텍스트
            sources: 사용 가능한 Source 객체 리스트
            top_k: 추천할 소스 개수
            min_score: 최소 점수 (이하는 필터링)

        Returns:
            추천 소스 리스트 (점수 높은 순)

        ★ Learning Point ─────────────────
        추천 알고리즘:

        1. Claim Type 분류:
           - Factual (사실): 통계, 연구 결과
           - Opinion (의견): 전문가 분석
           - Statistical (통계): 수치 데이터

        2. Score 계산:
           combined_score = (
               relevance_score * 0.6 +
               quality_score * 0.3 +
               type_match_score * 0.1
           )

        3. Filtering:
           - min_score 이하 제거
           - 중복 도메인 제한
           - Top-k 선택
        ─────────────────────────────────
        """
        claim_type = self._classify_claim(claim)
        recommendations = []

        for source in sources:
            # 1. Calculate relevance score
            relevance_score = self._calculate_relevance(claim, source)

            # 2. Get quality score
            quality_score = self._get_quality_score(source)

            # 3. Calculate type match score
            type_match_score = self._calculate_type_match(claim_type, source)

            # 4. Combined score (weighted)
            combined_score = (
                relevance_score * 0.6 +
                quality_score * 0.3 +
                type_match_score * 0.1
            )

            # Filter by min_score
            if combined_score < min_score:
                continue

            # Generate recommendation reason
            reason = self._generate_reason(
                claim_type, relevance_score, quality_score, source
            )

            recommendations.append(CitationRecommendation(
                source_number=source.citation_number,
                source_title=source.title,
                relevance_score=relevance_score,
                quality_score=quality_score,
                combined_score=combined_score,
                reason=reason,
                source_type=source.source_type,
                has_identifier=source.academic_ids and source.academic_ids.has_identifiers()
            ))

        # Sort by combined score
        recommendations.sort(key=lambda x: x.combined_score, reverse=True)

        # Diversity: Avoid too many from same domain
        diverse_recommendations = self._apply_diversity_filter(
            recommendations, max_per_domain=2
        )

        return diverse_recommendations[:top_k]

    def _classify_claim(self, claim: str) -> str:
        """
        Claim 타입 분류

        Returns:
            'factual', 'opinion', 'statistical', or 'general'
        """
        claim_lower = claim.lower()

        # Check for statistical claim
        for pattern in self.STATISTICAL_PATTERNS:
            if re.search(pattern, claim_lower):
                return 'statistical'

        # Check for factual claim
        for pattern in self.FACTUAL_PATTERNS:
            if re.search(pattern, claim_lower):
                return 'factual'

        # Check for opinion
        for pattern in self.OPINION_PATTERNS:
            if re.search(pattern, claim_lower):
                return 'opinion'

        return 'general'

    def _calculate_relevance(self, claim: str, source: Any) -> float:
        """
        주장과 소스의 관련성 점수 계산

        Uses embedding similarity if available, otherwise keyword matching
        """
        if self.use_embeddings:
            # TODO: Implement embedding-based similarity
            # similarity = cosine_similarity(embed(claim), embed(source.content))
            # For now, fall back to keyword matching
            pass

        # Keyword-based matching
        return self._keyword_similarity(claim, source)

    def _keyword_similarity(self, claim: str, source: Any) -> float:
        """
        키워드 기반 유사도 계산

        ★ Learning Point ─────────────────
        간단하지만 효과적인 방법:
        1. Claim에서 주요 키워드 추출
        2. Source title + content에서 매칭
        3. Jaccard similarity 계산

        개선 가능:
        - TF-IDF
        - Word2Vec
        - Sentence-BERT
        ─────────────────────────────────
        """
        # Extract keywords (simple: words longer than 3 chars)
        claim_words = set(
            word.lower() for word in re.findall(r'\b\w+\b', claim)
            if len(word) > 3 and word.lower() not in ['that', 'with', 'this', 'have', 'from']
        )

        # Source text (title + content snippet)
        source_text = f"{source.title} {source.content[:500]}".lower()
        source_words = set(re.findall(r'\b\w+\b', source_text))

        # Jaccard similarity
        if not claim_words:
            return 0.0

        intersection = claim_words & source_words
        union = claim_words | source_words

        if not union:
            return 0.0

        return len(intersection) / len(union)

    def _get_quality_score(self, source: Any) -> float:
        """
        소스 품질 점수

        Factors:
        - source.quality_score (if available)
        - source_type (academic > news > blog)
        - has academic identifier (DOI, arXiv)
        - domain authority
        """
        score = 0.0

        # Base quality score
        if hasattr(source, 'quality_score'):
            score += source.quality_score * 0.5

        # Source type bonus
        type_scores = {
            'academic': 0.3,
            'official': 0.25,
            'news': 0.15,
            'documentation': 0.1,
            'other': 0.0
        }
        score += type_scores.get(source.source_type, 0.0)

        # Academic identifier bonus
        if source.academic_ids and source.academic_ids.has_identifiers():
            score += 0.2

        return min(score, 1.0)

    def _calculate_type_match(self, claim_type: str, source: Any) -> float:
        """
        Claim 타입과 Source 타입의 매칭 점수

        ★ Learning Point ─────────────────
        적합성 매칭:

        Statistical claim → academic source (높은 점수)
        Statistical claim → blog (낮은 점수)

        Opinion claim → expert analysis (높은 점수)
        Opinion claim → academic (중간 점수)
        ─────────────────────────────────
        """
        # Type match matrix
        match_scores = {
            ('statistical', 'academic'): 1.0,
            ('statistical', 'official'): 0.9,
            ('statistical', 'news'): 0.5,
            ('factual', 'academic'): 0.9,
            ('factual', 'official'): 0.8,
            ('factual', 'news'): 0.7,
            ('opinion', 'academic'): 0.7,
            ('opinion', 'news'): 0.8,
            ('general', 'academic'): 0.8,
            ('general', 'news'): 0.6,
        }

        key = (claim_type, source.source_type)
        return match_scores.get(key, 0.5)

    def _generate_reason(
        self,
        claim_type: str,
        relevance: float,
        quality: float,
        source: Any
    ) -> str:
        """추천 이유 생성"""
        reasons = []

        # Relevance
        if relevance > 0.7:
            reasons.append("highly relevant content")
        elif relevance > 0.5:
            reasons.append("relevant content")

        # Quality
        if quality > 0.8:
            reasons.append("high-quality source")
        if source.source_type == 'academic':
            reasons.append("academic source")

        # Identifiers
        if source.academic_ids and source.academic_ids.has_identifiers():
            if source.academic_ids.doi:
                reasons.append("has DOI")
            elif source.academic_ids.arxiv_id:
                reasons.append("arXiv paper")
            elif source.academic_ids.pmid:
                reasons.append("PubMed indexed")

        # Type match
        if claim_type == 'statistical' and source.source_type == 'academic':
            reasons.append("suitable for statistical claim")

        return ", ".join(reasons) if reasons else "general match"

    def _apply_diversity_filter(
        self,
        recommendations: List[CitationRecommendation],
        max_per_domain: int = 2
    ) -> List[CitationRecommendation]:
        """
        도메인 다양성 필터 적용

        같은 도메인에서 너무 많은 소스가 추천되지 않도록
        """
        # This would need source domain information
        # For now, return as is
        # TODO: Implement domain tracking
        return recommendations

    def recommend_for_section(
        self,
        section_text: str,
        sources: List[Any],
        min_citations_per_claim: int = 2
    ) -> Dict[str, List[CitationRecommendation]]:
        """
        섹션 전체에 대한 Citation 추천

        Args:
            section_text: 섹션 텍스트
            sources: 사용 가능한 소스 리스트
            min_citations_per_claim: 주장당 최소 추천 소스 수

        Returns:
            {claim: [recommendations]} 딕셔너리

        ★ Learning Point ─────────────────
        섹션 레벨 추천:
        1. 섹션을 문장으로 분리
        2. Citation이 필요한 문장 식별
        3. 각 문장에 대해 추천
        4. 통합 및 중복 제거
        ─────────────────────────────────
        """
        # Split into sentences
        sentences = re.split(r'[.!?]+', section_text)

        recommendations_by_claim = {}

        for sentence in sentences:
            sentence = sentence.strip()
            if len(sentence) < 20:  # Skip very short sentences
                continue

            # Check if needs citation (has factual/statistical content)
            if self._needs_citation(sentence):
                recs = self.recommend_for_claim(
                    sentence,
                    sources,
                    top_k=min_citations_per_claim
                )
                if recs:
                    recommendations_by_claim[sentence] = recs

        return recommendations_by_claim

    def _needs_citation(self, sentence: str) -> bool:
        """
        문장이 citation을 필요로 하는지 판단

        ★ Learning Point ─────────────────
        Citation이 필요한 문장:
        - 통계/수치 포함
        - 연구 결과 언급
        - 사실적 주장
        - 전문가 의견 인용

        Citation 불필요:
        - 일반적 지식
        - 자명한 사실
        - 저자의 분석/해석
        ─────────────────────────────────
        """
        # Has numbers/statistics
        if re.search(r'\d+%|\d+\.\d+|\d+\s*(million|billion|thousand)', sentence):
            return True

        # Research mentions
        research_keywords = [
            'research', 'study', 'according to', 'found that',
            'shows that', 'indicates', 'suggests', 'data'
        ]
        sentence_lower = sentence.lower()
        if any(kw in sentence_lower for kw in research_keywords):
            return True

        # Specific claims (not general knowledge)
        # TODO: More sophisticated detection
        # For now, assume most sentences need citation
        return len(sentence) > 30  # Longer sentences likely need citation


class CitationQualityScorer:
    """
    Citation 품질 평가기

    특정 주장에 대한 citation의 적합성을 평가
    """

    def score_citation(
        self,
        claim: str,
        source: Any,
        citation_context: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Citation 품질 점수

        Args:
            claim: 주장 텍스트
            source: Source 객체
            citation_context: Citation이 사용된 컨텍스트 (문단 등)

        Returns:
            {
                'overall_score': 0-1,
                'relevance': 0-1,
                'authority': 0-1,
                'recency': 0-1,
                'appropriateness': 0-1,
                'issues': [list of issues],
                'grade': 'A' | 'B' | 'C' | 'D'
            }
        """
        recommender = CitationRecommender()

        # Relevance
        relevance = recommender._calculate_relevance(claim, source)

        # Authority (quality)
        authority = recommender._get_quality_score(source)

        # Recency
        recency = self._score_recency(source)

        # Appropriateness
        claim_type = recommender._classify_claim(claim)
        appropriateness = recommender._calculate_type_match(claim_type, source)

        # Overall score (weighted)
        overall_score = (
            relevance * 0.4 +
            authority * 0.3 +
            recency * 0.15 +
            appropriateness * 0.15
        )

        # Identify issues
        issues = self._identify_issues(
            claim, source, relevance, authority, recency
        )

        # Grade
        grade = self._assign_grade(overall_score)

        return {
            'overall_score': overall_score,
            'relevance': relevance,
            'authority': authority,
            'recency': recency,
            'appropriateness': appropriateness,
            'issues': issues,
            'grade': grade
        }

    def _score_recency(self, source: Any) -> float:
        """
        소스의 최신성 점수

        Recent = higher score (for most topics)
        """
        # TODO: Parse published_date and calculate age
        # For now, return default
        return 0.7

    def _identify_issues(
        self,
        claim: str,
        source: Any,
        relevance: float,
        authority: float,
        recency: float
    ) -> List[str]:
        """잠재적 문제 식별"""
        issues = []

        if relevance < 0.3:
            issues.append("Low relevance: source may not support this specific claim")

        if authority < 0.5:
            issues.append("Low authority: consider using higher-quality source")

        if source.source_type not in ['academic', 'official']:
            issues.append(f"Non-academic source ({source.source_type})")

        if not (source.academic_ids and source.academic_ids.has_identifiers()):
            issues.append("No academic identifier (DOI/arXiv/PMID)")

        return issues

    def _assign_grade(self, score: float) -> str:
        """점수를 등급으로 변환"""
        if score >= 0.8:
            return 'A'
        elif score >= 0.6:
            return 'B'
        elif score >= 0.4:
            return 'C'
        else:
            return 'D'
