"""웹 검색 로깅 통합 테스트"""

import asyncio
import uuid
from datetime import datetime

from neos.database.web_search_logger import WebSearchLogger
from neos.database.web_search_types import (
    SearchLogRequest,
    SearchLogComplete,
    SearchResultItem,
    SearchQueryStatus
)
from neos.utils.message_queue import MessageQueueFactory


async def test_web_search_logger():
    print("=" * 70)
    print("웹 검색 로깅 시스템 테스트")
    print("=" * 70)
    print()

    # 1. 메시지 큐 생성
    print("1. 메시지 큐 초기화...")
    message_queue = MessageQueueFactory.create("memory", max_queue_size=1000)
    logger = WebSearchLogger(
        message_queue=message_queue,
        enable_async_logging=True
    )
    await logger.initialize()
    print("   ✓ 로거 초기화 완료")
    print()

    # 2. 검색 시작 로그
    print("2. 검색 시작 로그...")
    log_request = SearchLogRequest(
        query_text="Python 프로그래밍 튜토리얼",
        engine_name="tavily",
        user_id="test_user_123",
        session_id="test_session_456",
        query_language="ko",
        query_intent="informational",
        search_params={"max_results": 10, "search_depth": "advanced"},
        trace_id=str(uuid.uuid4())
    )

    query_id = await logger.log_search_start(log_request)
    print(f"   ✓ 검색 시작 로그 생성 완료")
    print(f"     Query ID: {query_id}")
    print()

    # 메시지 처리를 위한 대기
    await asyncio.sleep(0.5)

    # 3. 검색 완료 로그
    print("3. 검색 완료 로그...")
    log_complete = SearchLogComplete(
        query_id=query_id,
        results=[
            SearchResultItem(
                url="https://docs.python.org/3/tutorial/",
                title="Python Tutorial",
                content="The Python Tutorial — Python 3.12 documentation",
                score=0.95,
                position=1,
                metadata={"content_type": "documentation"}
            ),
            SearchResultItem(
                url="https://realpython.com/",
                title="Real Python",
                content="Real Python Tutorials - Learn Python programming",
                score=0.92,
                position=2,
                metadata={"content_type": "educational"}
            ),
            SearchResultItem(
                url="https://www.learnpython.org/",
                title="Learn Python",
                content="Free interactive Python tutorial",
                score=0.88,
                position=3,
                metadata={"content_type": "tutorial"}
            )
        ],
        execution_time_ms=1234,
        status=SearchQueryStatus.COMPLETED,
        quality_score=0.92,
        metrics={
            "api_call_time_ms": 1000,
            "result_processing_time_ms": 234,
            "total_time_ms": 1234
        }
    )

    await logger.log_search_complete(log_complete)
    print(f"   ✓ 검색 완료 로그 생성 완료")
    print(f"     결과 수: {len(log_complete.results)}")
    print(f"     실행 시간: {log_complete.execution_time_ms}ms")
    print(f"     품질 점수: {log_complete.quality_score}")
    print()

    # 메시지 처리를 위한 대기
    await asyncio.sleep(0.5)

    # 4. 에러 케이스 테스트
    print("4. 검색 실패 로그 테스트...")
    error_request = SearchLogRequest(
        query_text="테스트 에러 쿼리",
        engine_name="tavily",
        user_id="test_user_123",
        session_id="test_session_456"
    )

    error_query_id = await logger.log_search_start(error_request)

    error_complete = SearchLogComplete(
        query_id=error_query_id,
        results=[],
        execution_time_ms=500,
        status=SearchQueryStatus.FAILED,
        error_message="API timeout occurred"
    )

    await logger.log_search_complete(error_complete)
    print(f"   ✓ 검색 실패 로그 생성 완료")
    print(f"     에러 메시지: {error_complete.error_message}")
    print()

    # 메시지 처리를 위한 대기
    await asyncio.sleep(0.5)

    # 5. 로거 종료
    print("5. 로거 종료...")
    await logger.close()
    print("   ✓ 로거 종료 완료")
    print()

    print("=" * 70)
    print("✓ 모든 테스트 완료!")
    print("=" * 70)
    print()
    print("주의: 이 테스트는 메모리 큐만 사용하며, 실제 DB 저장은 하지 않습니다.")
    print("실제 DB 저장을 테스트하려면 DATABASE_URL을 설정하고")
    print("db/web_search_log.sql 스키마를 PostgreSQL에 적용해야 합니다.")
    print()


if __name__ == "__main__":
    asyncio.run(test_web_search_logger())
