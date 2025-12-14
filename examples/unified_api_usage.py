"""
통합 API 사용 예제

문서 처리와 워크플로우를 통합하는 API 사용 방법을 보여줍니다.
"""

import asyncio
import httpx
import json
from pathlib import Path


BASE_URL = "http://localhost:8000/api/v1/unified"


# ============================================================================
# 예제 1: 텍스트 쿼리만 (문서 없음)
# ============================================================================

async def example_text_only():
    """텍스트 쿼리만 처리"""
    print("\n" + "=" * 60)
    print("예제 1: 텍스트 쿼리만 처리")
    print("=" * 60)

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            f"{BASE_URL}/process",
            json={
                "query": "인공지능의 최신 트렌드는 무엇인가요?",
                "mode": "text_only"
            }
        )

        if response.status_code == 200:
            result = response.json()
            print("\n✅ 성공!")
            print(f"Session ID: {result['session_id']}")
            print(f"Quality Score: {result['quality_score']}")
            print(f"Execution Time: {result['execution_time_ms']}ms")
            print(f"\n응답:\n{result['response'][:500]}...")
        else:
            print(f"❌ 실패: {response.status_code}")
            print(response.text)


# ============================================================================
# 예제 2: 문서 + 쿼리 (Base64 인코딩)
# ============================================================================

async def example_document_with_query():
    """문서와 쿼리를 함께 처리"""
    print("\n" + "=" * 60)
    print("예제 2: 문서 + 쿼리 처리")
    print("=" * 60)

    # 샘플 문서 생성 (간단한 텍스트 파일)
    sample_content = """
# AI Research Report

## Executive Summary
This report provides an overview of recent developments in artificial intelligence,
focusing on large language models and their applications.

## Key Findings
1. LLMs have shown remarkable performance in various tasks
2. Multi-agent systems are emerging as a powerful paradigm
3. Vision-language models are becoming mainstream

## Conclusion
The field of AI continues to evolve rapidly with new breakthroughs every month.
""".encode('utf-8')

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            f"{BASE_URL}/process",
            json={
                "query": "이 문서의 주요 내용을 요약해주세요",
                "documents": [
                    {
                        "filename": "report.txt",
                        "mime_type": "text/plain",
                        "file_size": len(sample_content),
                        "file_content": sample_content.decode('utf-8')
                    }
                ],
                "mode": "document_with_query",
                "enable_vision": False  # 텍스트 파일이므로 Vision 비활성화
            }
        )

        if response.status_code == 200:
            result = response.json()
            print("\n✅ 성공!")
            print(f"Session ID: {result['session_id']}")
            print(f"처리된 문서 수: {len(result.get('documents_processed', []))}")

            if result.get('documents_processed'):
                doc = result['documents_processed'][0]
                print("\n문서 정보:")
                print(f"  - 형식: {doc['extraction_method']}")
                print(f"  - 문자 수: {doc['char_count']}")
                print(f"  - 단어 수: {doc['word_count']}")

            print(f"\n응답:\n{result['response'][:500]}...")
        else:
            print(f"❌ 실패: {response.status_code}")
            print(response.text)


# ============================================================================
# 예제 3: 파일 업로드 방식
# ============================================================================

async def example_file_upload():
    """파일 업로드 방식으로 처리"""
    print("\n" + "=" * 60)
    print("예제 3: 파일 업로드 방식")
    print("=" * 60)

    # 임시 파일 생성
    temp_file = Path("/tmp/sample_document.txt")
    temp_file.write_text("""
# Product Specification

## Overview
This document describes the technical specifications of our new AI product.

## Features
- Natural language understanding
- Multi-turn conversation
- Context awareness
- Real-time processing

## Performance Metrics
- Response time: < 100ms
- Accuracy: > 95%
- Throughput: 1000 requests/sec
""")

    async with httpx.AsyncClient(timeout=60.0) as client:
        with open(temp_file, 'rb') as f:
            response = await client.post(
                f"{BASE_URL}/process/upload",
                files={"files": ("sample_document.txt", f, "text/plain")},
                data={
                    "query": "이 제품의 주요 특징과 성능 지표를 정리해주세요",
                    "enable_vision": "false",
                    "mode": "document_with_query"
                }
            )

        if response.status_code == 200:
            result = response.json()
            print("\n✅ 성공!")
            print(f"Session ID: {result['session_id']}")
            print(f"처리된 문서: {result['documents_processed']}개")
            print(f"Quality Score: {result['quality_score']}")
            print(f"\n응답:\n{result['response'][:500]}...")
        else:
            print(f"❌ 실패: {response.status_code}")
            print(response.text)

    # 임시 파일 삭제
    temp_file.unlink()


