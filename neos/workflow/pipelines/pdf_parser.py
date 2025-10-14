"""
PDF 파싱 유틸리티

PyPDF2를 사용하여 PDF 문서에서 텍스트와 메타데이터를 추출합니다.
"""

from typing import Dict, Any, List, Optional
import io
from datetime import datetime


class PDFParser:
    """
    PDF 파서

    PyPDF2를 사용하여 PDF 파일을 파싱하고 텍스트와 메타데이터를 추출합니다.
    """

    def __init__(self):
        self.supports_pypdf2 = self._check_pypdf2()

    def _check_pypdf2(self) -> bool:
        """PyPDF2 설치 여부 확인"""
        try:
            import PyPDF2 # noqa: F401
            return True
        except ImportError:
            return False

    def is_available(self) -> bool:
        """파서 사용 가능 여부"""
        return self.supports_pypdf2

    async def parse(
        self,
        file_content: Optional[bytes] = None,
        file_path: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        PDF 파일 파싱

        Args:
            file_content: PDF 파일 바이너리 내용
            file_path: PDF 파일 경로

        Returns:
            파싱 결과 딕셔너리

        Raises:
            ImportError: PyPDF2가 설치되지 않은 경우
            ValueError: 파일 내용이나 경로가 제공되지 않은 경우
        """
        if not self.is_available():
            raise ImportError(
                "PyPDF2 is not installed. Install it with: pip install PyPDF2"
            )

        if not file_content and not file_path:
            raise ValueError("Either file_content or file_path must be provided")

        try:
            import PyPDF2

            # PDF 파일 열기
            if file_content:
                pdf_file = io.BytesIO(file_content)
            else:
                pdf_file = open(file_path, 'rb')

            try:
                # PdfReader 생성
                reader = PyPDF2.PdfReader(pdf_file)

                # 기본 정보 추출
                page_count = len(reader.pages)
                is_encrypted = reader.is_encrypted

                # 메타데이터 추출
                metadata = self._extract_metadata(reader)

                # 텍스트 추출
                text_result = self._extract_text(reader)

                # 페이지별 정보
                pages_info = self._extract_pages_info(reader)

                result = {
                    "text": text_result["text"],
                    "page_count": page_count,
                    "is_encrypted": is_encrypted,
                    "metadata": metadata,
                    "pages": pages_info,
                    "char_count": len(text_result["text"]),
                    "word_count": len(text_result["text"].split()),
                    "has_images": text_result.get("has_images", False),
                    "has_tables": False,  # PyPDF2는 테이블 감지 미지원
                    "extraction_method": "PyPDF2",
                }

                return result

            finally:
                # 파일 닫기
                if isinstance(pdf_file, io.BytesIO):
                    pdf_file.close()
                else:
                    pdf_file.close()

        except Exception as e:
            return {
                "text": "",
                "page_count": 0,
                "error": str(e),
                "extraction_method": "PyPDF2",
            }

    def _extract_metadata(self, reader) -> Dict[str, Any]:
        """PDF 메타데이터 추출"""
        metadata = {}

        try:
            if hasattr(reader, 'metadata') and reader.metadata:
                raw_metadata = reader.metadata

                # 일반적인 메타데이터 필드
                metadata_fields = {
                    '/Title': 'title',
                    '/Author': 'author',
                    '/Subject': 'subject',
                    '/Creator': 'creator',
                    '/Producer': 'producer',
                    '/CreationDate': 'creation_date',
                    '/ModDate': 'modification_date',
                    '/Keywords': 'keywords',
                }

                for pdf_key, key in metadata_fields.items():
                    if pdf_key in raw_metadata:
                        value = raw_metadata[pdf_key]
                        # 날짜 형식 변환
                        if 'date' in key.lower() and isinstance(value, str):
                            value = self._parse_pdf_date(value)
                        metadata[key] = value

        except Exception as e:
            metadata['extraction_error'] = str(e)

        return metadata

    def _extract_text(self, reader) -> Dict[str, Any]:
        """PDF에서 텍스트 추출"""
        all_text = []
        has_images = False

        try:
            for page_num, page in enumerate(reader.pages):
                try:
                    # 페이지 텍스트 추출
                    text = page.extract_text()
                    if text:
                        all_text.append(text)

                    # 이미지 존재 여부 확인 (간단한 휴리스틱)
                    if hasattr(page, '/Resources') and '/XObject' in page['/Resources']:
                        has_images = True

                except Exception as e:
                    all_text.append(f"[Page {page_num + 1} extraction error: {str(e)}]")

            combined_text = "\n\n".join(all_text)

            return {
                "text": combined_text,
                "has_images": has_images,
            }

        except Exception as e:
            return {
                "text": f"Text extraction error: {str(e)}",
                "has_images": False,
            }

    def _extract_pages_info(self, reader) -> List[Dict[str, Any]]:
        """페이지별 정보 추출"""
        pages_info = []

        try:
            for page_num, page in enumerate(reader.pages):
                page_info = {
                    "page_number": page_num + 1,
                    "text_length": 0,
                }

                try:
                    text = page.extract_text()
                    page_info["text_length"] = len(text) if text else 0

                    # 페이지 크기 (가능한 경우)
                    if hasattr(page, 'mediabox'):
                        page_info["width"] = float(page.mediabox.width)
                        page_info["height"] = float(page.mediabox.height)

                except Exception as e:
                    page_info["error"] = str(e)

                pages_info.append(page_info)

        except Exception as e:
            pages_info.append({"error": str(e)})

        return pages_info

    def _parse_pdf_date(self, date_str: str) -> str:
        """
        PDF 날짜 형식 파싱

        PDF 날짜 형식: D:YYYYMMDDHHmmSSOHH'mm'
        예: D:20230101120000+09'00'
        """
        try:
            if date_str.startswith('D:'):
                date_str = date_str[2:]

            # 기본 날짜 부분 추출 (YYYYMMDDHHMMSS)
            if len(date_str) >= 14:
                year = int(date_str[0:4])
                month = int(date_str[4:6])
                day = int(date_str[6:8])
                hour = int(date_str[8:10])
                minute = int(date_str[10:12])
                second = int(date_str[12:14])

                dt = datetime(year, month, day, hour, minute, second)
                return dt.isoformat()

            return date_str

        except Exception:
            return date_str


# 편의 함수
async def parse_pdf(
    file_content: Optional[bytes] = None,
    file_path: Optional[str] = None
) -> Dict[str, Any]:
    """
    PDF 파싱 편의 함수

    Args:
        file_content: PDF 바이너리 내용
        file_path: PDF 파일 경로

    Returns:
        파싱 결과
    """
    parser = PDFParser()
    return await parser.parse(file_content=file_content, file_path=file_path)
