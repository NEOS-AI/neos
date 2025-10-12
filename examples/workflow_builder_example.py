"""커스텀 워크플로우 빌더 사용 예제"""

import asyncio
from neos.workflow.builder import CustomWorkflowBuilder, WorkflowExecutor
from neos.tools.mcp_server_manager import mcp_server_manager


async def example_1_register_mcp_servers():
    """예제 1: MCP 서버 등록"""
    print("\n=== 예제 1: MCP 서버 등록 ===\n")

    # 웹 검색 MCP 서버 등록
    try:
        server_id = await mcp_server_manager.register_server(
            name="example_web_search",
            url="https://api.tavily.com",
            server_type="web_search",
            description="예제용 웹 검색 서버",
            capabilities=["real_time_search", "multi_source"]
        )
        print(f"✅ MCP 서버 등록 완료: ID={server_id}")
    except ValueError as e:
        print(f"⚠️  서버가 이미 존재합니다: {e}")

    # 등록된 서버 목록 조회
    servers = await mcp_server_manager.list_servers()
    print(f"\n등록된 MCP 서버 수: {len(servers)}")
    for server in servers:
        print(f"  - {server['name']} ({server['server_type']})")


async def example_2_create_simple_workflow():
    """예제 2: 간단한 워크플로우 생성"""
    print("\n=== 예제 2: 간단한 워크플로우 생성 ===\n")

    # MCP 서버 확인
    server = await mcp_server_manager.get_server_by_name("example_web_search")
    if not server:
        print("❌ MCP 서버를 먼저 등록해주세요 (예제 1 실행)")
        return None

    # 워크플로우 빌더 생성
    builder = CustomWorkflowBuilder()

    # MCP 서버 추가
    builder.add_mcp_server("example_web_search", server["id"])

    # 노드 추가
    builder.add_node(
        name="web_search",
        node_type="mcp_tool",
        config={"max_results": 5},
        mcp_server_name="example_web_search"
    )

    builder.add_node(
        name="result_processor",
        node_type="processor",
        config={"processor_type": "result_integrator"}
    )

    builder.add_node(
        name="response_generator",
        node_type="processor",
        config={"processor_type": "response_generator"}
    )

    # 엣지 추가 (노드 연결)
    builder.add_edge("web_search", "result_processor")
    builder.add_edge("result_processor", "response_generator")
    builder.add_edge("response_generator", "END")

    # 워크플로우 저장
    workflow_id = await builder.save(
        name="example_simple_search",
        description="웹 검색 후 결과를 정리하는 간단한 워크플로우",
        created_by="example_user",
        tags=["example", "search", "simple"]
    )

    print(f"✅ 워크플로우 생성 완료: ID={workflow_id}")
    print(f"   이름: example_simple_search")
    print(f"   노드 수: 3개")
    print(f"   엣지 수: 3개")

    return workflow_id


async def example_3_create_advanced_workflow():
    """예제 3: 고급 워크플로우 생성 (여러 MCP 도구 사용)"""
    print("\n=== 예제 3: 고급 워크플로우 생성 ===\n")

    # 파일 처리 MCP 서버 등록
    try:
        file_server_id = await mcp_server_manager.register_server(
            name="example_file_processing",
            url="local",
            server_type="file_processing",
            description="예제용 파일 처리 서버",
            capabilities=["file_read", "file_write"]
        )
        print(f"✅ 파일 처리 MCP 서버 등록: ID={file_server_id}")
    except ValueError:
        server = await mcp_server_manager.get_server_by_name("example_file_processing")
        file_server_id = server["id"]
        print(f"⚠️  파일 처리 서버 이미 존재: ID={file_server_id}")

    # 웹 검색 서버 확인
    web_server = await mcp_server_manager.get_server_by_name("example_web_search")
    if not web_server:
        print("❌ 웹 검색 MCP 서버를 먼저 등록해주세요 (예제 1 실행)")
        return None

    # 워크플로우 빌더 생성
    builder = CustomWorkflowBuilder()

    # MCP 서버들 추가
    builder.add_mcp_server("example_web_search", web_server["id"])
    builder.add_mcp_server("example_file_processing", file_server_id)

    # 노드 추가
    # 1. 웹 검색
    builder.add_node(
        name="initial_search",
        node_type="mcp_tool",
        config={"max_results": 10, "search_depth": "advanced"},
        mcp_server_name="example_web_search"
    )

    # 2. 결과 통합
    builder.add_node(
        name="integrate_results",
        node_type="processor",
        config={"processor_type": "result_integrator"}
    )

    # 3. 파일 저장 (선택사항)
    builder.add_node(
        name="save_results",
        node_type="mcp_tool",
        config={
            "operation": "write",
            "file_path": "output/workflow_results.json",
            "mode": "w"
        },
        mcp_server_name="example_file_processing"
    )

    # 4. 최종 응답 생성
    builder.add_node(
        name="generate_final_response",
        node_type="processor",
        config={"processor_type": "response_generator"}
    )

    # 엣지 추가
    builder.add_edge("initial_search", "integrate_results")
    builder.add_edge("integrate_results", "save_results")
    builder.add_edge("save_results", "generate_final_response")
    builder.add_edge("generate_final_response", "END")

    # 워크플로우 저장
    workflow_id = await builder.save(
        name="example_advanced_search",
        description="웹 검색 후 결과를 파일로 저장하고 최종 응답 생성",
        created_by="example_user",
        tags=["example", "advanced", "file_output"]
    )

    print(f"✅ 고급 워크플로우 생성 완료: ID={workflow_id}")
    print(f"   이름: example_advanced_search")
    print(f"   노드 수: 4개")
    print(f"   사용 MCP 서버: 2개")

    return workflow_id


