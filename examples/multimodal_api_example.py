"""
멀티모달 API 사용 예제

이미지와 텍스트를 함께 업로드하여 Vision 모델로 분석하는 방법을 보여줍니다.
"""

import requests
import json
from pathlib import Path
from typing import Optional
import sys


# API 기본 설정
API_BASE_URL = "http://localhost:8518"
API_V1_PREFIX = "/api/v1"


def print_section(title: str):
    """섹션 구분자 출력"""
    print("\n" + "=" * 80)
    print(f" {title}")
    print("=" * 80)


def print_response(response: requests.Response):
    """응답을 보기 좋게 출력"""
    print(f"\nStatus Code: {response.status_code}")
    print(f"Response:")
    try:
        data = response.json()
        print(json.dumps(data, indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"Failed to parse JSON: {e}")
        print(response.text)


def test_multimodal_query_with_image(image_path: str, query: str):
    """
    이미지와 텍스트를 함께 업로드하여 멀티모달 쿼리 실행

    Args:
        image_path: 이미지 파일 경로
        query: 사용자 질문
    """
    print_section(f"Multimodal Query Test: {Path(image_path).name}")

    url = f"{API_BASE_URL}{API_V1_PREFIX}/multimodal/query"

    try:
        # 파일 열기
        with open(image_path, "rb") as f:
            files = [
                ("files", (Path(image_path).name, f, "image/jpeg"))
            ]

            data = {
                "query": query,
                "user_id": "example_user",
                "language": "ko"
            }

            print(f"Uploading: {image_path}")
            print(f"Query: {query}")

            response = requests.post(url, files=files, data=data)
            print_response(response)

            # 주요 정보 추출
            if response.status_code == 200:
                result = response.json()
                print("\n" + "-" * 80)
                print("📝 Response Summary:")
                print(f"  - Success: {result.get('success')}")
                print(f"  - Input Type: {result.get('input_type')}")
                print(f"  - Processing Time: {result.get('processing_time_ms', 0):.0f}ms")

                if result.get('vision_analysis'):
                    vision = result['vision_analysis']
                    print(f"\n🔍 Vision Analysis:")
                    if 'description' in vision:
                        print(f"  - Description: {vision['description']}")
                    if 'objects' in vision and vision['objects']:
                        print(f"  - Objects: {', '.join(vision['objects'])}")
                    if 'ocr_text' in vision and vision['ocr_text']:
                        print(f"  - OCR Text: {vision['ocr_text']}")

                if result.get('response'):
                    print(f"\n💬 Final Response:")
                    print(f"  {result['response']}")

                print("-" * 80)

    except FileNotFoundError:
        print(f"❌ Error: File not found: {image_path}")
    except Exception as e:
        print(f"❌ Error: {str(e)}")


def test_image_analysis_only(image_path: str, query: Optional[str] = None):
    """
    이미지만 업로드하여 Vision 분석 수행 (빠른 분석)

    Args:
        image_path: 이미지 파일 경로
        query: 선택적 질문
    """
    print_section(f"Image Analysis Test: {Path(image_path).name}")

    url = f"{API_BASE_URL}{API_V1_PREFIX}/multimodal/image/analyze"

    try:
        with open(image_path, "rb") as f:
            files = {
                "image": (Path(image_path).name, f, "image/jpeg")
            }

            data = {
                "language": "ko"
            }

            if query:
                data["query"] = query
                print(f"Query: {query}")

            print(f"Analyzing: {image_path}")

            response = requests.post(url, files=files, data=data)
            print_response(response)

            # 주요 정보 추출
            if response.status_code == 200:
                result = response.json()
                print("\n" + "-" * 80)
                print("📊 Analysis Summary:")
                print(f"  - Filename: {result.get('filename')}")
                print(f"  - Processing Time: {result.get('processing_time_ms', 0):.0f}ms")

                if result.get('description'):
                    print(f"\n📝 Description:")
                    print(f"  {result['description']}")

                if result.get('objects'):
                    print(f"\n🏷️  Detected Objects:")
                    for obj in result['objects']:
                        print(f"    - {obj}")

                if result.get('ocr_text'):
                    print(f"\n📄 OCR Text:")
                    print(f"  {result['ocr_text']}")

                metadata = result.get('image_metadata', {})
                if metadata:
                    print(f"\n🖼️  Image Metadata:")
                    print(f"  - Size: {metadata.get('width')}x{metadata.get('height')}")
                    print(f"  - Format: {metadata.get('format')}")
                    print(f"  - File Size: {metadata.get('file_size', 0) / 1024:.1f} KB")

                if result.get('vision_provider'):
                    print(f"\n🤖 Vision Provider: {result['vision_provider']}")
                    if result.get('confidence'):
                        print(f"   Confidence: {result['confidence']:.2f}")

                print("-" * 80)

    except FileNotFoundError:
        print(f"❌ Error: File not found: {image_path}")
    except Exception as e:
        print(f"❌ Error: {str(e)}")


def test_multiple_files(file_paths: list, query: str):
    """
    여러 파일을 동시에 업로드하여 멀티모달 분석

    Args:
        file_paths: 파일 경로 리스트
        query: 사용자 질문
    """
    print_section(f"Multiple Files Test ({len(file_paths)} files)")

    url = f"{API_BASE_URL}{API_V1_PREFIX}/multimodal/query"

    try:
        files = []
        file_handles = []

        # 여러 파일 열기
        for path in file_paths:
            f = open(path, "rb")
            file_handles.append(f)
            files.append(("files", (Path(path).name, f, "image/jpeg")))
            print(f"  - {Path(path).name}")

        data = {
            "query": query,
            "user_id": "example_user",
            "language": "ko"
        }

        print(f"\nQuery: {query}")

        response = requests.post(url, files=files, data=data)

        # 파일 핸들 닫기
        for f in file_handles:
            f.close()

        print_response(response)

    except FileNotFoundError as e:
        print(f"❌ Error: File not found: {e}")
    except Exception as e:
        print(f"❌ Error: {str(e)}")


def test_supported_types():
    """지원하는 파일 타입 확인"""
    print_section("Supported Types Test")

    url = f"{API_BASE_URL}{API_V1_PREFIX}/multimodal/supported-types"

    try:
        response = requests.get(url)
        print_response(response)

        if response.status_code == 200:
            result = response.json()
            print("\n" + "-" * 80)
            print("✅ Supported File Types:")

            for file_type, extensions in result.get('supported_types', {}).items():
                print(f"\n  {file_type.upper()}:")
                print(f"    {', '.join(extensions)}")

            print(f"\n🔍 Vision Enabled: {result.get('vision_enabled')}")
            if result.get('vision_providers'):
                print(f"   Available Providers: {', '.join(result['vision_providers'])}")

            print("-" * 80)

    except Exception as e:
        print(f"❌ Error: {str(e)}")


def test_health_check():
    """멀티모달 API 헬스 체크"""
    print_section("Health Check Test")

    url = f"{API_BASE_URL}{API_V1_PREFIX}/multimodal/health"

    try:
        response = requests.get(url)
        print_response(response)

        if response.status_code == 200:
            result = response.json()
            print("\n" + "-" * 80)
            print(f"Status: {result.get('status', 'unknown').upper()}")
            print(f"Multimodal Workflow: {result.get('multimodal_workflow')}")
            print(f"Vision Enabled: {result.get('vision_enabled')}")

            vision_models = result.get('vision_models', {})
            if vision_models:
                print("\n🤖 Vision Models:")
                for key, info in vision_models.items():
                    if isinstance(info, dict):
                        print(f"  {key}: {info}")
            print("-" * 80)

    except Exception as e:
        print(f"❌ Error: {str(e)}")


def main():
    """메인 함수"""
    print("\n")
    print("*" * 80)
    print(" Multimodal API Example - Image + Text Query")
    print("*" * 80)
    print("\n📋 This example demonstrates:")
    print("  1. Uploading images with text queries")
    print("  2. Vision model analysis")
    print("  3. Multiple file uploads")
    print("  4. API health checks")
    print("\n⚠️  Make sure:")
    print("  - FastAPI server is running (python -m neos.main)")
    print("  - Vision API keys are set (OPENAI_API_KEY or ANTHROPIC_API_KEY)")
    print("  - Test images are available\n")

    # API 서버 연결 확인
    try:
        response = requests.get(f"{API_BASE_URL}/")
        if response.status_code != 200:
            print("❌ Error: Cannot connect to API server")
            print(f"   Make sure the server is running at {API_BASE_URL}")
            sys.exit(1)
        print(f"✅ Connected to API server: {API_BASE_URL}\n")
    except Exception as e:
        print(f"❌ Error: Cannot connect to API server: {e}")
        print(f"   Make sure the server is running at {API_BASE_URL}")
        sys.exit(1)

    # 1. 지원하는 타입 확인
    test_supported_types()

    # 2. 헬스 체크
    test_health_check()

    # 3. 이미지 + 텍스트 쿼리 예제
    # 테스트 이미지가 있다면 사용
    test_image_path = "test_image.jpg"

    if Path(test_image_path).exists():
        # 멀티모달 쿼리 테스트
        test_multimodal_query_with_image(
            test_image_path,
            "이 이미지에 무엇이 보이나요? 자세히 설명해주세요."
        )

        # 이미지 단독 분석 테스트
        test_image_analysis_only(
            test_image_path,
            "이 사진의 주요 특징을 설명해주세요."
        )
    else:
        print("\n" + "=" * 80)
        print("⚠️  Test image not found: test_image.jpg")
        print("   Create a test image or update the path to test image upload")
        print("=" * 80)

        # 샘플 코드 출력
        print("\n📝 Sample Code for Your Own Images:\n")
        print("""
# 1. 이미지 + 텍스트 쿼리
test_multimodal_query_with_image(
    "your_image.jpg",
    "이 이미지에서 무엇을 볼 수 있나요?"
)

# 2. 빠른 이미지 분석
test_image_analysis_only("your_image.jpg")

# 3. 여러 이미지 동시 분석
test_multiple_files(
    ["image1.jpg", "image2.jpg"],
    "이 이미지들의 공통점은 무엇인가요?"
)
        """)

    print("\n" + "=" * 80)
    print("✅ Example completed!")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    main()
