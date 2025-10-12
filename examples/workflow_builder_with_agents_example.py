"""커스텀 워크플로우 빌더 - Neos 에이전트 통합 예제"""

import asyncio
from neos.workflow.builder import CustomWorkflowBuilder, WorkflowExecutor
from neos.workflow.agent_registry import agent_registry
from neos.tools.mcp_server_manager import mcp_server_manager


async def example_1_list_available_agents():
    """예제 1: 사용 가능한 에이전트 목록"""
    print("\n=== 예제 1: 사용 가능한 에이전트 목록 ===\n")

    # 모든 에이전트 목록
    all_agents = agent_registry.list_agents()
    print(f"총 {len(all_agents)}개의 에이전트 사용 가능\n")

    # 카테고리별 그룹화
    from collections import defaultdict
    agents_by_category = defaultdict(list)
    for agent in all_agents:
        agents_by_category[agent.category].append(agent)

    for category, agents in sorted(agents_by_category.items()):
        print(f"\n[{category.upper()}] - {len(agents)}개")
        for agent in agents:
            print(f"  • {agent.name}")
            print(f"    {agent.description}")
            print(f"    기능: {', '.join(agent.capabilities[:3])}")


async def example_2_create_agent_workflow():
    """예제 2: 에이전트를 사용하는 워크플로우 생성"""
    print("\n=== 예제 2: 에이전트를 사용하는 워크플로우 생성 ===\n")

    builder = CustomWorkflowBuilder()

    # 검색 에이전트 노드 추가
    builder.add_node(
        name="realtime_search",
        node_type="agent",
        config={"agent_name": "realtime_info_search"}
    )

    # 결과 통합 노드
    builder.add_node(
        name="integrate",
        node_type="processor",
        config={"processor_type": "result_integrator"}
    )

    # 최종 응답 생성 노드
    builder.add_node(
        name="response",
        node_type="processor",
        config={"processor_type": "response_generator"}
    )

    # 엣지 연결
    builder.add_edge("realtime_search", "integrate")
    builder.add_edge("integrate", "response")
    builder.add_edge("response", "END")

    # 워크플로우 저장
    workflow_id = await builder.save(
        name="agent_search_workflow",
        description="Neos 에이전트를 사용한 실시간 검색 워크플로우",
        created_by="example_user",
        tags=["agent", "realtime", "search"]
    )

    print(f"✅ 에이전트 워크플로우 생성 완료: ID={workflow_id}")
    print(f"   - 에이전트: realtime_info_search")
    print(f"   - 노드 수: 3개")

    return workflow_id


async def example_3_create_complex_workflow():
    """예제 3: 여러 에이전트와 MCP 도구를 조합한 복합 워크플로우"""
    print("\n=== 예제 3: 복합 워크플로우 (에이전트 + MCP) ===\n")

    # MCP 서버 등록 (이미 존재하면 스킵)
    try:
        server_id = await mcp_server_manager.register_server(
            name="example_web_search_mcp",
            url="https://api.tavily.com",
            server_type="web_search",
            description="웹 검색 MCP 서버",
            capabilities=["web_search"]
        )
        print(f"✅ MCP 서버 등록: ID={server_id}")
    except ValueError:
        server = await mcp_server_manager.get_server_by_name("example_web_search_mcp")
        server_id = server["id"]
        print(f"⚠️  MCP 서버 이미 존재: ID={server_id}")

    # 워크플로우 빌더 생성
    builder = CustomWorkflowBuilder()

    # MCP 서버 추가
    builder.add_mcp_server("example_web_search_mcp", server_id)

    # 1단계: MCP 웹 검색
    builder.add_node(
        name="mcp_web_search",
        node_type="mcp_tool",
        config={"max_results": 5},
        mcp_server_name="example_web_search_mcp"
    )

    # 2단계: 에이전트 - 데이터 분석
    builder.add_node(
        name="analyze_results",
        node_type="agent",
        config={"agent_name": "data_analysis"}
    )

    # 3단계: 에이전트 - 비교 분석
    builder.add_node(
        name="comparative_analysis",
        node_type="agent",
        config={"agent_name": "comparative_analysis"}
    )

    # 4단계: 결과 통합
    builder.add_node(
        name="integrate_all",
        node_type="processor",
        config={"processor_type": "result_integrator"}
    )

    # 5단계: 최종 응답
    builder.add_node(
        name="final_response",
        node_type="processor",
        config={"processor_type": "response_generator"}
    )

    # 엣지 연결
    builder.add_edge("mcp_web_search", "analyze_results")
    builder.add_edge("analyze_results", "comparative_analysis")
    builder.add_edge("comparative_analysis", "integrate_all")
    builder.add_edge("integrate_all", "final_response")
    builder.add_edge("final_response", "END")

    # 워크플로우 저장
    workflow_id = await builder.save(
        name="complex_agent_mcp_workflow",
        description="MCP 검색 + 에이전트 분석을 결합한 복합 워크플로우",
        created_by="example_user",
        tags=["complex", "agent", "mcp", "analysis"]
    )

    print(f"✅ 복합 워크플로우 생성 완료: ID={workflow_id}")
    print(f"   - MCP 도구: 1개 (웹 검색)")
    print(f"   - 에이전트: 2개 (데이터 분석, 비교 분석)")
    print(f"   - 총 노드 수: 5개")

    return workflow_id


