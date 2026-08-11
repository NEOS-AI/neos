"""
Research Templates (Phase 4.7)

사전 구축된 연구 설정. 각 템플릿은 특정 연구 유형에 최적화된
워크플로우 설정, 에이전트 구성, 프롬프트를 제공합니다.
"""

from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional


@dataclass
class ResearchTemplate:
    """연구 템플릿 정의"""

    template_id: str
    name: str
    name_en: str
    description: str
    category: str  # business, academic, technology, finance

    # WorkflowConfig override (기존 설정 덮어쓰기)
    workflow_overrides: Dict[str, Any] = field(default_factory=dict)

    # 필수 에이전트 목록 (SearchOrchestrator가 우선 할당)
    required_agents: List[str] = field(default_factory=list)

    # 권장 skill 목록 (SkillBasedToolSelector 힌트)
    recommended_skills: List[str] = field(default_factory=list)

    # 연구 지침 프롬프트 (쿼리 앞에 prepend)
    research_guidance: str = ""

    # 출력 형식 힌트
    output_format: str = "report"  # report, comparison, data_table, summary

    # 템플릿 파라미터 스키마 (API에서 사용자 입력용)
    parameter_schema: Dict[str, str] = field(default_factory=dict)


# ============================================================================
# 사전 정의 템플릿
# ============================================================================

