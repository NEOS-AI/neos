"""Builtin Skills for NEOS

이 모듈은 NEOS에 내장된 기본 스킬들을 제공합니다.
"""

from pathlib import Path
from typing import List

from neos.skills.manager.skill_registry import SkillInfo
from neos.skills.base import SkillType

# Import builtin skills
from .bigquery import BigQuerySkill
from .docx import DocxSkill
from .pdf import PdfSkill
from .research_assistant import ResearchAssistantSkill
from .arxiv import ArxivSkill
from .pubmed import PubmedSkill
from .wikipedia import WikipediaSkill


def get_builtin_skills() -> List[SkillInfo]:
    """내장 스킬 목록 가져오기

    Returns:
        SkillInfo 객체 목록
    """
    # 스킬 디렉토리 경로
    skills_dir = Path(__file__).parent

    builtin_skills = [
        SkillInfo(
            name="bigquery",
            skill_class=BigQuerySkill,
            skill_type=SkillType.DATABASE,
            description="BigQuery 데이터베이스 조회 및 분석",
            capabilities=[
                "sql_query",
                "data_retrieval",
                "data_analysis",
                "bigquery",
            ],
            version="1.0.0",
            skill_dir=skills_dir / "bigquery",
        ),
        SkillInfo(
            name="docx",
            skill_class=DocxSkill,
            skill_type=SkillType.DOCUMENT,
            description="Microsoft Word 문서 읽기, 생성, 편집",
            capabilities=[
                "document_reading",
                "document_creation",
                "document_editing",
                "text_extraction",
            ],
            version="1.0.0",
            skill_dir=skills_dir / "docx",
        ),
        SkillInfo(
            name="pdf",
            skill_class=PdfSkill,
            skill_type=SkillType.DOCUMENT,
            description="PDF 문서 읽기, 텍스트 추출, 생성",
            capabilities=[
                "document_reading",
                "text_extraction",
                "pdf_parsing",
                "document_creation",
            ],
            version="1.0.0",
            skill_dir=skills_dir / "pdf",
        ),
        SkillInfo(
            name="research_assistant",
            skill_class=ResearchAssistantSkill,
            skill_type=SkillType.RESEARCH,
            description="리서치 작업 보조 - 소스 분석, 요약, 참고문헌 정리",
            capabilities=[
                "source_analysis",
                "text_summarization",
                "reference_extraction",
                "insight_generation",
                "research_support",
            ],
            version="1.0.0",
            skill_dir=skills_dir / "research_assistant",
        ),
        SkillInfo(
            name="arxiv",
            skill_class=ArxivSkill,
            skill_type=SkillType.RESEARCH,
            description="ArXiv 학술 논문 검색 - 물리학, 수학, 컴퓨터 과학, AI/ML 등",
            capabilities=[
                "paper_search",
                "academic_research",
                "arxiv_query",
                "metadata_extraction",
                "research_support",
            ],
            version="1.0.0",
            skill_dir=skills_dir / "arxiv",
        ),
        SkillInfo(
            name="pubmed",
            skill_class=PubmedSkill,
            skill_type=SkillType.RESEARCH,
            description="PubMed 의학/생물학 논문 검색 - 의학, 생명과학, 바이오메디컬 분야",
            capabilities=[
                "medical_research",
                "biomedical_search",
                "pubmed_query",
                "paper_search",
                "metadata_extraction",
                "research_support",
            ],
            version="1.0.0",
            skill_dir=skills_dir / "pubmed",
        ),
        SkillInfo(
            name="wikipedia",
            skill_class=WikipediaSkill,
            skill_type=SkillType.RESEARCH,
            description="Wikipedia 일반 지식 검색 - 개념 정의, 배경 정보, 일반 지식",
            capabilities=[
                "knowledge_search",
                "concept_definition",
                "background_research",
                "general_information",
                "research_support",
            ],
            version="1.0.0",
            skill_dir=skills_dir / "wikipedia",
        ),
    ]

    return builtin_skills


__all__ = [
    "get_builtin_skills",
    "BigQuerySkill",
    "DocxSkill",
    "PdfSkill",
    "ResearchAssistantSkill",
    "ArxivSkill",
    "PubmedSkill",
    "WikipediaSkill",
]
