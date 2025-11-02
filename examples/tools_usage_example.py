"""
Tools Module Usage Examples

리팩토링된 neos.tools 모듈 사용 예제
"""

import asyncio

from neos.tools import (
    MCPTool,
    MCPToolResult,
    MCPToolType,
    ToolContext,
    mcp_manager,
    tool_selector,
)


async def example_1_basic_mcp_manager():
    """예제 1: MCPManager 기본 사용법"""
    print("=" * 80)
    print("예제 1: MCPManager 기본 사용법")
    print("=" * 80)

    # 초기화
    results = await mcp_manager.initialize()
    print(f"\n✓ 초기화 완료: {results}")

    # 사용 가능한 도구 확인
    available_tools = mcp_manager.get_available_tools()
    print(f"\n✓ 사용 가능한 도구: {len(available_tools)}개")
    for tool in available_tools:
        print(f"   - {tool.name} ({tool.tool_type.value})")

    # 도구 실행
    if mcp_manager.is_tool_available("web_search_mcp"):
        print("\n✓ 웹 검색 도구 실행...")
        result = await mcp_manager.execute_tool(
            "web_search_mcp",
            {"query": "Python asyncio tutorial", "max_results": 3},
        )

        print(f"   성공: {result.success}")
        print(f"   실행 시간: {result.execution_time_ms}ms")
        if result.success and result.data:
            print(f"   결과 개수: {len(result.data)}")


async def example_2_tool_selector():
    """예제 2: ToolSelector 사용법"""
    print("\n" + "=" * 80)
    print("예제 2: ToolSelector - 상황에 따른 도구 선택")
    print("=" * 80)

    # ToolSelector 초기화
    await tool_selector.initialize()

    # 컨텍스트 생성
    context = ToolContext(
        query="Find latest Python news",
        user_id="example_user",
        session_id="example_session",
        intent="web_search",
        urgency="normal",
        quality_requirement="high",
        mcp_preference=True,
        fallback_allowed=True,
    )

    # 도구 선택 및 실행
    result, selected_tool = await tool_selector.select_and_execute_tool(
        tool_category="web_search",
        params={"query": "Python 3.12 features", "max_results": 5},
        context=context,
    )

    print(f"\n✓ 선택된 도구: {selected_tool}")
    print(f"   성공: {result.success}")
    print(f"   실행 시간: {result.execution_time_ms}ms")


async def example_3_custom_tool():
    """예제 3: 커스텀 MCP 도구 작성 및 등록"""
    print("\n" + "=" * 80)
    print("예제 3: 커스텀 MCP 도구 작성")
    print("=" * 80)

    # 커스텀 도구 정의
    class CalculatorMCPTool(MCPTool):
        """간단한 계산기 MCP 도구"""

        def __init__(self):
            super().__init__(
                name="calculator_mcp",
                tool_type=MCPToolType.API_INTEGRATION,
                description="Simple calculator tool",
                capabilities=["add", "subtract", "multiply", "divide"],
            )

        async def initialize(self) -> bool:
            self.is_available = True
            return True

        async def execute(self, params: dict) -> MCPToolResult:
            operation = params.get("operation", "")
            a = params.get("a", 0)
            b = params.get("b", 0)

            if operation == "add":
                result = a + b
            elif operation == "subtract":
                result = a - b
            elif operation == "multiply":
                result = a * b
            elif operation == "divide":
                if b == 0:
                    return MCPToolResult.from_error(
                        error="Division by zero",
                        tool_name=self.name,
                    )
                result = a / b
            else:
                return MCPToolResult.from_error(
                    error=f"Unknown operation: {operation}",
                    tool_name=self.name,
                )

            return MCPToolResult.from_success(
                data={"result": result, "operation": operation},
                tool_name=self.name,
                metadata={"a": a, "b": b},
            )

        async def cleanup(self) -> None:
            pass

    # 도구 등록
    calculator = CalculatorMCPTool()
    await calculator.initialize()
    mcp_manager.register_tool(calculator)

    print(f"\n✓ 커스텀 도구 등록: {calculator.name}")

    # 실행
    result = await mcp_manager.execute_tool(
        "calculator_mcp",
        {"operation": "multiply", "a": 7, "b": 6},
    )

    print(f"   성공: {result.success}")
    if result.success:
        print(f"   결과: {result.data}")


