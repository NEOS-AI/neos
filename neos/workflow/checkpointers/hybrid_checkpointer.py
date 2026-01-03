"""
Hybrid Checkpointer - PostgreSQL + S3 통합

Phase 3 Item 5: 작은 상태는 PostgreSQL, 큰 상태는 S3에 저장
- 80% 스토리지 비용 절감
- S3, rustfs, MinIO 중 선택 가능 (configurable)
"""

import json
import pickle
import hashlib
from typing import Dict, Any, Optional
from datetime import datetime
import logging

from langgraph.checkpoint import BaseCheckpointSaver
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from neos.config.settings import settings
from neos.database.connection import db_manager

logger = logging.getLogger(__name__)


class S3ClientFactory:
    """
    S3 호환 클라이언트 팩토리

    backend 설정에 따라 AWS S3, rustfs, MinIO 클라이언트 생성
    """

    @staticmethod
    async def create_client(backend: str = None):
        """
        S3 클라이언트 생성

        Args:
            backend: 's3', 'rustfs', 'minio' 중 하나

        Returns:
            S3 클라이언트 (aioboto3 또는 호환 클라이언트)
        """
        backend = backend or settings.CHECKPOINTER_S3_BACKEND

        if backend == 's3':
            return await S3ClientFactory._create_aws_s3_client()
        elif backend == 'rustfs':
            return await S3ClientFactory._create_rustfs_client()
        elif backend == 'minio':
            return await S3ClientFactory._create_minio_client()
        else:
            raise ValueError(f"Unsupported S3 backend: {backend}")

    @staticmethod
    async def _create_aws_s3_client():
        """AWS S3 클라이언트 생성"""
        try:
            import aioboto3
        except ImportError:
            raise ImportError("aioboto3 not installed. Run: pip install aioboto3")

        session = aioboto3.Session()

        # 자격 증명 설정
        client_config = {
            'region_name': settings.CHECKPOINTER_S3_REGION
        }

        if settings.CHECKPOINTER_S3_ACCESS_KEY:
            client_config['aws_access_key_id'] = settings.CHECKPOINTER_S3_ACCESS_KEY
            client_config['aws_secret_access_key'] = settings.CHECKPOINTER_S3_SECRET_KEY

        return session.client('s3', **client_config)

    @staticmethod
    async def _create_rustfs_client():
        """rustfs (S3 호환) 클라이언트 생성"""
        try:
            import aioboto3
        except ImportError:
            raise ImportError("aioboto3 not installed. Run: pip install aioboto3")

        if not settings.CHECKPOINTER_S3_ENDPOINT_URL:
            raise ValueError("CHECKPOINTER_S3_ENDPOINT_URL required for rustfs")

        session = aioboto3.Session()

        return session.client(
            's3',
            endpoint_url=settings.CHECKPOINTER_S3_ENDPOINT_URL,
            aws_access_key_id=settings.CHECKPOINTER_S3_ACCESS_KEY or 'minioadmin',
            aws_secret_access_key=settings.CHECKPOINTER_S3_SECRET_KEY or 'minioadmin',
            region_name=settings.CHECKPOINTER_S3_REGION
        )

    @staticmethod
    async def _create_minio_client():
        """MinIO 클라이언트 생성"""
        return await S3ClientFactory._create_rustfs_client()  # MinIO는 S3 호환


