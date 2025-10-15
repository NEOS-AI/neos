"""
CSV 파일 파싱 유틸리티

pandas를 사용하여 CSV 파일에서 데이터와 통계 정보를 추출합니다.
"""

from typing import Dict, Any, List, Optional
import io


class CSVParser:
    """
    CSV 파서

    pandas를 사용하여 CSV 파일을 파싱하고 데이터와 구조를 추출합니다.
    """

    def __init__(self):
        self.supports_pandas = self._check_pandas()

    def _check_pandas(self) -> bool:
        """pandas 설치 여부 확인"""
        try:
            import pandas  # noqa: F401
            return True
        except ImportError:
            return False

    def is_available(self) -> bool:
        """파서 사용 가능 여부"""
        return self.supports_pandas

    async def parse(
        self,
        file_content: Optional[bytes] = None,
        file_path: Optional[str] = None,
        max_rows: int = 10000,
        encoding: str = 'utf-8'
    ) -> Dict[str, Any]:
        """
        CSV 파일 파싱

        Args:
            file_content: CSV 파일 바이너리 내용
            file_path: CSV 파일 경로
            max_rows: 최대 읽을 행 수
            encoding: 파일 인코딩

        Returns:
            파싱 결과 딕셔너리

        Raises:
            ImportError: pandas가 설치되지 않은 경우
            ValueError: 파일 내용이나 경로가 제공되지 않은 경우
        """
        if not self.is_available():
            raise ImportError(
                "pandas is not installed. Install it with: pip install pandas"
            )

        if not file_content and not file_path:
            raise ValueError("Either file_content or file_path must be provided")

        try:
            import pandas as pd

            # CSV 파일 읽기
            if file_content:
                # 여러 인코딩 시도
                df = self._read_csv_with_fallback_encoding(
                    io.BytesIO(file_content), encoding, max_rows, pd
                )
            else:
                df = self._read_csv_with_fallback_encoding(
                    file_path, encoding, max_rows, pd
                )

            # 데이터 추출
            data_info = self._extract_data_info(df)

            # 텍스트 요약 생성
            text = self._generate_text_summary(df, data_info)

            # 통계 정보 추출
            statistics = self._extract_statistics(df)

            # 컬럼 정보 추출
            column_info = self._extract_column_info(df)

            result = {
                "text": text,
                "row_count": len(df),
                "column_count": len(df.columns),
                "columns": column_info,
                "data_preview": data_info["preview"],
                "statistics": statistics,
                "missing_values": data_info["missing_values"],
                "data_types": data_info["data_types"],
                "memory_usage": int(df.memory_usage(deep=True).sum()),
                "extraction_method": "pandas",
            }

            return result

        except Exception as e:
            return {
                "text": "",
                "row_count": 0,
                "column_count": 0,
                "error": str(e),
                "extraction_method": "pandas",
            }

    def _read_csv_with_fallback_encoding(
        self,
        source,
        encoding: str,
        max_rows: int,
        pd
    ):
        """여러 인코딩을 시도하여 CSV 읽기"""
        encodings = [encoding, 'utf-8', 'latin-1', 'cp949', 'euc-kr']

        for enc in encodings:
            try:
                if max_rows > 0:
                    df = pd.read_csv(source, encoding=enc, nrows=max_rows)
                else:
                    df = pd.read_csv(source, encoding=enc)
                return df
            except (UnicodeDecodeError, UnicodeError):
                # BytesIO인 경우 position 리셋
                if hasattr(source, 'seek'):
                    source.seek(0)
                continue
            except Exception as e:
                raise e

        # 모든 인코딩 실패
        raise UnicodeDecodeError(
            'utf-8', b'', 0, 1,
            f'Failed to decode CSV with encodings: {encodings}'
        )

    def _extract_data_info(self, df) -> Dict[str, Any]:
        """데이터 기본 정보 추출"""
        import pandas as pd

        # 데이터 미리보기 (처음 10행)
        preview_rows = min(10, len(df))
        preview = df.head(preview_rows).to_dict('records')

        # 결측치 정보
        missing_values = {}
        for col in df.columns:
            missing_count = df[col].isna().sum()
            if missing_count > 0:
                missing_values[col] = {
                    "count": int(missing_count),
                    "percentage": float(missing_count / len(df) * 100)
                }

        # 데이터 타입 정보
        data_types = {}
        for col in df.columns:
            dtype = str(df[col].dtype)
            data_types[col] = dtype

        return {
            "preview": preview,
            "missing_values": missing_values,
            "data_types": data_types,
        }

    def _generate_text_summary(self, df, data_info: Dict[str, Any]) -> str:
        """CSV 데이터에서 텍스트 요약 생성"""
        text_parts = []

        # 헤더 정보
        text_parts.append("=== CSV Data ===")
        text_parts.append(f"Columns: {', '.join(df.columns.tolist())}")
        text_parts.append("")

        # 데이터 미리보기 (처음 100행을 텍스트로)
        preview_rows = min(100, len(df))
        for idx, row in df.head(preview_rows).iterrows():
            row_text = " | ".join(str(val) for val in row.values)
            text_parts.append(row_text)

        # 통계 요약 추가
        text_parts.append("")
        text_parts.append("=== Summary ===")
        text_parts.append(f"Total Rows: {len(df)}")
        text_parts.append(f"Total Columns: {len(df.columns)}")

        if data_info["missing_values"]:
            text_parts.append("")
            text_parts.append("Missing Values:")
            for col, info in data_info["missing_values"].items():
                text_parts.append(f"  {col}: {info['count']} ({info['percentage']:.2f}%)")

        return "\n".join(text_parts)

    def _extract_statistics(self, df) -> Dict[str, Any]:
        """수치형 컬럼의 통계 정보 추출"""
        import pandas as pd

        statistics = {}

        # 수치형 컬럼만 선택
        numeric_cols = df.select_dtypes(include=['number']).columns

        for col in numeric_cols:
            try:
                col_stats = {
                    "mean": float(df[col].mean()) if not df[col].isna().all() else None,
                    "median": float(df[col].median()) if not df[col].isna().all() else None,
                    "std": float(df[col].std()) if not df[col].isna().all() else None,
                    "min": float(df[col].min()) if not df[col].isna().all() else None,
                    "max": float(df[col].max()) if not df[col].isna().all() else None,
                    "quantile_25": float(df[col].quantile(0.25)) if not df[col].isna().all() else None,
                    "quantile_75": float(df[col].quantile(0.75)) if not df[col].isna().all() else None,
                }
                statistics[col] = col_stats
            except Exception:
                # 통계 계산 실패 시 건너뛰기
                continue

        return statistics

    def _extract_column_info(self, df) -> List[Dict[str, Any]]:
        """컬럼별 상세 정보 추출"""
        columns_info = []

        for col in df.columns:
            col_info = {
                "name": col,
                "dtype": str(df[col].dtype),
                "non_null_count": int(df[col].count()),
                "null_count": int(df[col].isna().sum()),
                "unique_count": int(df[col].nunique()),
            }

            # 수치형 컬럼인 경우
            if df[col].dtype in ['int64', 'float64', 'int32', 'float32']:
                col_info["is_numeric"] = True
            else:
                col_info["is_numeric"] = False

                # 범주형 데이터인 경우 상위 값들 추출
                if df[col].nunique() < 50:  # 고유값이 50개 미만이면 범주형으로 간주
                    top_values = df[col].value_counts().head(10).to_dict()
                    # 키를 문자열로 변환
                    col_info["top_values"] = {str(k): int(v) for k, v in top_values.items()}

            columns_info.append(col_info)

        return columns_info


# 편의 함수
async def parse_csv(
    file_content: Optional[bytes] = None,
    file_path: Optional[str] = None,
    max_rows: int = 10000,
    encoding: str = 'utf-8'
) -> Dict[str, Any]:
    """
    CSV 파일 파싱 편의 함수

    Args:
        file_content: CSV 바이너리 내용
        file_path: CSV 파일 경로
        max_rows: 최대 읽을 행 수
        encoding: 파일 인코딩

    Returns:
        파싱 결과
    """
    parser = CSVParser()
    return await parser.parse(
        file_content=file_content,
        file_path=file_path,
        max_rows=max_rows,
        encoding=encoding
    )
