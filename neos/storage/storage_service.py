"""Storage service for document uploads supporting S3, rustfs, and local storage"""

import hashlib
import os
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import BinaryIO, Dict, Optional
import logging
import aiofiles
import boto3
from botocore.exceptions import ClientError

from neos.config.settings import settings


logger = logging.getLogger(__name__)


class StorageProvider(ABC):
    """추상 스토리지 프로바이더 인터페이스"""

    @abstractmethod
    async def upload(
        self,
        file_obj: BinaryIO,
        key: str,
        metadata: Optional[Dict[str, str]] = None,
        content_type: Optional[str] = None,
    ) -> str:
        """
        파일 업로드

        Args:
            file_obj: 업로드할 파일 객체
            key: 스토리지 키/경로
            metadata: 파일 메타데이터
            content_type: MIME 타입

        Returns:
            업로드된 파일의 URL
        """
        pass

    @abstractmethod
    async def download(self, key: str) -> bytes:
        """
        파일 다운로드

        Args:
            key: 스토리지 키/경로

        Returns:
            파일 바이트
        """
        pass

    @abstractmethod
    async def delete(self, key: str) -> bool:
        """
        파일 삭제

        Args:
            key: 스토리지 키/경로

        Returns:
            삭제 성공 여부
        """
        pass

    @abstractmethod
    async def exists(self, key: str) -> bool:
        """
        파일 존재 확인

        Args:
            key: 스토리지 키/경로

        Returns:
            파일 존재 여부
        """
        pass

    @abstractmethod
    async def get_presigned_url(
        self, key: str, expiration: int = 3600
    ) -> Optional[str]:
        """
        Presigned URL 생성 (다운로드용)

        Args:
            key: 스토리지 키/경로
            expiration: URL 만료 시간 (초)

        Returns:
            Presigned URL
        """
        pass


class S3StorageProvider(StorageProvider):
    """AWS S3 (또는 S3-compatible) 스토리지 프로바이더"""

    def __init__(
        self,
        bucket_name: str,
        region_name: Optional[str] = None,
        endpoint_url: Optional[str] = None,
        aws_access_key_id: Optional[str] = None,
        aws_secret_access_key: Optional[str] = None,
    ):
        """
        S3 스토리지 초기화

        Args:
            bucket_name: S3 버킷 이름
            region_name: AWS 리전
            endpoint_url: S3-compatible 엔드포인트 (rustfs 등)
            aws_access_key_id: AWS Access Key
            aws_secret_access_key: AWS Secret Key
        """
        self.bucket_name = bucket_name
        self.region_name = region_name or "us-east-1"

        # S3 클라이언트 초기화
        self.s3_client = boto3.client(
            "s3",
            region_name=self.region_name,
            endpoint_url=endpoint_url,
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
        )

        logger.info(
            f"S3 Storage initialized: bucket={bucket_name}, endpoint={endpoint_url or 'AWS'}"
        )

    async def upload(
        self,
        file_obj: BinaryIO,
        key: str,
        metadata: Optional[Dict[str, str]] = None,
        content_type: Optional[str] = None,
    ) -> str:
        """S3에 파일 업로드"""
        try:
            extra_args = {}

            if metadata:
                extra_args["Metadata"] = metadata

            if content_type:
                extra_args["ContentType"] = content_type

            # 파일 객체를 처음부터 읽기
            file_obj.seek(0)

            # S3 업로드 (boto3는 동기 API이지만, 빠르므로 asyncio에서 직접 호출)
            self.s3_client.upload_fileobj(
                file_obj, self.bucket_name, key, ExtraArgs=extra_args
            )

            # URL 생성
            url = f"s3://{self.bucket_name}/{key}"
            logger.info(f"File uploaded to S3: {url}")

            return url

        except ClientError as e:
            logger.error(f"S3 upload failed: {e}")
            raise

    async def download(self, key: str) -> bytes:
        """S3에서 파일 다운로드"""
        try:
            response = self.s3_client.get_object(Bucket=self.bucket_name, Key=key)
            file_data = response["Body"].read()
            logger.info(f"File downloaded from S3: {key}")
            return file_data

        except ClientError as e:
            logger.error(f"S3 download failed: {e}")
            raise

    async def delete(self, key: str) -> bool:
        """S3에서 파일 삭제"""
        try:
            self.s3_client.delete_object(Bucket=self.bucket_name, Key=key)
            logger.info(f"File deleted from S3: {key}")
            return True

        except ClientError as e:
            logger.error(f"S3 delete failed: {e}")
            return False

    async def exists(self, key: str) -> bool:
        """S3에서 파일 존재 확인"""
        try:
            self.s3_client.head_object(Bucket=self.bucket_name, Key=key)
            return True
        except ClientError:
            return False

    async def get_presigned_url(
        self, key: str, expiration: int = 3600
    ) -> Optional[str]:
        """Presigned URL 생성"""
        try:
            url = self.s3_client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket_name, "Key": key},
                ExpiresIn=expiration,
            )
            return url
        except ClientError as e:
            logger.error(f"Presigned URL generation failed: {e}")
            return None