async def example_4_execute_workflow(workflow_id: int):
    """예제 4: 워크플로우 실행"""
    print(f"\n=== 예제 4: 워크플로우 실행 (ID={workflow_id}) ===\n")

    # WorkflowExecutor 생성
    executor = WorkflowExecutor(workflow_id)

    # 워크플로우 로드
    await executor.load_workflow()
    print(f"워크플로우 로드 완료: {executor.workflow_data.name}")
    print(f"설명: {executor.workflow_data.description}")
    print(f"노드 수: {len(executor.workflow_data.nodes)}\n")

    # 워크플로우 실행
    print("워크플로우 실행 중...")
    result = await executor.execute({
        "query": "2024년 AI 산업의 주요 동향",
        "user_id": "example_user",
        "session_id": "example_session_001"
    })

    # 결과 출력
    print("\n" + "="*60)
    if result["success"]:
        print("✅ 실행 성공!")
        print(f"\n응답:\n{result.get('response', 'N/A')}")
        print(f"\n실행 시간: {result['execution_time_ms']}ms")

        if result.get("errors"):
            print(f"\n⚠️  경고: {len(result['errors'])}개의 오류 발생")
            for error in result["errors"]:
                print(f"  - {error}")
    else:
        print("❌ 실행 실패!")
        print(f"오류: {result.get('error', 'Unknown error')}")

    print("="*60)


async def example_5_manage_workflows():
    """예제 5: 워크플로우 관리"""
    print("\n=== 예제 5: 워크플로우 관리 ===\n")

    from neos.workflow.builder import WorkflowManager
    from neos.database.workflow_models import WorkflowStatus

    # 모든 워크플로우 조회
    workflows = await WorkflowManager.list_workflows()
    print(f"총 워크플로우 수: {len(workflows)}\n")

    for wf in workflows:
        print(f"ID: {wf['id']}")
        print(f"  이름: {wf['name']}")
        print(f"  상태: {wf['status']}")
        print(f"  노드 수: {wf['nodes_count']}")
        print(f"  실행 횟수: {wf['execution_count']}")
        print(f"  생성일: {wf['created_at']}")
        print()

    # 특정 워크플로우 활성화
    if workflows:
        first_workflow_id = workflows[0]['id']
        success = await WorkflowManager.update_workflow_status(
            first_workflow_id,
            WorkflowStatus.ACTIVE
        )
        if success:
            print(f"✅ 워크플로우 ID {first_workflow_id} 활성화 완료")


async def main():
    """메인 실행 함수"""
    print("\n" + "="*60)
    print("커스텀 워크플로우 빌더 예제")
    print("="*60)

    # 예제 1: MCP 서버 등록
    await example_1_register_mcp_servers()

    # 예제 2: 간단한 워크플로우 생성
    simple_workflow_id = await example_2_create_simple_workflow()

    # 예제 3: 고급 워크플로우 생성
    advanced_workflow_id = await example_3_create_advanced_workflow()

    # 예제 5: 워크플로우 관리
    await example_5_manage_workflows()

    # 예제 4: 워크플로우 실행 (활성화된 경우에만)
    if simple_workflow_id:
        print("\n⚠️  워크플로우를 활성화한 후 실행할 수 있습니다.")
        print(f"   활성화 명령어: uv run python -m neos.cli workflow-builder activate {simple_workflow_id}")
        print(f"   실행 명령어: uv run python -m neos.cli workflow-builder execute {simple_workflow_id} --query 'test'")

        # 주석 해제하면 바로 실행할 수 있습니다
        # from neos.workflow.builder import WorkflowManager
        # from neos.database.workflow_models import WorkflowStatus
        # await WorkflowManager.update_workflow_status(simple_workflow_id, WorkflowStatus.ACTIVE)
        # await example_4_execute_workflow(simple_workflow_id)

    print("\n" + "="*60)
    print("모든 예제 완료!")
    print("="*60 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