# ============================================================================
# 예제 4: 스트리밍 처리 (SSE)
# ============================================================================

async def example_streaming():
    """SSE 스트리밍으로 실시간 진행 상황 확인"""
    print("\n" + "=" * 60)
    print("예제 4: 스트리밍 처리 (실시간)")
    print("=" * 60)

    async with httpx.AsyncClient(timeout=120.0) as client:
        async with client.stream(
            "POST",
            f"{BASE_URL}/process/stream",
            json={
                "query": "양자 컴퓨팅의 미래 전망은?",
                "mode": "text_only"
            }
        ) as response:
            print("\n스트리밍 이벤트:")
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    data_str = line[6:]  # "data: " 제거
                    try:
                        event = json.loads(data_str)
                        event_type = event.get("event")
                        progress = event.get("progress_percent", 0)
                        phase = event.get("phase", "")

                        print(f"  [{event_type}] {phase} - {progress}%")

                        if event.get("content"):
                            print(f"    💬 {event['content']}")

                        if event_type == "completed":
                            print("\n✅ 완료!")
                            if "data" in event and "response" in event["data"]:
                                print(f"\n최종 응답:\n{event['data']['response'][:500]}...")
                            break

                        elif event_type == "error":
                            print(f"\n❌ 에러: {event.get('error')}")
                            break

                    except json.JSONDecodeError:
                        continue


# ============================================================================
# 예제 5: PDF 문서 처리 (Vision 활성화)
# ============================================================================

async def example_pdf_with_vision():
    """PDF 문서 + Vision 분석"""
    print("\n" + "=" * 60)
    print("예제 5: PDF 문서 + Vision 분석")
    print("=" * 60)

    # 실제 PDF 파일이 있다면 사용
    # 여기서는 개념만 보여줍니다
    print("\n💡 사용법:")
    print("""
    # Python 코드
    import httpx

    async with httpx.AsyncClient(timeout=120.0) as client:
        with open("document.pdf", "rb") as f:
            response = await client.post(
                "http://localhost:8000/api/v1/unified/process/upload",
                files={"files": ("document.pdf", f, "application/pdf")},
                data={
                    "query": "이 문서의 이미지들을 분석하고 주요 내용을 요약해주세요",
                    "enable_vision": "true",
                    "max_images_to_analyze": "10"
                }
            )

    # 결과에는 다음이 포함됩니다:
    # - 추출된 텍스트
    # - 추출된 표
    # - 추출된 이미지
    # - Vision 모델의 이미지 분석 결과
    # - 통합된 최종 응답
    """)


# ============================================================================
# Health Check
# ============================================================================

async def check_api_health():
    """API 상태 확인"""
    print("\n" + "=" * 60)
    print("API 상태 확인")
    print("=" * 60)

    async with httpx.AsyncClient() as client:
        response = await client.get(f"{BASE_URL}/health")

        if response.status_code == 200:
            health = response.json()
            print("\n✅ API 정상 작동 중")
            print(f"Service: {health['service']}")
            print("Features:")
            for feature, enabled in health['features'].items():
                status = "✓" if enabled else "✗"
                print(f"  {status} {feature}")
            print("\nSupported Formats:")
            for fmt in health['supported_formats']:
                print(f"  • {fmt}")
        else:
            print(f"❌ API 상태 확인 실패: {response.status_code}")


# ============================================================================
# 메인 실행
# ============================================================================

async def main():
    """모든 예제 실행"""
    print("\n" + "🚀 " * 20)
    print("통합 API 사용 예제")
    print("🚀 " * 20)

    # API 상태 확인
    await check_api_health()

    # 예제 실행
    try:
        await example_text_only()
        await example_document_with_query()
        await example_file_upload()
        await example_streaming()
        example_pdf_with_vision()  # 비동기 아님

    except httpx.ConnectError:
        print("\n❌ API 서버에 연결할 수 없습니다.")
        print("다음 명령으로 서버를 시작하세요:")
        print("  python -m neos.main")

    except Exception as e:
        print(f"\n❌ 에러 발생: {e}")

    print("\n" + "=" * 60)
    print("예제 실행 완료!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
