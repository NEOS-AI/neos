"""
Academic Identifier Extractor

학술 자료의 고유 식별자를 URL과 텍스트에서 자동으로 추출합니다.

지원 식별자:
- DOI (Digital Object Identifier)
- arXiv ID
- PubMed ID (PMID)
- ISBN
- ISSN

★ Learning Point ─────────────────
학술 인용의 신뢰성을 높이는 핵심:
1. Persistent Identifier (영구적 식별자)
2. 출판사나 플랫폼 변경과 무관
3. 전 세계적으로 유일한 식별자

DOI 예시: 10.1038/s41586-019-1666-5
arXiv 예시: 2301.12345
─────────────────────────────────
"""

import re
import logging
from typing import Optional, Dict, Any
from dataclasses import dataclass
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


@dataclass
class AcademicIdentifiers:
    """학술 자료 식별자 모음"""
    doi: Optional[str] = None
    arxiv_id: Optional[str] = None
    pmid: Optional[str] = None  # PubMed ID
    isbn: Optional[str] = None
    issn: Optional[str] = None

    # Metadata from identifiers
    publisher: Optional[str] = None
    journal: Optional[str] = None

    def has_identifiers(self) -> bool:
        """식별자가 하나라도 있는지 확인"""
        return any([self.doi, self.arxiv_id, self.pmid, self.isbn, self.issn])

    def get_primary_identifier(self) -> Optional[str]:
        """
        주 식별자 반환 (우선순위: DOI > arXiv > PMID)

        ★ Learning Point ─────────────────
        우선순위 이유:
        1. DOI: 가장 보편적, 모든 학술 자료
        2. arXiv: 물리/수학/CS 분야 표준
        3. PMID: 의학/생물학 분야 표준
        ─────────────────────────────────
        """
        if self.doi:
            return f"doi:{self.doi}"
        elif self.arxiv_id:
            return f"arXiv:{self.arxiv_id}"
        elif self.pmid:
            return f"PMID:{self.pmid}"
        elif self.isbn:
            return f"ISBN:{self.isbn}"
        return None

    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리 변환"""
        return {
            "doi": self.doi,
            "arxiv_id": self.arxiv_id,
            "pmid": self.pmid,
            "isbn": self.isbn,
            "issn": self.issn,
            "publisher": self.publisher,
            "journal": self.journal,
        }


class AcademicIdentifierExtractor:
    """
    학술 식별자 추출기

    URL, 텍스트, 메타데이터에서 학술 식별자를 자동으로 추출
    """

    # Regular expressions for identifiers
    DOI_PATTERN = re.compile(
        r'10\.\d{4,9}/[-._;()/:A-Za-z0-9]+',
        re.IGNORECASE
    )

    ARXIV_PATTERN = re.compile(
        r'(?:arXiv:)?(\d{4}\.\d{4,5}(?:v\d+)?)',
        re.IGNORECASE
    )

    PMID_PATTERN = re.compile(
        r'(?:PMID:?\s*|pubmed/)(\d{7,8})',
        re.IGNORECASE
    )

    ISBN_PATTERN = re.compile(
        r'ISBN(?:-1[03])?:?\s*((?:\d{1,5}[-\s]?){3,5}\d{1,5})',
        re.IGNORECASE
    )

    ISSN_PATTERN = re.compile(
        r'ISSN:?\s*(\d{4}-\d{3}[\dxX])',
        re.IGNORECASE
    )

    # Domain-based identifier extraction
    ACADEMIC_DOMAINS = {
        'doi.org': 'doi',
        'dx.doi.org': 'doi',
        'arxiv.org': 'arxiv',
        'pubmed.ncbi.nlm.nih.gov': 'pmid',
        'ncbi.nlm.nih.gov/pubmed': 'pmid',
    }

    @classmethod
    def extract_from_url(cls, url: str) -> AcademicIdentifiers:
        """
        URL에서 식별자 추출

        Args:
            url: 학술 자료 URL

        Returns:
            추출된 식별자들

        ★ Learning Point ─────────────────
        학술 플랫폼별 URL 패턴:

        DOI:
        - https://doi.org/10.1038/nature12345
        - https://dx.doi.org/10.1126/science.abc123

        arXiv:
        - https://arxiv.org/abs/2301.12345
        - https://arxiv.org/pdf/2301.12345.pdf

        PubMed:
        - https://pubmed.ncbi.nlm.nih.gov/12345678/
        ─────────────────────────────────
        """
        identifiers = AcademicIdentifiers()

        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
            path = parsed.path

            # DOI URLs
            if 'doi.org' in domain:
                doi_match = cls.DOI_PATTERN.search(path)
                if doi_match:
                    identifiers.doi = doi_match.group(0)
                    identifiers.publisher = cls._infer_publisher_from_doi(identifiers.doi)

            # arXiv URLs
            elif 'arxiv.org' in domain:
                arxiv_match = cls.ARXIV_PATTERN.search(path)
                if arxiv_match:
                    identifiers.arxiv_id = arxiv_match.group(1)
                    identifiers.publisher = "arXiv"

            # PubMed URLs
            elif 'pubmed' in domain or 'ncbi.nlm.nih.gov' in domain:
                pmid_match = re.search(r'/(\d{7,8})/?', path)
                if pmid_match:
                    identifiers.pmid = pmid_match.group(1)
                    identifiers.publisher = "PubMed"

            # Nature, Science, etc. (직접 DOI 포함)
            elif any(pub in domain for pub in ['nature.com', 'science.org', 'cell.com']):
                doi_match = cls.DOI_PATTERN.search(url)
                if doi_match:
                    identifiers.doi = doi_match.group(0)
                    identifiers.publisher = domain.split('.')[0].title()

        except Exception as e:
            logger.debug(f"Identifier extraction failed for {url}: {e}")

        return identifiers

    @classmethod
    def extract_from_text(cls, text: str) -> AcademicIdentifiers:
        """
        텍스트에서 식별자 추출

        Args:
            text: 분석할 텍스트 (제목, 설명, 메타데이터 등)

        Returns:
            추출된 식별자들
        """
        identifiers = AcademicIdentifiers()

        # DOI 추출
        doi_match = cls.DOI_PATTERN.search(text)
        if doi_match:
            identifiers.doi = doi_match.group(0)
            identifiers.publisher = cls._infer_publisher_from_doi(identifiers.doi)

        # arXiv ID 추출
        arxiv_match = cls.ARXIV_PATTERN.search(text)
        if arxiv_match:
            identifiers.arxiv_id = arxiv_match.group(1)
            identifiers.publisher = "arXiv"

        # PMID 추출
        pmid_match = cls.PMID_PATTERN.search(text)
        if pmid_match:
            identifiers.pmid = pmid_match.group(1)
            identifiers.publisher = "PubMed"

        # ISBN 추출
        isbn_match = cls.ISBN_PATTERN.search(text)
        if isbn_match:
            identifiers.isbn = isbn_match.group(1).replace('-', '').replace(' ', '')

        # ISSN 추출
        issn_match = cls.ISSN_PATTERN.search(text)
        if issn_match:
            identifiers.issn = issn_match.group(1)

        return identifiers

    @classmethod
    def extract(cls, url: str, content: str = "", metadata: Dict[str, Any] = None) -> AcademicIdentifiers:
        """
        종합 추출: URL, 콘텐츠, 메타데이터 모두 분석

        Args:
            url: 소스 URL
            content: 소스 내용
            metadata: 추가 메타데이터

        Returns:
            통합된 식별자 정보
        """
        # URL에서 추출
        identifiers = cls.extract_from_url(url)

        # 콘텐츠에서 추가 추출 (URL에서 못 찾은 경우)
        if not identifiers.has_identifiers() and content:
            text_identifiers = cls.extract_from_text(content[:1000])  # 처음 1000자만
            identifiers = cls._merge_identifiers(identifiers, text_identifiers)

        # 메타데이터에서 추가 정보
        if metadata:
            if not identifiers.doi and 'doi' in metadata:
                identifiers.doi = metadata['doi']
            if not identifiers.arxiv_id and 'arxiv_id' in metadata:
                identifiers.arxiv_id = metadata['arxiv_id']
            if not identifiers.journal and 'journal' in metadata:
                identifiers.journal = metadata['journal']

        return identifiers

    @staticmethod
    def _infer_publisher_from_doi(doi: str) -> Optional[str]:
        """
        DOI prefix로 출판사 추론

        ★ Learning Point ─────────────────
        DOI Prefix 구조: 10.XXXX/...
        - 10.1038: Nature Publishing Group
        - 10.1126: Science (AAAS)
        - 10.1016: Elsevier
        - 10.1007: Springer
        ─────────────────────────────────
        """
        prefix_map = {
            '10.1038': 'Nature',
            '10.1126': 'Science',
            '10.1016': 'Elsevier',
            '10.1007': 'Springer',
            '10.1109': 'IEEE',
            '10.1145': 'ACM',
            '10.1371': 'PLOS',
            '10.3389': 'Frontiers',
        }

        prefix = doi.split('/')[0]
        return prefix_map.get(prefix)

    @staticmethod
    def _merge_identifiers(primary: AcademicIdentifiers, secondary: AcademicIdentifiers) -> AcademicIdentifiers:
        """두 식별자 객체 병합 (primary 우선)"""
        merged = AcademicIdentifiers()

        merged.doi = primary.doi or secondary.doi
        merged.arxiv_id = primary.arxiv_id or secondary.arxiv_id
        merged.pmid = primary.pmid or secondary.pmid
        merged.isbn = primary.isbn or secondary.isbn
        merged.issn = primary.issn or secondary.issn
        merged.publisher = primary.publisher or secondary.publisher
        merged.journal = primary.journal or secondary.journal

        return merged

    @staticmethod
    def format_identifier_for_citation(identifiers: AcademicIdentifiers, style: str = "default") -> str:
        """
        Citation에 포함할 식별자 포맷팅

        Args:
            identifiers: 식별자 정보
            style: Citation 스타일

        Returns:
            포맷된 식별자 문자열

        Examples:
            - "DOI: 10.1038/nature12345"
            - "arXiv:2301.12345"
            - "PMID: 12345678"
        """
        parts = []

        if identifiers.doi:
            if style == "url":
                parts.append(f"https://doi.org/{identifiers.doi}")
            else:
                parts.append(f"DOI: {identifiers.doi}")

        if identifiers.arxiv_id:
            if style == "url":
                parts.append(f"https://arxiv.org/abs/{identifiers.arxiv_id}")
            else:
                parts.append(f"arXiv:{identifiers.arxiv_id}")

        if identifiers.pmid:
            if style == "url":
                parts.append(f"https://pubmed.ncbi.nlm.nih.gov/{identifiers.pmid}/")
            else:
                parts.append(f"PMID: {identifiers.pmid}")

        return " | ".join(parts) if parts else ""
