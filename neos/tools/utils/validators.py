"""Validators for MCP tools"""

from pathlib import Path
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class PathValidator:
    """파일 경로 검증 유틸리티

    보안을 위한 경로 검증 기능을 제공합니다.
    """

    @staticmethod
    def validate_path(
        file_path: str, work_dir: Path, allow_absolute: bool = True
    ) -> Optional[Path]:
        """파일 경로 검증

        Args:
            file_path: 검증할 파일 경로
            work_dir: 작업 디렉토리 (기준 경로)
            allow_absolute: 절대 경로 허용 여부

        Returns:
            검증된 Path 객체 (실패 시 None)
        """
        try:
            target_path = Path(file_path)

            # 절대 경로 처리
            if target_path.is_absolute():
                if not allow_absolute:
                    logger.warning(f"Absolute path not allowed: {file_path}")
                    return None

                # 작업 디렉토리 내부인지 확인
                try:
                    target_path.resolve().relative_to(work_dir.resolve())
                except ValueError:
                    logger.warning(
                        f"Path outside work directory: {file_path}"
                    )
                    return None

            else:
                # 상대 경로를 절대 경로로 변환
                target_path = work_dir / target_path

            # 경로 정규화
            target_path = target_path.resolve()

            # 다시 한번 작업 디렉토리 내부 확인
            try:
                target_path.relative_to(work_dir.resolve())
            except ValueError:
                logger.warning(
                    f"Resolved path outside work directory: {target_path}"
                )
                return None

            return target_path

        except Exception as e:
            logger.error(f"Path validation error: {e}")
            return None

    @staticmethod
    def is_safe_path(file_path: Path) -> bool:
        """안전한 경로인지 확인

        Args:
            file_path: 확인할 경로

        Returns:
            안전 여부
        """
        # 위험한 경로 패턴 체크
        dangerous_patterns = [
            "..",  # 부모 디렉토리 접근
            "~",  # 홈 디렉토리
        ]

        path_str = str(file_path)
        for pattern in dangerous_patterns:
            if pattern in path_str:
                return False

        return True