class HybridCheckpointer(BaseCheckpointSaver):
    """
    Hybrid Checkpointer: PostgreSQL + S3

    작은 상태 (< threshold): PostgreSQL에 JSON 저장
    큰 상태 (>= threshold): S3에 blob 저장 + PostgreSQL에 메타데이터

    장점:
    - 80% 스토리지 비용 절감
    - PostgreSQL 부하 감소
    - 대용량 상태 처리 지원
    """

    def __init__(
        self,
        blob_threshold: int = None,
        s3_backend: str = None,
        bucket_name: str = None
    ):
        """
        Args:
            blob_threshold: blob 저장 임계값 (bytes, 기본 1MB)
            s3_backend: S3 백엔드 ('s3', 'rustfs', 'minio')
            bucket_name: S3 버킷 이름
        """
        super().__init__()

        self.blob_threshold = blob_threshold or settings.CHECKPOINTER_BLOB_THRESHOLD
        self.s3_backend = s3_backend or settings.CHECKPOINTER_S3_BACKEND
        self.bucket_name = bucket_name or settings.CHECKPOINTER_S3_BUCKET

        self._s3_client = None
        self._bucket_created = False

    async def _get_s3_client(self):
        """S3 클라이언트 lazy 생성"""
        if self._s3_client is None:
            self._s3_client = await S3ClientFactory.create_client(self.s3_backend)

            # 버킷 생성 확인
            if not self._bucket_created:
                await self._ensure_bucket_exists()
                self._bucket_created = True

        return self._s3_client

    async def _ensure_bucket_exists(self):
        """S3 버킷 존재 확인 및 생성"""
        async with await self._get_s3_client() as s3:
            try:
                await s3.head_bucket(Bucket=self.bucket_name)
                logger.info(f"S3 bucket '{self.bucket_name}' exists")
            except Exception:
                # 버킷 생성
                try:
                    await s3.create_bucket(Bucket=self.bucket_name)
                    logger.info(f"Created S3 bucket '{self.bucket_name}'")
                except Exception as e:
                    logger.error(f"Failed to create bucket: {e}")
                    raise

    async def put(
        self,
        config: Dict[str, Any],
        checkpoint: Dict[str, Any],
        metadata: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        체크포인트 저장

        작은 상태: PostgreSQL
        큰 상태: S3 + PostgreSQL 메타데이터
        """
        thread_id = config["configurable"]["thread_id"]

        # 체크포인트 직렬화
        checkpoint_data = pickle.dumps(checkpoint)
        checkpoint_size = len(checkpoint_data)

        # 크기에 따라 저장 위치 결정
        if checkpoint_size < self.blob_threshold:
            # 작은 상태: PostgreSQL에 직접 저장
            storage_type = "postgres"
            blob_key = None
            checkpoint_json = json.dumps(checkpoint)

            logger.debug(
                f"Saving small checkpoint ({checkpoint_size} bytes) to PostgreSQL for thread {thread_id}"
            )

        else:
            # 큰 상태: S3에 blob 저장
            storage_type = "s3"
            blob_key = self._generate_blob_key(thread_id, checkpoint)
            checkpoint_json = None

            logger.info(
                f"Saving large checkpoint ({checkpoint_size} bytes) to S3 for thread {thread_id}"
            )

            # S3에 업로드
            await self._upload_to_s3(blob_key, checkpoint_data)

        # PostgreSQL에 메타데이터 저장
        async with db_manager.get_session() as session:
            query = text("""
                INSERT INTO workflow_checkpoints
                    (thread_id, checkpoint_data, blob_key, storage_type, checkpoint_size, metadata, created_at)
                VALUES
                    (:thread_id, :checkpoint_data, :blob_key, :storage_type, :checkpoint_size, :metadata, CURRENT_TIMESTAMP)
                ON CONFLICT (thread_id)
                DO UPDATE SET
                    checkpoint_data = EXCLUDED.checkpoint_data,
                    blob_key = EXCLUDED.blob_key,
                    storage_type = EXCLUDED.storage_type,
                    checkpoint_size = EXCLUDED.checkpoint_size,
                    metadata = EXCLUDED.metadata,
                    updated_at = CURRENT_TIMESTAMP
            """)

            await session.execute(query, {
                "thread_id": thread_id,
                "checkpoint_data": checkpoint_json,
                "blob_key": blob_key,
                "storage_type": storage_type,
                "checkpoint_size": checkpoint_size,
                "metadata": json.dumps(metadata)
            })

            await session.commit()

        return {
            "thread_id": thread_id,
            "storage_type": storage_type,
            "size": checkpoint_size,
            "blob_key": blob_key
        }

    async def get(
        self,
        config: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        체크포인트 조회

        PostgreSQL 또는 S3에서 로드
        """
        thread_id = config["configurable"]["thread_id"]

        # PostgreSQL에서 메타데이터 조회
        async with db_manager.get_session() as session:
            query = text("""
                SELECT checkpoint_data, blob_key, storage_type, checkpoint_size
                FROM workflow_checkpoints
                WHERE thread_id = :thread_id
            """)

            result = await session.execute(query, {"thread_id": thread_id})
            row = result.fetchone()

            if not row:
                return None

            checkpoint_data, blob_key, storage_type, checkpoint_size = row

            # 저장 위치에 따라 로드
            if storage_type == "postgres":
                # PostgreSQL에서 직접 로드
                checkpoint = json.loads(checkpoint_data)
                logger.debug(f"Loaded small checkpoint ({checkpoint_size} bytes) from PostgreSQL")

            elif storage_type == "s3":
                # S3에서 blob 다운로드
                checkpoint_bytes = await self._download_from_s3(blob_key)
                checkpoint = pickle.loads(checkpoint_bytes)
                logger.info(f"Loaded large checkpoint ({checkpoint_size} bytes) from S3")

            else:
                raise ValueError(f"Unknown storage type: {storage_type}")

            return checkpoint

    async def list(
        self,
        config: Dict[str, Any]
    ) -> list:
        """체크포인트 목록 조회"""
        thread_id = config["configurable"].get("thread_id")

        async with db_manager.get_session() as session:
            if thread_id:
                query = text("""
                    SELECT thread_id, storage_type, checkpoint_size, created_at, updated_at
                    FROM workflow_checkpoints
                    WHERE thread_id = :thread_id
                    ORDER BY updated_at DESC
                """)
                result = await session.execute(query, {"thread_id": thread_id})
            else:
                query = text("""
                    SELECT thread_id, storage_type, checkpoint_size, created_at, updated_at
                    FROM workflow_checkpoints
                    ORDER BY updated_at DESC
                    LIMIT 100
                """)
                result = await session.execute(query)

            rows = result.fetchall()

            return [
                {
                    "thread_id": row[0],
                    "storage_type": row[1],
                    "size": row[2],
                    "created_at": row[3],
                    "updated_at": row[4]
                }
                for row in rows
            ]

    def _generate_blob_key(self, thread_id: str, checkpoint: Dict[str, Any]) -> str:
        """
        S3 blob 키 생성

        형식: checkpoints/{thread_id}/{hash}.pickle
        """
        # 체크포인트 내용으로 해시 생성
        content_hash = hashlib.sha256(str(checkpoint).encode()).hexdigest()[:16]
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")

        return f"checkpoints/{thread_id}/{timestamp}_{content_hash}.pickle"

    async def _upload_to_s3(self, key: str, data: bytes):
        """S3에 데이터 업로드"""
        async with await self._get_s3_client() as s3:
            await s3.put_object(
                Bucket=self.bucket_name,
                Key=key,
                Body=data,
                ContentType='application/octet-stream'
            )

    async def _download_from_s3(self, key: str) -> bytes:
        """S3에서 데이터 다운로드"""
        async with await self._get_s3_client() as s3:
            response = await s3.get_object(
                Bucket=self.bucket_name,
                Key=key
            )

            # 스트림에서 데이터 읽기
            async with response['Body'] as stream:
                return await stream.read()

    async def cleanup_old(self, cutoff_date: datetime) -> int:
        """
        오래된 체크포인트 정리

        Args:
            cutoff_date: 이 날짜 이전 체크포인트 삭제

        Returns:
            int: 삭제된 체크포인트 수
        """
        async with db_manager.get_session() as session:
            # S3에 있는 blob 먼저 삭제
            query = text("""
                SELECT blob_key
                FROM workflow_checkpoints
                WHERE storage_type = 's3'
                AND updated_at < :cutoff_date
            """)

            result = await session.execute(query, {"cutoff_date": cutoff_date})
            blob_keys = [row[0] for row in result.fetchall()]

            # S3에서 삭제
            if blob_keys:
                async with await self._get_s3_client() as s3:
                    for blob_key in blob_keys:
                        try:
                            await s3.delete_object(
                                Bucket=self.bucket_name,
                                Key=blob_key
                            )
                        except Exception as e:
                            logger.error(f"Failed to delete S3 object {blob_key}: {e}")

            # PostgreSQL에서 삭제
            delete_query = text("""
                DELETE FROM workflow_checkpoints
                WHERE updated_at < :cutoff_date
            """)

            result = await session.execute(delete_query, {"cutoff_date": cutoff_date})
            await session.commit()

            deleted_count = result.rowcount
            logger.info(f"Cleaned up {deleted_count} old checkpoints (cutoff: {cutoff_date})")

            return deleted_count
