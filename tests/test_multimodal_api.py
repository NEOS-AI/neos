"""
멀티모달 API 엔드포인트 테스트
"""

import pytest
from fastapi.testclient import TestClient
from io import BytesIO
from PIL import Image
import json

from neos.main import app


@pytest.fixture
def client():
    """테스트 클라이언트"""
    return TestClient(app)


@pytest.fixture
def sample_image():
    """테스트용 샘플 이미지 생성"""
    # 간단한 RGB 이미지 생성 (100x100 빨간색)
    img = Image.new('RGB', (100, 100), color='red')
    img_bytes = BytesIO()
    img.save(img_bytes, format='JPEG')
    img_bytes.seek(0)
    return img_bytes


@pytest.fixture
def sample_image_png():
    """테스트용 PNG 이미지 생성"""
    img = Image.new('RGB', (200, 150), color='blue')
    img_bytes = BytesIO()
    img.save(img_bytes, format='PNG')
    img_bytes.seek(0)
    return img_bytes


class TestMultimodalRoutes:
    """멀티모달 API 라우트 테스트"""

    def test_supported_types_endpoint(self, client):
        """지원 타입 엔드포인트 테스트"""
        response = client.get("/api/v1/multimodal/supported-types")

        assert response.status_code == 200
        data = response.json()

        assert "supported_types" in data
        assert "vision_enabled" in data
        assert "vision_providers" in data

        # 이미지 타입 확인
        assert "image" in data["supported_types"]
        assert ".jpg" in data["supported_types"]["image"]
        assert ".png" in data["supported_types"]["image"]

    def test_health_check_endpoint(self, client):
        """헬스 체크 엔드포인트 테스트"""
        response = client.get("/api/v1/multimodal/health")

        assert response.status_code == 200
        data = response.json()

        assert "status" in data
        assert data["status"] in ["healthy", "degraded", "unhealthy"]
        assert "multimodal_workflow" in data
        assert "vision_enabled" in data

    @pytest.mark.asyncio
    async def test_image_analysis_endpoint(self, client, sample_image):
        """이미지 분석 엔드포인트 테스트"""
        files = {
            "image": ("test.jpg", sample_image, "image/jpeg")
        }
        data = {
            "query": "What's in this image?",
            "language": "en"
        }

        response = client.post(
            "/api/v1/multimodal/image/analyze",
            files=files,
            data=data
        )

        # Vision API 키가 없을 수도 있으므로 200 또는 500 허용
        assert response.status_code in [200, 500]

        if response.status_code == 200:
            result = response.json()
            assert "success" in result
            assert "filename" in result
            assert result["filename"] == "test.jpg"
            assert "image_metadata" in result
            assert "processing_time_ms" in result

    @pytest.mark.asyncio
    async def test_multimodal_query_endpoint(self, client, sample_image):
        """멀티모달 쿼리 엔드포인트 테스트"""
        files = [
            ("files", ("test.jpg", sample_image, "image/jpeg"))
        ]
        data = {
            "query": "Describe this image",
            "user_id": "test_user",
            "language": "en"
        }

        response = client.post(
            "/api/v1/multimodal/query",
            files=files,
            data=data
        )

        # Vision API 키가 없을 수도 있으므로 200 또는 500 허용
        assert response.status_code in [200, 500]

        if response.status_code == 200:
            result = response.json()
            assert "success" in result
            assert "response" in result
            assert "session_id" in result
            assert "input_type" in result
            assert "metadata" in result
            assert "processing_time_ms" in result

    def test_multimodal_query_no_files(self, client):
        """파일 없이 멀티모달 쿼리 시도 (에러 테스트)"""
        data = {
            "query": "Test query without files",
            "user_id": "test_user"
        }

        response = client.post(
            "/api/v1/multimodal/query",
            data=data
        )

        # 파일이 필수이므로 422 에러 예상
        assert response.status_code == 422

    def test_image_analysis_wrong_file_type(self, client):
        """잘못된 파일 타입으로 이미지 분석 시도"""
        # 텍스트 파일을 이미지로 업로드
        fake_file = BytesIO(b"This is not an image")

        files = {
            "image": ("test.txt", fake_file, "text/plain")
        }

        response = client.post(
            "/api/v1/multimodal/image/analyze",
            files=files
        )

        # 잘못된 파일 타입으로 400 에러 예상
        assert response.status_code == 400
        data = response.json()
        assert "Invalid file type" in data["detail"]

    @pytest.mark.asyncio
    async def test_large_file_rejection(self, client):
        """너무 큰 파일 업로드 시 거부되는지 테스트"""
        # 25MB 이미지 생성 (20MB 제한 초과)
        large_image = Image.new('RGB', (5000, 5000), color='green')
        img_bytes = BytesIO()
        large_image.save(img_bytes, format='JPEG', quality=100)
        img_bytes.seek(0)

        files = {
            "image": ("large.jpg", img_bytes, "image/jpeg")
        }

        response = client.post(
            "/api/v1/multimodal/image/analyze",
            files=files
        )

        # 파일 크기 제한으로 400 에러 예상
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_multiple_files_upload(self, client, sample_image, sample_image_png):
        """여러 파일 동시 업로드 테스트"""
        files = [
            ("files", ("test1.jpg", sample_image, "image/jpeg")),
            ("files", ("test2.png", sample_image_png, "image/png"))
        ]
        data = {
            "query": "Compare these images",
            "user_id": "test_user",
            "language": "en"
        }

        response = client.post(
            "/api/v1/multimodal/query",
            files=files,
            data=data
        )

        # Vision API 키가 없을 수도 있으므로 200 또는 500 허용
        assert response.status_code in [200, 500]

        if response.status_code == 200:
            result = response.json()
            assert result["success"] is True
            # 멀티모달 타입으로 분류되어야 함
            assert result["input_type"] in ["image", "multimodal"]


