#!/usr/bin/env python3
"""MCP 기능 테스트 예제"""

import asyncio
import logging
from datetime import datetime

from neos.tools.tool_selector import tool_selector, ToolContext
from neos.tools.mcp_integration import mcp_manager

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def test_mcp_tools():
    """MCP 도구 테스트"""
    print("🔧 MCP 도구 테스트 시작...")

    # 1. MCP 매니저 초기화
    print("\n1. MCP 매니저 초기화...")
    init_results = await mcp_manager.initialize()
    print(f"초기화 결과: {init_results}")

    # 2. 사용 가능한 도구 확인
    print("\n2. 사용 가능한 도구 확인...")
    available_tools = mcp_manager.get_available_tools()
    print(f"사용 가능한 MCP 도구: {[tool.name for tool in available_tools]}")

    # 3. 웹 검색 도구 테스트
    if mcp_manager.is_tool_available("web_search_mcp"):
        print("\n3. 웹 검색 MCP 도구 테스트...")
        search_params = {
            "query": "OpenAI GPT-4 latest news",
            "max_results": 5
        }
        result = await mcp_manager.execute_tool("web_search_mcp", search_params)
        print(f"검색 결과: {result.success}, 데이터 길이: {len(result.data) if result.data else 0}")
        if result.success:
            print(f"실행 시간: {result.execution_time_ms}ms")

    # 4. 파일 처리 도구 테스트
    if mcp_manager.is_tool_available("file_processing_mcp"):
        print("\n4. 파일 처리 MCP 도구 테스트...")
        file_params = {
            "operation": "read",
            "file_path": "/example/test.txt"
        }
        result = await mcp_manager.execute_tool("file_processing_mcp", file_params)
        print(f"파일 처리 결과: {result.success}")
        if result.success:
            print(f"처리 결과: {result.data}")

    await mcp_manager.cleanup()


async def test_tool_selector():
    """도구 선택기 테스트"""
    print("\n🎯 도구 선택기 테스트 시작...")

    # 1. 도구 선택기 초기화
    print("\n1. 도구 선택기 초기화...")
    success = await tool_selector.initialize()
    print(f"초기화 성공: {success}")

    # 2. 상태 확인
    print("\n2. 도구 선택기 상태 확인...")
    health = await tool_selector.health_check()
    print(f"상태: {health}")

    # 3. 웹 검색 도구 선택 및 실행
    print("\n3. 웹 검색 도구 선택 및 실행...")
    context = ToolContext(
        query="Python machine learning tutorials",
        user_id="test_user",
        session_id="test_session",
        intent="information_seeking",
        urgency="normal",
        quality_requirement="standard",
        mcp_preference=True,
        fallback_allowed=True
    )

    search_params = {
        "query": "Python machine learning tutorials",
        "max_results": 10
    }

    result, selected_tool = await tool_selector.select_and_execute_tool(
        "web_search",
        search_params,
        context
    )

    print(f"선택된 도구: {selected_tool}")
    print(f"실행 결과: {result.success}")
    if result.success:
        print(f"데이터 길이: {len(result.data) if isinstance(result.data, list) else 'N/A'}")
        print(f"실행 시간: {result.execution_time_ms}ms")
        print(f"메타데이터: {result.metadata}")

    # 4. 다양한 조건으로 테스트
    print("\n4. 다양한 조건으로 도구 선택 테스트...")

    test_scenarios = [
        {
            "name": "긴급 요청 (MCP 사용 제한)",
            "context": ToolContext(
                query="urgent data analysis",
                user_id="test_user",
                session_id="test_session",
                urgency="high",
                mcp_preference=False,
                fallback_allowed=True
            ),
            "category": "data_analysis"
        },
        {
            "name": "고품질 요구 (MCP 선호)",
            "context": ToolContext(
                query="detailed market analysis",
                user_id="test_user",
                session_id="test_session",
                quality_requirement="high",
                mcp_preference=True,
                fallback_allowed=True
            ),
            "category": "data_analysis"
        },
        {
            "name": "리소스 제약 (대체 도구만)",
            "context": ToolContext(
                query="simple file processing",
                user_id="test_user",
                session_id="test_session",
                resource_constraints={"limited_resources": True},
                mcp_preference=False,
                fallback_allowed=True
            ),
            "category": "file_processing"
        }
    ]

    for scenario in test_scenarios:
        print(f"\n  테스트: {scenario['name']}")
        test_params = {"query": scenario["context"].query}

        result, selected_tool = await tool_selector.select_and_execute_tool(
            scenario["category"],
            test_params,
            scenario["context"]
        )

        print(f"    선택된 도구: {selected_tool}")
        print(f"    실행 결과: {result.success}")
        if result.metadata:
            print(f"    도구 타입: {result.metadata.get('source', 'unknown')}")


async def test_workflow_integration():
    """워크플로우 통합 테스트"""
    print("\n🔄 워크플로우 통합 테스트...")

    # 실제 워크플로우와의 통합 테스트는 별도로 진행
    # 여기서는 기본적인 통합 확인만 수행

    print("워크플로우 통합은 별도 테스트에서 확인됩니다.")
    print("neos.workflow.graph.MultiAgentWorkflow에서 tool_selector가 사용됩니다.")


async def main():
    """메인 테스트 함수"""
    print("=" * 60)
    print("🚀 NEOS MCP 기능 확장 테스트")
    print("=" * 60)

    try:
        # MCP 도구 테스트
        await test_mcp_tools()

        print("\n" + "=" * 60)

        # 도구 선택기 테스트
        await test_tool_selector()

        print("\n" + "=" * 60)

        # 워크플로우 통합 테스트
        await test_workflow_integration()

        print("\n" + "=" * 60)
        print("✅ 모든 테스트 완료!")

    except Exception as e:
        print(f"\n❌ 테스트 중 오류 발생: {e}")
        logger.exception("테스트 실행 중 오류")

    finally:
        # 정리
        await mcp_manager.cleanup()


if __name__ == "__main__":
    asyncio.run(main())