async def example_4_deep_research_workflow():
    """예제 4: 심층 조사 에이전트를 활용한 워크플로우"""
    print("\n=== 예제 4: 심층 조사 워크플로우 ===\n")

    builder = CustomWorkflowBuilder()

    # 1단계: 실시간 정보 수집
    builder.add_node(
        name="initial_research",
        node_type="agent",
        config={"agent_name": "realtime_info_search"}
    )

    # 2단계: 심층 조사
    builder.add_node(
        name="deep_research",
        node_type="agent",
        config={
            "agent_name": "deep_research",
            "context": {
                "max_iterations": 4,  # 4단계 심층 조사
                "quality_threshold": 0.8
            }
        }
    )

    # 3단계: 결과 통합
    builder.add_node(
        name="integrate",
        node_type="processor",
        config={"processor_type": "result_integrator"}
    )

    # 4단계: 최종 보고서 생성
    builder.add_node(
        name="generate_report",
        node_type="processor",
        config={"processor_type": "response_generator"}
    )

    # 엣지 연결
    builder.add_edge("initial_research", "deep_research")
    builder.add_edge("deep_research", "integrate")
    builder.add_edge("integrate", "generate_report")
    builder.add_edge("generate_report", "END")

    # 워크플로우 저장
    workflow_id = await builder.save(
        name="deep_research_workflow",
        description="실시간 정보 수집 + 심층 조사 워크플로우",
        created_by="example_user",
        tags=["research", "deep", "comprehensive"]
    )

    print(f"✅ 심층 조사 워크플로우 생성 완료: ID={workflow_id}")
    print(f"   - 에이전트: realtime_info_search, deep_research")
    print(f"   - 예상 실행 시간: 15-25분")

    return workflow_id


async def example_5_multi_query_workflow():
    """예제 5: 다중 쿼리 검색을 활용한 워크플로우"""
    print("\n=== 예제 5: 다중 쿼리 검색 워크플로우 ===\n")

    builder = CustomWorkflowBuilder()

    # 1단계: 다중 쿼리 검색 (여러 각도에서 검색)
    builder.add_node(
        name="multi_query_search",
        node_type="agent",
        config={
            "agent_name": "multi_query_search",
            "context": {
                "num_queries": 5  # 5개의 다른 쿼리 생성
            }
        }
    )

    # 2단계: 비교 분석
    builder.add_node(
        name="compare_results",
        node_type="agent",
        config={"agent_name": "comparative_analysis"}
    )

    # 3단계: 최종 응답
    builder.add_node(
        name="final_response",
        node_type="processor",
        config={"processor_type": "response_generator"}
    )

    # 엣지 연결
    builder.add_edge("multi_query_search", "compare_results")
    builder.add_edge("compare_results", "final_response")
    builder.add_edge("final_response", "END")

    # 워크플로우 저장
    workflow_id = await builder.save(
        name="multi_query_workflow",
        description="다중 쿼리 검색 + 비교 분석 워크플로우",
        created_by="example_user",
        tags=["multi_query", "comprehensive", "analysis"]
    )

    print(f"✅ 다중 쿼리 워크플로우 생성 완료: ID={workflow_id}")
    print(f"   - 에이전트: multi_query_search, comparative_analysis")

    return workflow_id


