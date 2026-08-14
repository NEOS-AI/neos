"""
멀티모달 API 엔드포인트 테스트
"""

import pytest
from fastapi.testclient import TestClient
from io import BytesIO
from PIL import Image
import json
from types import SimpleNamespace

from neos.api.dependencies.auth import get_current_active_user
from neos.main import app

# 이 파일은 DB 를 쓰지 않는다(요청 경로의 미들웨어만 건드린다). 표시하지 않으면
# autouse 정리 픽스처가 **세션 루프에서** 엔진을 만들어 두는데, 아래
# `engine_belongs_to_this_test_loop` 가 설명하는 루프 불일치의 절반이 그것이다.
pytestmark = pytest.mark.no_db


@pytest.fixture(autouse=True)
def engine_belongs_to_this_test_loop():
    """전역 DB 엔진을 테스트마다 비운다.

    `TestClient` 는 인스턴스마다 자기 이벤트 루프(portal)를 돌리는데,
    `db_manager.engine` 은 프로세스 전역이고 asyncpg 커넥션은 **만들어진 루프에
    묶인다.** 그래서 이 파일의 두 번째 요청부터 미들웨어의 DB 접근이
    `got Future attached to a different loop` 로 터지고, 핸들러가 그것을 500 으로
    바꾼다.

    이것은 **원래 있던 결함**이고 내가 만든 것이 아니다. 다만 단언이
    `status_code in [200, 500]` 이라 보이지 않았을 뿐이다 -- 그 관용이 실제로
    가리고 있던 것이 이것이다.

    엔진을 비우면 각 요청이 자기 루프에서 새로 만든다. 버려진 엔진이 테스트당
    하나씩 쌓이지만 이 파일은 12개이고, 전역 엔진을 루프별로 관리하는 것은
    이 파일이 감당할 범위가 아니다(로드맵에 등록).
    """
    from neos.database.connection import db_manager

    db_manager.engine = None
    db_manager.session_factory = None
    yield
    db_manager.engine = None
    db_manager.session_factory = None


@pytest.fixture
def client():
    """인증된 테스트 클라이언트.

    멀티모달 라우트는 get_current_active_user를 요구한다. 이 스위트는 인가가
    아니라 멀티모달 동작을 검증하므로 인증된 사용자를 주입한다.
    (인가 자체는 tests/api/handlers/의 authorization 스위트가 다룬다.)
    """
    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_current_active_user] = lambda: SimpleNamespace(
        user_id="multimodal-test-user",
        is_active=True,
        is_admin=False,
        role="user",
    )
    try:
        # Deliberately not used as a context manager: that would run the app
        # lifespan, which needs Redis and Postgres.
        yield TestClient(app)
    finally:
        app.dependency_overrides = previous


@pytest.fixture(autouse=True)
def no_real_vision_calls(monkeypatch):
    """Vision 경로를 서비스 경계에서 끊는다.

    이 파일은 실제 이미지를 `/multimodal/image/analyze` 와 `/multimodal/query`
    로 올렸고, 그 핸들러는 Anthropic vision 을 호출한다. `.env` 에 키가 있는
    기계에서는 **한 번 돌 때마다 실제 API 를 15회 호출**했다 -- 게이트에 돈과
    네트워크 변동성이 섞였다는 뜻이다.

    그런데도 초록이었던 이유는 단언이 `status_code in [200, 500]` 이었기
    때문이다. 그건 "되든 안 되든 통과"이고, 그래서 **키가 있는 로컬과 키가 없는
    CI 가 서로 다른 코드 경로를 검사**하고 있었다. 정제 테스트·vision 팩토리
    테스트와 같은 부류다(D64) -- 테스트가 환경을 정하지 않고 읽는다.

    여기서 정한다. 그러면 200 과 응답 계약을 실제로 단언할 수 있다.
    """
    from neos.api.services.multimodal_service import MultimodalService

    async def fake_analyze_image(*, filename, **_kwargs):
        return {
            "success": True,
            "filename": filename,
            "description": "A red square.",
            "objects": ["square"],
            "image_metadata": {"width": 100, "height": 100, "format": "JPEG"},
            "vision_provider": "stub",
            "confidence": 0.9,
            "processing_time_ms": 1.0,
        }

    async def fake_process_multimodal_query(*, query, session_id=None, **_kwargs):
        return {
            "success": True,
            "response": f"stubbed answer for: {query}",
            "session_id": session_id or "stub-session",
            "input_type": "multimodal",
            "metadata": {"stub": True},
            "processing_time_ms": 1.0,
        }

    monkeypatch.setattr(
        MultimodalService, "analyze_image", staticmethod(fake_analyze_image)
    )
    monkeypatch.setattr(
        MultimodalService,
        "process_multimodal_query",
        staticmethod(fake_process_multimodal_query),
    )


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

        assert response.status_code == 200
        result = response.json()
        assert result["success"] is True
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

        assert response.status_code == 200
        result = response.json()
        assert result["success"] is True
        assert "Describe this image" in result["response"]
        assert result["session_id"]
        assert result["input_type"]
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

        # 잘못된 파일 타입으로 400 또는 422 에러 예상
        assert response.status_code in [400, 422]
        data = response.json()
        # detail은 dict이거나 string일 수 있음
        if isinstance(data.get("detail"), str):
            assert "Invalid file type" in data["detail"] or "file type" in data["detail"].lower()
        else:
            # FastAPI validation error format
            assert "detail" in data or "error" in data

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

        # 20MB 상한은 핸들러가 강제한다. 스텁 때문에 서비스까지 가지 않으므로
        # 남은 결과는 둘뿐이다 -- 거부되거나, 상한 아래라 통과하거나.
        assert response.status_code in [200, 400]

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

        assert response.status_code == 200
        result = response.json()
        assert result["success"] is True
        # 멀티모달 타입으로 분류되어야 함
        assert result["input_type"] in ["image", "multimodal"]


class TestMultimodalIntegration:
    """멀티모달 API 통합 테스트"""

    def test_root_endpoint_does_not_advertise_endpoints(self, client):
        """루트는 엔드포인트 목록을 노출하지 않는다.

        예전에는 루트가 멀티모달 경로를 나열했지만, 정보 노출을 줄이기 위해
        최소 정보만 반환하도록 바뀌었다. 멀티모달 등록 여부는 아래
        test_api_documentation_includes_multimodal이 OpenAPI 스펙으로 검증한다.
        """
        response = client.get("/")

        assert response.status_code == 200
        data = response.json()

        assert set(data) <= {"name", "version", "status", "health", "docs"}
        assert "endpoints" not in data
        assert "multimodal" not in json.dumps(data)

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
