"""BigQuery Skill implementation"""

from typing import Dict, Any, Optional
import logging
import os

from neos.skills.base import BaseSkill, SkillResult, SkillType


logger = logging.getLogger(__name__)


class BigQuerySkill(BaseSkill):
    """BigQuery 데이터 조회 및 분석 스킬"""

    def __init__(self, **kwargs):
        super().__init__(
            name="bigquery",
            skill_type=SkillType.DATABASE,
            description="BigQuery 데이터베이스 조회 및 분석",
            capabilities=[
                "sql_query",
                "data_retrieval",
                "data_analysis",
                "bigquery",
            ],
            version="1.0.0",
            **kwargs
        )
        self.client = None
        self.project_id = None

    async def initialize(self) -> bool:
        """BigQuery 클라이언트 초기화"""
        try:
            # Google Cloud 라이브러리 임포트 시도
            from google.cloud import bigquery

            # 프로젝트 ID 가져오기
            self.project_id = os.getenv("GCP_PROJECT_ID")

            # 클라이언트 생성
            if self.project_id:
                self.client = bigquery.Client(project=self.project_id)
            else:
                # 프로젝트 ID가 없으면 기본 자격증명 사용
                self.client = bigquery.Client()
                self.project_id = self.client.project

            self.is_available = True
            logger.info(
                f"BigQuery skill initialized successfully "
                f"(project: {self.project_id})"
            )
            return True

        except ImportError:
            logger.warning(
                "BigQuery skill not available: "
                "google-cloud-bigquery package not installed"
            )
            return False
        except Exception as e:
            logger.error(f"Failed to initialize BigQuery skill: {e}")
            return False

    async def execute(self, params: Dict[str, Any]) -> SkillResult:
        """BigQuery 쿼리 실행

        Args:
            params: {
                "query": str,  # SQL 쿼리
                "project_id": str (optional),  # 프로젝트 ID
                "max_results": int (optional),  # 최대 결과 수
            }

        Returns:
            쿼리 실행 결과
        """
        if not self.is_available:
            return SkillResult.error_result(
                error="BigQuery skill not initialized",
                skill_name=self.name,
            )

        query = params.get("query")
        if not query:
            return SkillResult.error_result(
                error="Query parameter is required",
                skill_name=self.name,
            )

        max_results = params.get("max_results", 1000)
        project_id = params.get("project_id", self.project_id)

        try:
            # 쿼리 실행
            logger.info(f"Executing BigQuery query: {query[:100]}...")
            query_job = self.client.query(query, project=project_id)

            # 결과 가져오기
            results = query_job.result(max_results=max_results)

            # 결과를 리스트로 변환
            rows = []
            for row in results:
                rows.append(dict(row))

            metadata = {
                "total_rows": results.total_rows,
                "num_dml_affected_rows": query_job.num_dml_affected_rows,
                "total_bytes_processed": query_job.total_bytes_processed,
                "total_bytes_billed": query_job.total_bytes_billed,
                "cache_hit": query_job.cache_hit,
            }

            logger.info(
                f"BigQuery query completed: {len(rows)} rows, "
                f"{metadata['total_bytes_processed']} bytes processed"
            )

            return SkillResult.success_result(
                data={
                    "rows": rows,
                    "row_count": len(rows),
                    "schema": [
                        {"name": field.name, "type": field.field_type}
                        for field in results.schema
                    ],
                },
                skill_name=self.name,
                metadata=metadata,
            )

        except Exception as e:
            logger.error(f"BigQuery query failed: {e}")
            return SkillResult.error_result(
                error=str(e),
                skill_name=self.name,
            )

    async def cleanup(self) -> None:
        """리소스 정리"""
        if self.client:
            self.client.close()
            self.client = None
        self.is_available = False
        logger.info("BigQuery skill cleaned up")