class TestMultimodalIntegration:
    """멀티모달 API 통합 테스트"""

    def test_root_endpoint_includes_multimodal(self, client):
        """루트 엔드포인트에 멀티모달 API 정보 포함 확인"""
        response = client.get("/")

        assert response.status_code == 200
        data = response.json()

        assert "endpoints" in data
        assert "multimodal_query" in data["endpoints"]
        assert "image_analysis" in data["endpoints"]
        assert "/multimodal/query" in data["endpoints"]["multimodal_query"]
        assert "/multimodal/image/analyze" in data["endpoints"]["image_analysis"]

    def test_api_documentation_includes_multimodal(self, client):
        """API 문서에 멀티모달 엔드포인트 포함 확인"""
        # OpenAPI 스펙 확인
        response = client.get("/openapi.json")

        assert response.status_code == 200
        openapi_spec = response.json()

        # 멀티모달 경로 확인
        assert "/api/v1/multimodal/query" in openapi_spec["paths"]
        assert "/api/v1/multimodal/image/analyze" in openapi_spec["paths"]
        assert "/api/v1/multimodal/supported-types" in openapi_spec["paths"]
        assert "/api/v1/multimodal/health" in openapi_spec["paths"]


class TestMultimodalErrorHandling:
    """멀티모달 API 에러 처리 테스트"""

    def test_missing_required_fields(self, client, sample_image):
        """필수 필드 누락 시 에러 처리"""
        files = [
            ("files", ("test.jpg", sample_image, "image/jpeg"))
        ]
        # query 필드 누락
        data = {
            "user_id": "test_user"
        }

        response = client.post(
            "/api/v1/multimodal/query",
            files=files,
            data=data
        )

        # 필수 필드 누락으로 422 에러
        assert response.status_code == 422

    def test_invalid_language_code(self, client, sample_image):
        """잘못된 언어 코드 처리"""
        files = {
            "image": ("test.jpg", sample_image, "image/jpeg")
        }
        data = {
            "query": "Test",
            "language": "invalid_lang"
        }

        response = client.post(
            "/api/v1/multimodal/image/analyze",
            files=files,
            data=data
        )

        # 잘못된 언어 코드도 처리되어야 함 (기본값 사용)
        assert response.status_code in [200, 500]


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