async def example_6_execute_agent_workflow(workflow_id: int):
    """예제 6: 에이전트 워크플로우 실행"""
    print(f"\n=== 예제 6: 워크플로우 실행 (ID={workflow_id}) ===\n")

    executor = WorkflowExecutor(workflow_id)

    # 워크플로우 로드
    await executor.load_workflow()
    print(f"워크플로우 로드 완료: {executor.workflow_data.name}")
    print(f"설명: {executor.workflow_data.description}\n")

    # 워크플로우 실행
    print("워크플로우 실행 중...")
    result = await executor.execute({
        "query": "2024년 인공지능 산업의 주요 트렌드",
        "user_id": "example_user",
        "session_id": "example_session_001"
    })

    # 결과 출력
    print("\n" + "="*60)
    if result["success"]:
        print("✅ 실행 성공!")
        print(f"\n응답 (처음 500자):\n{result.get('response', 'N/A')[:500]}...")
        print(f"\n실행 시간: {result['execution_time_ms']}ms")

        if result.get("errors"):
            print(f"\n⚠️  경고: {len(result['errors'])}개의 오류")
    else:
        print("❌ 실행 실패!")
        print(f"오류: {result.get('error', 'Unknown')}")
    print("="*60)


async def main():
    """메인 실행 함수"""
    print("\n" + "="*60)
    print("커스텀 워크플로우 빌더 - Neos 에이전트 통합 예제")
    print("="*60)

    # 예제 1: 사용 가능한 에이전트 목록
    await example_1_list_available_agents()

    # 예제 2: 간단한 에이전트 워크플로우
    workflow_id_1 = await example_2_create_agent_workflow()

    # 예제 3: 복합 워크플로우 (에이전트 + MCP)
    workflow_id_2 = await example_3_create_complex_workflow()

    # 예제 4: 심층 조사 워크플로우
    workflow_id_3 = await example_4_deep_research_workflow()

    # 예제 5: 다중 쿼리 워크플로우
    workflow_id_4 = await example_5_multi_query_workflow()

    print("\n" + "="*60)
    print("생성된 워크플로우:")
    print(f"  1. 에이전트 검색 워크플로우: ID={workflow_id_1}")
    print(f"  2. 복합 워크플로우: ID={workflow_id_2}")
    print(f"  3. 심층 조사 워크플로우: ID={workflow_id_3}")
    print(f"  4. 다중 쿼리 워크플로우: ID={workflow_id_4}")
    print("="*60)

    # 실행 예제 (주석 해제하여 실행)
    # print("\n⚠️  워크플로우를 활성화한 후 실행할 수 있습니다.")
    # print(f"활성화: uv run python -m neos.cli workflow-builder activate {workflow_id_1}")
    # print(f"실행: uv run python -m neos.cli workflow-builder execute {workflow_id_1} --query 'test'")

    # 또는 직접 활성화하고 실행:
    # from neos.workflow.builder import WorkflowManager
    # from neos.database.workflow_models import WorkflowStatus
    # await WorkflowManager.update_workflow_status(workflow_id_1, WorkflowStatus.ACTIVE)
    # await example_6_execute_agent_workflow(workflow_id_1)

    print("\n모든 예제 완료! 🎉\n")


if __name__ == "__main__":
    asyncio.run(main())
