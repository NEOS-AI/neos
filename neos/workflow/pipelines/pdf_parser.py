"""
PDF 파싱 유틸리티

PyMuPDF를 주 파서로 사용하고, PyPDF2를 fallback으로 사용하여
PDF 문서에서 텍스트, 메타데이터, 표, 이미지를 추출합니다.
"""

from typing import Dict, Any, List, Optional
import io
from datetime import datetime


class PDFParser:
    """
    PDF 파서

    PyMuPDF(fitz)를 주 파서로 사용하고, PyPDF2를 fallback으로 사용하여
    PDF 파일을 파싱하고 텍스트, 메타데이터, 표, 이미지를 추출합니다.
    """

    def __init__(self):
        self.supports_pymupdf = self._check_pymupdf()
        self.supports_pypdf2 = self._check_pypdf2()

    def _check_pymupdf(self) -> bool:
        """PyMuPDF 설치 여부 확인"""
        try:
            import fitz  # noqa: F401
            return True
        except ImportError:
            return False

    def _check_pypdf2(self) -> bool:
        """PyPDF2 설치 여부 확인"""
        try:
            import PyPDF2 # noqa: F401
            return True
        except ImportError:
            return False

    def is_available(self) -> bool:
        """파서 사용 가능 여부 (PyMuPDF 또는 PyPDF2)"""
        return self.supports_pymupdf or self.supports_pypdf2

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
            ImportError: PyMuPDF와 PyPDF2 모두 설치되지 않은 경우
            ValueError: 파일 내용이나 경로가 제공되지 않은 경우
        """
        if not self.is_available():
            raise ImportError(
                "Neither PyMuPDF nor PyPDF2 is installed. "
                "Install with: pip install pymupdf or pip install PyPDF2"
            )

        if not file_content and not file_path:
            raise ValueError("Either file_content or file_path must be provided")

        # PyMuPDF 우선 시도
        if self.supports_pymupdf:
            try:
                return await self._parse_with_pymupdf(file_content, file_path)
            except Exception as e:
                # PyPDF2로 fallback
                if self.supports_pypdf2:
                    return await self._parse_with_pypdf2(file_content, file_path)
                else:
                    return {
                        "text": "",
                        "page_count": 0,
                        "error": f"PyMuPDF failed: {str(e)}",
                        "extraction_method": "PyMuPDF (failed)",
                    }

        # PyMuPDF가 없으면 PyPDF2 사용
        elif self.supports_pypdf2:
            return await self._parse_with_pypdf2(file_content, file_path)

        else:
            raise ImportError(
                "No PDF parser available. Install PyMuPDF or PyPDF2"
            )

    async def _parse_with_pymupdf(
        self,
        file_content: Optional[bytes] = None,
        file_path: Optional[str] = None
    ) -> Dict[str, Any]:
        """PyMuPDF를 사용한 PDF 파싱"""
        import fitz

        try:
            # PDF 문서 열기
            if file_content:
                doc = fitz.open(stream=file_content, filetype="pdf")
            else:
                doc = fitz.open(file_path)

            try:
                # 기본 정보 추출
                page_count = len(doc)
                is_encrypted = doc.is_encrypted
                metadata = doc.metadata

                # 텍스트, 표, 이미지 추출
                all_text = []
                all_tables = []
                all_images = []
                pages_info = []

                for page_num in range(page_count):
                    page = doc[page_num]

                    # 텍스트 추출
                    text = page.get_text()
                    all_text.append(text)

                    # 표 추출
                    tables = self._extract_tables_pymupdf(page)
                    if tables:
                        all_tables.extend(tables)

                    # 이미지 추출
                    images = self._extract_images_pymupdf(page, doc)
                    if images:
                        all_images.extend(images)

                    # 페이지 정보
                    page_info = {
                        "page_number": page_num + 1,
                        "text_length": len(text),
                        "width": page.rect.width,
                        "height": page.rect.height,
                        "table_count": len(tables),
                        "image_count": len(images),
                    }
                    pages_info.append(page_info)

                combined_text = "\n\n".join(all_text)

                result = {
                    "text": combined_text,
                    "page_count": page_count,
                    "is_encrypted": is_encrypted,
                    "metadata": self._clean_metadata(metadata),
                    "pages": pages_info,
                    "char_count": len(combined_text),
                    "word_count": len(combined_text.split()),
                    "has_images": len(all_images) > 0,
                    "has_tables": len(all_tables) > 0,
                    "tables": all_tables,
                    "images": all_images,
                    "extraction_method": "PyMuPDF",
                }

                return result

            finally:
                doc.close()

        except Exception as e:
            return {
                "text": "",
                "page_count": 0,
                "error": str(e),
                "extraction_method": "PyMuPDF",
            }

    def _extract_tables_pymupdf(self, page) -> List[Dict[str, Any]]:
        """PyMuPDF를 사용한 표 추출"""
        tables_data = []

        try:
            tables = page.find_tables()

            for table_index, table in enumerate(tables):
                table_dict = {
                    "page_number": page.number + 1,
                    "table_index": table_index,
                    "bbox": list(table.bbox),  # (x0, y0, x1, y1)
                    "data": table.extract(),
                    "row_count": len(table.extract()) if table.extract() else 0,
                    "col_count": len(table.extract()[0]) if table.extract() and len(table.extract()) > 0 else 0,
                }
                tables_data.append(table_dict)

        except Exception:
            # 표 추출 실패는 에러로 처리하지 않음 (일부 PDF는 표가 없을 수 있음)
            pass

        return tables_data

    def _extract_images_pymupdf(self, page, doc) -> List[Dict[str, Any]]:
        """PyMuPDF를 사용한 이미지 추출"""
        images_data = []

        try:
            image_list = page.get_images()

            for img_index, img in enumerate(image_list):
                xref = img[0]

                try:
                    base_image = doc.extract_image(xref)

                    image_dict = {
                        "page_number": page.number + 1,
                        "image_index": img_index,
                        "xref": xref,
                        "ext": base_image["ext"],
                        "width": base_image["width"],
                        "height": base_image["height"],
                        "colorspace": base_image.get("colorspace"),
                        "bpc": base_image.get("bpc"),  # bits per component
                        "size": len(base_image["image"]),
                        "image_bytes": base_image["image"],
                    }
                    images_data.append(image_dict)

                except Exception:
                    # 개별 이미지 추출 실패는 건너뜀
                    continue

        except Exception:
            # 이미지 추출 실패는 에러로 처리하지 않음
            pass

        return images_data

    def _clean_metadata(self, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """PyMuPDF 메타데이터 정리"""
        cleaned = {}

        if not metadata:
            return cleaned

        # 표준 메타데이터 필드
        standard_fields = [
            'title', 'author', 'subject', 'keywords',
            'creator', 'producer', 'creationDate', 'modDate'
        ]

        for field in standard_fields:
            if field in metadata and metadata[field]:
                # 날짜 필드 변환
                if 'Date' in field:
                    cleaned[field] = self._parse_pdf_date(metadata[field])
                else:
                    cleaned[field] = metadata[field]

        return cleaned

    async def _parse_with_pypdf2(
        self,
        file_content: Optional[bytes] = None,
        file_path: Optional[str] = None
    ) -> Dict[str, Any]:
        """PyPDF2를 사용한 PDF 파싱 (fallback)"""
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