class LocalStorageProvider(StorageProvider):
    """로컬 파일 시스템 스토리지 프로바이더"""

    def __init__(self, base_path: str):
        """
        로컬 스토리지 초기화

        Args:
            base_path: 베이스 디렉토리 경로
        """
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)
        logger.info(f"Local Storage initialized: {self.base_path}")

    def _get_full_path(self, key: str) -> Path:
        """키에서 전체 경로 생성"""
        return self.base_path / key

    async def upload(
        self,
        file_obj: BinaryIO,
        key: str,
        metadata: Optional[Dict[str, str]] = None,
        content_type: Optional[str] = None,
    ) -> str:
        """로컬에 파일 저장"""
        try:
            full_path = self._get_full_path(key)
            full_path.parent.mkdir(parents=True, exist_ok=True)

            # 파일 쓰기
            file_obj.seek(0)
            async with aiofiles.open(full_path, "wb") as f:
                await f.write(file_obj.read())

            # 메타데이터 저장 (별도 파일)
            if metadata:
                metadata_path = full_path.with_suffix(full_path.suffix + ".meta")
                async with aiofiles.open(metadata_path, "w") as f:
                    import json

                    await f.write(json.dumps(metadata))

            url = f"file://{full_path}"
            logger.info(f"File saved locally: {url}")

            return url

        except Exception as e:
            logger.error(f"Local upload failed: {e}")
            raise

    async def download(self, key: str) -> bytes:
        """로컬에서 파일 읽기"""
        try:
            full_path = self._get_full_path(key)
            async with aiofiles.open(full_path, "rb") as f:
                file_data = await f.read()
            logger.info(f"File read from local storage: {key}")
            return file_data

        except Exception as e:
            logger.error(f"Local download failed: {e}")
            raise

    async def delete(self, key: str) -> bool:
        """로컬에서 파일 삭제"""
        try:
            full_path = self._get_full_path(key)

            if full_path.exists():
                full_path.unlink()

                # 메타데이터 파일도 삭제
                metadata_path = full_path.with_suffix(full_path.suffix + ".meta")
                if metadata_path.exists():
                    metadata_path.unlink()

                logger.info(f"File deleted from local storage: {key}")
                return True

            return False

        except Exception as e:
            logger.error(f"Local delete failed: {e}")
            return False

    async def exists(self, key: str) -> bool:
        """로컬에서 파일 존재 확인"""
        full_path = self._get_full_path(key)
        return full_path.exists()

    async def get_presigned_url(
        self, key: str, expiration: int = 3600
    ) -> Optional[str]:
        """로컬 스토리지는 presigned URL을 지원하지 않음"""
        full_path = self._get_full_path(key)
        if full_path.exists():
            return f"file://{full_path}"
        return None


class StorageService:
    """스토리지 서비스 팩토리 및 유틸리티"""

    @staticmethod
    def create_provider(
        provider_type: str = "s3", **kwargs
    ) -> StorageProvider:
        """
        스토리지 프로바이더 생성

        Args:
            provider_type: 's3', 'rustfs', 'local'
            **kwargs: 프로바이더별 설정

        Returns:
            StorageProvider 인스턴스
        """
        if provider_type == "s3":
            return S3StorageProvider(
                bucket_name=kwargs.get("bucket_name", settings.S3_BUCKET_NAME),
                region_name=kwargs.get("region_name", settings.AWS_REGION),
                endpoint_url=kwargs.get("endpoint_url", settings.S3_ENDPOINT_URL),
                aws_access_key_id=kwargs.get(
                    "aws_access_key_id", settings.AWS_ACCESS_KEY_ID
                ),
                aws_secret_access_key=kwargs.get(
                    "aws_secret_access_key", settings.AWS_SECRET_ACCESS_KEY
                ),
            )

        elif provider_type == "rustfs":
            # rustfs는 S3-compatible이므로 S3 프로바이더 사용
            return S3StorageProvider(
                bucket_name=kwargs.get("bucket_name", settings.RUSTFS_BUCKET_NAME),
                endpoint_url=kwargs.get("endpoint_url", settings.RUSTFS_ENDPOINT_URL),
                aws_access_key_id=kwargs.get(
                    "aws_access_key_id", settings.RUSTFS_ACCESS_KEY
                ),
                aws_secret_access_key=kwargs.get(
                    "aws_secret_access_key", settings.RUSTFS_SECRET_KEY
                ),
                region_name=kwargs.get("region_name", "us-east-1"),
            )

        elif provider_type == "local":
            return LocalStorageProvider(
                base_path=kwargs.get("base_path", settings.LOCAL_STORAGE_PATH)
            )

        else:
            raise ValueError(f"Unknown storage provider: {provider_type}")

    @staticmethod
    def compute_file_hash(file_obj: BinaryIO) -> str:
        """
        파일 해시 계산 (SHA-256)

        Args:
            file_obj: 파일 객체

        Returns:
            SHA-256 해시 (hex)
        """
        file_obj.seek(0)
        sha256_hash = hashlib.sha256()

        # 청크 단위로 읽어서 해시 계산
        for byte_block in iter(lambda: file_obj.read(4096), b""):
            sha256_hash.update(byte_block)

        file_obj.seek(0)
        return sha256_hash.hexdigest()

    @staticmethod
    def generate_storage_key(
        user_id: str, filename: str, file_hash: str, prefix: str = "documents"
    ) -> str:
        """
        스토리지 키 생성

        Args:
            user_id: 사용자 ID
            filename: 파일명
            file_hash: 파일 해시
            prefix: 키 접두사

        Returns:
            스토리지 키 (예: documents/user123/2024/01/hash_filename.pdf)
        """
        now = datetime.now()
        year = now.strftime("%Y")
        month = now.strftime("%m")

        # 파일 확장자 추출
        file_ext = Path(filename).suffix

        # 키 생성: prefix/user_id/year/month/hash[:8]_filename
        key = f"{prefix}/{user_id}/{year}/{month}/{file_hash[:8]}_{filename}"

        return key