RESEARCH_TEMPLATES: Dict[str, ResearchTemplate] = {
    # ------------------------------------------------------------------ #
    # 1. 시장 분석
    # ------------------------------------------------------------------ #
    "market_analysis": ResearchTemplate(
        template_id="market_analysis",
        name="시장 분석",
        name_en="Market Analysis",
        description="특정 시장의 규모, 트렌드, 경쟁 구도, 성장률을 종합 분석합니다.",
        category="business",
        workflow_overrides={
            "enable_fact_check": True,
            "min_search_sources": 5,
            "enable_data_analysis": True,
        },
        required_agents=[
            "realtime_info_search",
            "realtime_data_search",
            "comparative_analysis",
        ],
        recommended_skills=["news-api", "sec-edgar", "google-scholar", "openalex"],
        research_guidance=(
            "다음 항목을 포괄적으로 분석하세요:\n"
            "1. 시장 규모 및 성장률 (최근 3년 데이터)\n"
            "2. 주요 플레이어 및 시장 점유율\n"
            "3. 핵심 트렌드와 성장 동인\n"
            "4. 규제 환경 및 진입 장벽\n"
            "5. 향후 전망 및 기회\n\n"
            "수치 데이터는 출처를 명시하고, 가능하면 표 형식으로 정리하세요."
        ),
        output_format="report",
        parameter_schema={
            "market_name": "분석할 시장 이름 (예: '글로벌 전기차 배터리 시장')",
        },
    ),
    # ------------------------------------------------------------------ #
    # 2. 문헌 리뷰
    # ------------------------------------------------------------------ #
    "literature_review": ResearchTemplate(
        template_id="literature_review",
        name="문헌 리뷰",
        name_en="Literature Review",
        description="학술 논문을 체계적으로 종합 분석하고 연구 동향을 파악합니다.",
        category="academic",
        workflow_overrides={
            "enable_fact_check": True,
            "enable_citation_tracking": True,
            "min_search_sources": 8,
        },
        required_agents=[
            "knowledge_search",
            "multi_query_search",
        ],
        recommended_skills=[
            "semantic-scholar",
            "arxiv",
            "pubmed",
            "google-scholar",
            "openalex",
        ],
        research_guidance=(
            "체계적 문헌 리뷰를 수행하세요:\n"
            "1. 주요 연구 동향 및 패러다임 변화\n"
            "2. 핵심 연구자 및 인용 관계\n"
            "3. 주요 방법론 비교 분석\n"
            "4. 연구 갭(gap) 및 미래 연구 방향\n"
            "5. 상위 인용 논문 정리\n\n"
            "모든 주장에 학술적 인용(저자, 연도)을 포함하세요."
        ),
        output_format="report",
        parameter_schema={
            "topic": "연구 주제",
            "year_range": "검색 기간 (예: '2020-2025')",
        },
    ),
    # ------------------------------------------------------------------ #
    # 3. 경쟁사 분석
    # ------------------------------------------------------------------ #
    "competitive_analysis": ResearchTemplate(
        template_id="competitive_analysis",
        name="경쟁사 분석",
        name_en="Competitive Analysis",
        description="경쟁사의 제품, 전략, 강약점을 비교 분석합니다.",
        category="business",
        workflow_overrides={
            "enable_comparative_analysis": True,
            "min_search_sources": 5,
        },
        required_agents=[
            "realtime_info_search",
            "web_lookup",
            "comparative_analysis",
        ],
        recommended_skills=["news-api", "reddit", "github-search"],
        research_guidance=(
            "다음 항목별로 경쟁사를 비교 분석하세요:\n"
            "1. 제품/서비스 포트폴리오\n"
            "2. 가격 정책 및 비즈니스 모델\n"
            "3. 기술 스택 및 혁신성\n"
            "4. 시장 포지셔닝 및 타겟 고객\n"
            "5. SWOT (강점, 약점, 기회, 위협)\n"
            "6. 고객 리뷰 및 평판\n\n"
            "비교 결과를 표 형식으로 정리하세요."
        ),
        output_format="comparison",
        parameter_schema={
            "competitors": "비교할 기업/제품 목록 (쉼표 구분)",
        },
    ),
    # ------------------------------------------------------------------ #
    # 4. 기술 동향
    # ------------------------------------------------------------------ #
    "technology_trend": ResearchTemplate(
        template_id="technology_trend",
        name="기술 동향",
        name_en="Technology Trend",
        description="신기술의 발전 과정, 적용 사례, 미래 전망을 분석합니다.",
        category="technology",
        workflow_overrides={
            "enable_fact_check": True,
            "min_search_sources": 6,
        },
        required_agents=[
            "realtime_info_search",
            "knowledge_search",
            "multi_query_search",
        ],
        recommended_skills=[
            "news-api",
            "github-search",
            "arxiv",
            "reddit",
            "semantic-scholar",
        ],
        research_guidance=(
            "다음 관점에서 기술 동향을 분석하세요:\n"
            "1. 기술 개요 및 발전 과정\n"
            "2. 현재 적용 사례 및 주요 기업\n"
            "3. 최근 뉴스, 발표, 이슈\n"
            "4. 오픈소스 생태계 동향 (GitHub 등)\n"
            "5. 학술 연구 동향\n"
            "6. 향후 3-5년 전망\n\n"
            "실시간 데이터와 학술 자료를 균형 있게 활용하세요."
        ),
        output_format="report",
        parameter_schema={
            "technology": "분석할 기술 (예: 'LLM Agent Framework')",
        },
    ),
    # ------------------------------------------------------------------ #
    # 5. 투자 리서치
    # ------------------------------------------------------------------ #
    "investment_research": ResearchTemplate(
        template_id="investment_research",
        name="투자 리서치",
        name_en="Investment Research",
        description="기업의 재무 상태, 밸류에이션, 투자 매력도를 분석합니다.",
        category="finance",
        workflow_overrides={
            "enable_fact_check": True,
            "enable_data_analysis": True,
            "min_search_sources": 5,
        },
        required_agents=[
            "realtime_data_search",
            "realtime_info_search",
        ],
        recommended_skills=["sec-edgar", "news-api", "openalex"],
        research_guidance=(
            "다음 항목을 분석하세요:\n"
            "1. 재무제표 분석 (매출, 영업이익, 순이익 추이)\n"
            "2. 주요 재무 비율 (P/E, P/B, ROE, 부채비율 등)\n"
            "3. 성장률 및 수익성 트렌드\n"
            "4. 경쟁사 대비 밸류에이션 비교\n"
            "5. 최근 뉴스, 이슈, 경영진 변화\n"
            "6. 투자 의견 요약 (매수/보유/매도 논거)\n\n"
            "재무 수치는 반드시 출처와 기준일을 명시하세요.\n"
            "⚠️ 이 분석은 투자 권유가 아닌 정보 제공 목적입니다."
        ),
        output_format="report",
        parameter_schema={
            "company": "분석할 기업명",
            "ticker": "주식 티커 (선택)",
        },
    ),
}


def get_template(template_id: str) -> Optional[ResearchTemplate]:
    """템플릿 ID로 조회"""
    return RESEARCH_TEMPLATES.get(template_id)


def list_templates(category: Optional[str] = None) -> List[ResearchTemplate]:
    """템플릿 목록 반환. category로 필터링 가능."""
    templates = list(RESEARCH_TEMPLATES.values())
    if category:
        templates = [t for t in templates if t.category == category]
    return templates
