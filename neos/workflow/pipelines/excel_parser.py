"""
Excel 파일 파싱 유틸리티

openpyxl을 사용하여 Excel 파일에서 데이터, 수식, 차트 정보를 추출합니다.
"""

from typing import Dict, Any, List, Optional
import io
from pathlib import Path


class ExcelParser:
    """
    Excel 파일 파서

    openpyxl을 사용하여 XLSX 파일을 파싱하고 데이터와 구조를 추출합니다.
    """

    def __init__(self):
        self.supports_openpyxl = self._check_openpyxl()

    def _check_openpyxl(self) -> bool:
        """openpyxl 설치 여부 확인"""
        try:
            import openpyxl
            return True
        except ImportError:
            return False

    def is_available(self) -> bool:
        """파서 사용 가능 여부"""
        return self.supports_openpyxl

    async def parse(
        self,
        file_content: Optional[bytes] = None,
        file_path: Optional[str] = None,
        max_rows_per_sheet: int = 1000
    ) -> Dict[str, Any]:
        """
        Excel 파일 파싱

        Args:
            file_content: Excel 파일 바이너리 내용
            file_path: Excel 파일 경로
            max_rows_per_sheet: 시트당 최대 읽을 행 수

        Returns:
            파싱 결과 딕셔너리

        Raises:
            ImportError: openpyxl이 설치되지 않은 경우
            ValueError: 파일 내용이나 경로가 제공되지 않은 경우
        """
        if not self.is_available():
            raise ImportError(
                "openpyxl is not installed. Install it with: pip install openpyxl"
            )

        if not file_content and not file_path:
            raise ValueError("Either file_content or file_path must be provided")

        try:
            from openpyxl import load_workbook

            # Excel 파일 열기
            if file_content:
                workbook = load_workbook(io.BytesIO(file_content), data_only=True)
            else:
                workbook = load_workbook(file_path, data_only=True)

            # 시트 정보 추출
            sheets_data = self._extract_sheets(workbook, max_rows_per_sheet)

            # 텍스트 생성
            text = self._generate_text_summary(sheets_data)

            # 메타데이터 추출
            metadata = self._extract_metadata(workbook)

            result = {
                "text": text,
                "sheet_count": len(workbook.sheetnames),
                "sheet_names": workbook.sheetnames,
                "sheets": sheets_data,
                "has_formulas": any(s.get("has_formulas") for s in sheets_data),
                "has_charts": any(s.get("chart_count", 0) > 0 for s in sheets_data),
                "metadata": metadata,
                "total_rows": sum(s.get("row_count", 0) for s in sheets_data),
                "total_cols": max(s.get("col_count", 0) for s in sheets_data),
                "extraction_method": "openpyxl",
            }

            return result

        except Exception as e:
            return {
                "text": "",
                "sheet_count": 0,
                "error": str(e),
                "extraction_method": "openpyxl",
            }

    def _extract_sheets(self, workbook, max_rows: int) -> List[Dict[str, Any]]:
        """시트별 데이터 추출"""
        sheets_data = []

        try:
            for sheet in workbook.worksheets:
                sheet_info = {
                    "sheet_name": sheet.title,
                    "row_count": sheet.max_row,
                    "col_count": sheet.max_column,
                    "data": [],
                    "has_formulas": False,
                    "chart_count": len(sheet._charts) if hasattr(sheet, '_charts') else 0,
                }

                # 데이터 추출 (최대 행 제한)
                rows_to_read = min(sheet.max_row, max_rows)

                for row_idx, row in enumerate(sheet.iter_rows(max_row=rows_to_read, values_only=False), 1):
                    row_data = []
                    for cell in row:
                        # 셀 값 추출
                        value = cell.value

                        # 수식 감지
                        if hasattr(cell, 'data_type') and cell.data_type == 'f':
                            sheet_info["has_formulas"] = True

                        # None을 빈 문자열로 변환
                        if value is None:
                            value = ""
                        else:
                            value = str(value)

                        row_data.append(value)

                    sheet_info["data"].append(row_data)

                sheets_data.append(sheet_info)

        except Exception as e:
            sheets_data.append({"error": str(e)})

        return sheets_data

    def _generate_text_summary(self, sheets_data: List[Dict[str, Any]]) -> str:
        """시트 데이터에서 텍스트 요약 생성"""
        text_parts = []

        for sheet in sheets_data:
            if "error" in sheet:
                continue

            sheet_name = sheet.get("sheet_name", "Unknown")
            text_parts.append(f"=== Sheet: {sheet_name} ===")

            # 데이터를 텍스트로 변환
            data = sheet.get("data", [])
            for row in data[:100]:  # 처음 100행만 텍스트로
                row_text = " | ".join(str(cell) for cell in row if cell)
                if row_text.strip():
                    text_parts.append(row_text)

            text_parts.append("")  # 시트 간 구분

        return "\n".join(text_parts)

    def _extract_metadata(self, workbook) -> Dict[str, Any]:
        """Excel 메타데이터 추출"""
        metadata = {}

        try:
            props = workbook.properties

            if props:
                metadata_fields = {
                    'title': props.title,
                    'creator': props.creator,
                    'subject': props.subject,
                    'description': props.description,
                    'keywords': props.keywords,
                    'category': props.category,
                    'last_modified_by': props.lastModifiedBy,
                    'created': props.created,
                    'modified': props.modified,
                }

                for key, value in metadata_fields.items():
                    if value:
                        # datetime 객체를 문자열로 변환
                        if hasattr(value, 'isoformat'):
                            value = value.isoformat()
                        metadata[key] = value

        except Exception as e:
            metadata['extraction_error'] = str(e)

        return metadata


# 편의 함수
async def parse_excel(
    file_content: Optional[bytes] = None,
    file_path: Optional[str] = None,
    max_rows_per_sheet: int = 1000
) -> Dict[str, Any]:
    """
    Excel 파일 파싱 편의 함수

    Args:
        file_content: Excel 바이너리 내용
        file_path: Excel 파일 경로
        max_rows_per_sheet: 시트당 최대 행 수

    Returns:
        파싱 결과
    """
    parser = ExcelParser()
    return await parser.parse(
        file_content=file_content,
        file_path=file_path,
        max_rows_per_sheet=max_rows_per_sheet
    )