async def example_4_file_operations():
    """예제 4: 파일 처리 도구 사용"""
    print("\n" + "=" * 80)
    print("예제 4: 파일 처리 도구")
    print("=" * 80)

    if not mcp_manager.is_tool_available("file_processing_mcp"):
        print("   파일 처리 도구를 사용할 수 없습니다.")
        return

    # 파일 목록 조회
    result = await mcp_manager.execute_tool(
        "file_processing_mcp",
        {
            "operation": "list",
            "file_path": ".",  # 현재 디렉토리
        },
    )

    print(f"\n✓ 파일 목록 조회: {result.success}")
    if result.success and result.data:
        files = result.data.get("files", [])
        print(f"   파일 개수: {len(files)}")
        for file_info in files[:5]:  # 처음 5개만 출력
            print(f"   - {file_info['name']} ({file_info['type']})")


async def example_5_git_operations():
    """예제 5: Git 작업"""
    print("\n" + "=" * 80)
    print("예제 5: Git 작업")
    print("=" * 80)

    if not mcp_manager.is_tool_available("git_mcp"):
        print("   Git 도구를 사용할 수 없습니다.")
        return

    # 현재 브랜치 확인
    result = await mcp_manager.execute_tool(
        "git_mcp",
        {"operation": "branch"},
    )

    print(f"\n✓ Git 브랜치 조회: {result.success}")
    if result.success and result.data:
        print(f"   현재 브랜치: {result.data.get('current_branch')}")

    # Git 상태 확인
    result = await mcp_manager.execute_tool(
        "git_mcp",
        {"operation": "status"},
    )

    print(f"\n✓ Git 상태 조회: {result.success}")
    if result.success and result.data:
        files = result.data.get("files", [])
        if files:
            print(f"   변경된 파일: {len(files)}개")
            for file_info in files[:5]:
                print(f"   - {file_info['status']} {file_info['file']}")
        else:
            print("   변경 사항 없음 (clean)")


async def example_6_tool_summary():
    """예제 6: 도구 요약 정보"""
    print("\n" + "=" * 80)
    print("예제 6: 도구 요약 정보")
    print("=" * 80)

    # MCPManager 요약
    summary = mcp_manager.get_tool_summary()
    print(f"\n✓ 전체 도구: {summary['total_tools']}개")
    print(f"   사용 가능: {summary['available_tools']}개")
    print(f"   초기화 완료: {summary['initialized']}")

    print("\n✓ 도구 목록:")
    for tool_info in summary["tools"]:
        print(f"   - {tool_info['name']}:")
        print(f"     타입: {tool_info['type']}")
        print(f"     설명: {tool_info['description']}")
        print(f"     기능: {', '.join(tool_info['capabilities'])}")

    # ToolSelector 요약
    ts_summary = tool_selector.get_available_tools_summary()
    print(f"\n✓ ToolSelector 전략: {len(ts_summary['strategies'])}개")
    for strategy in ts_summary["strategies"]:
        print(f"   - {strategy}")


async def example_7_health_check():
    """예제 7: 상태 확인"""
    print("\n" + "=" * 80)
    print("예제 7: 시스템 상태 확인")
    print("=" * 80)

    # ToolSelector health check
    health = await tool_selector.health_check()

    print(f"\n✓ ToolSelector 상태: {health['tool_selector']}")
    print(f"   MCP Manager 상태: {health['mcp_manager']}")
    print(f"   사용 가능한 MCP 도구: {health['available_mcp_tools']}개")
    print(f"   도구 전략: {health['tool_strategies']}개")


async def main():
    """모든 예제 실행"""
    print("\n" + "=" * 80)
    print("NEOS Tools Module - 리팩토링 버전 사용 예제")
    print("=" * 80)

    try:
        # 예제 실행
        await example_1_basic_mcp_manager()
        await example_2_tool_selector()
        await example_3_custom_tool()
        await example_4_file_operations()
        await example_5_git_operations()
        await example_6_tool_summary()
        await example_7_health_check()

        # 정리
        print("\n" + "=" * 80)
        print("정리 중...")
        print("=" * 80)
        await mcp_manager.cleanup()
        print("✓ 완료!")

    except Exception as e:
        print(f"\n❌ 에러 발생: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
