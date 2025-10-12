"""워크플로우 빌더 CLI 명령어"""

import asyncio
import json
from typing import Optional
import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from rich.syntax import Syntax
from datetime import datetime

from neos.workflow.builder import (
    CustomWorkflowBuilder,
    WorkflowExecutor,
    WorkflowManager
)
from neos.tools.mcp_server_manager import mcp_server_manager
from neos.database.workflow_models import WorkflowStatus
from neos.workflow.agent_registry import agent_registry


console = Console()


@click.group(name='workflow-builder')
def workflow_builder():
    """🏗️  커스텀 워크플로우 빌더 - MCP 도구를 활용한 워크플로우 생성 및 관리"""
    pass


# ==================== MCP 서버 관리 명령어 ====================

@workflow_builder.group(name='mcp')
def mcp_server():
    """MCP 서버 관리"""
    pass


@mcp_server.command(name='register')
@click.option('--name', '-n', required=True, help='MCP 서버 이름')
@click.option('--url', '-u', required=True, help='MCP 서버 URL')
@click.option('--type', '-t', required=True, help='서버 타입 (web_search, file_processing, 등)')
@click.option('--description', '-d', default='', help='서버 설명')
@click.option('--capabilities', '-c', multiple=True, help='서버 기능 목록')
def register_mcp_server(name: str, url: str, type: str, description: str, capabilities: tuple):
    """MCP 서버 등록

    예시:
      uv run python -m neos.cli workflow-builder mcp register \\
        --name "tavily_search" \\
        --url "https://api.tavily.com" \\
        --type "web_search" \\
        --description "Tavily 웹 검색 API" \\
        --capabilities "real_time_search" \\
        --capabilities "multi_source"
    """
    console.print(Panel.fit("🔧 MCP 서버 등록", style="bold blue"))

    try:
        server_id = asyncio.run(
            mcp_server_manager.register_server(
                name=name,
                url=url,
                server_type=type,
                description=description,
                capabilities=list(capabilities)
            )
        )

        console.print("\n✅ MCP 서버가 등록되었습니다!")
        console.print(f"   ID: {server_id}")
        console.print(f"   이름: {name}")
        console.print(f"   URL: {url}")
        console.print(f"   타입: {type}")

    except Exception as e:
        console.print(f"\n❌ 오류: {e}", style="red")


@mcp_server.command(name='list')
@click.option('--type', '-t', help='서버 타입으로 필터링')
@click.option('--active-only', is_flag=True, help='활성화된 서버만 표시')
def list_mcp_servers(type: Optional[str], active_only: bool):
    """MCP 서버 목록 조회

    예시:
      uv run python -m neos.cli workflow-builder mcp list
      uv run python -m neos.cli workflow-builder mcp list --type web_search
      uv run python -m neos.cli workflow-builder mcp list --active-only
    """
    console.print(Panel.fit("📋 MCP 서버 목록", style="bold blue"))

    try:
        servers = asyncio.run(
            mcp_server_manager.list_servers(
                server_type=type,
                is_active=True if active_only else None
            )
        )

        if not servers:
            console.print("\n⚠️  등록된 MCP 서버가 없습니다.")
            return

        table = Table(title=f"총 {len(servers)}개의 MCP 서버")
        table.add_column("ID", style="cyan")
        table.add_column("이름", style="green")
        table.add_column("타입", style="yellow")
        table.add_column("URL", style="blue")
        table.add_column("상태", style="magenta")
        table.add_column("기능", style="white")

        for server in servers:
            status = "✅ 활성" if server["is_active"] else "❌ 비활성"
            capabilities = ", ".join(server["capabilities"][:3])
            if len(server["capabilities"]) > 3:
                capabilities += "..."

            table.add_row(
                str(server["id"]),
                server["name"],
                server["server_type"],
                server["url"][:40] + "..." if len(server["url"]) > 40 else server["url"],
                status,
                capabilities
            )

        console.print()
        console.print(table)

    except Exception as e:
        console.print(f"\n❌ 오류: {e}", style="red")


@mcp_server.command(name='info')
@click.argument('server_id', type=int)
def mcp_server_info(server_id: int):
    """MCP 서버 상세 정보

    예시:
      uv run python -m neos.cli workflow-builder mcp info 1
    """
    console.print(Panel.fit(f"ℹ️  MCP 서버 상세 정보 (ID: {server_id})", style="bold blue"))

    try:
        server = asyncio.run(mcp_server_manager.get_server(server_id))

        if not server:
            console.print(f"\n❌ ID {server_id}인 MCP 서버를 찾을 수 없습니다.", style="red")
            return

        info_table = Table(show_header=False, box=None)
        info_table.add_column("속성", style="cyan bold")
        info_table.add_column("값", style="white")

        info_table.add_row("ID", str(server["id"]))
        info_table.add_row("이름", server["name"])
        info_table.add_row("URL", server["url"])
        info_table.add_row("타입", server["server_type"])
        info_table.add_row("설명", server["description"] or "-")
        info_table.add_row("상태", "✅ 활성" if server["is_active"] else "❌ 비활성")
        info_table.add_row("생성일", server["created_at"])
        info_table.add_row("수정일", server["updated_at"])

        console.print()
        console.print(info_table)

        if server["capabilities"]:
            console.print("\n[bold cyan]기능:[/bold cyan]")
            for cap in server["capabilities"]:
                console.print(f"  • {cap}")

        if server["config"]:
            console.print("\n[bold cyan]설정:[/bold cyan]")
            console.print(Syntax(json.dumps(server["config"], indent=2, ensure_ascii=False), "json"))

    except Exception as e:
        console.print(f"\n❌ 오류: {e}", style="red")


@mcp_server.command(name='delete')
@click.argument('server_id', type=int)
@click.option('--yes', '-y', is_flag=True, help='확인 없이 삭제')
def delete_mcp_server(server_id: int, yes: bool):
    """MCP 서버 삭제

    예시:
      uv run python -m neos.cli workflow-builder mcp delete 1
      uv run python -m neos.cli workflow-builder mcp delete 1 --yes
    """
    if not yes:
        if not Confirm.ask(f"정말 MCP 서버 ID {server_id}를 삭제하시겠습니까?"):
            console.print("취소되었습니다.")
            return

    try:
        success = asyncio.run(mcp_server_manager.delete_server(server_id))

        if success:
            console.print(f"\n✅ MCP 서버 ID {server_id}가 삭제되었습니다.", style="green")
        else:
            console.print("\n❌ MCP 서버를 찾을 수 없습니다.", style="red")

    except Exception as e:
        console.print(f"\n❌ 오류: {e}", style="red")


# ==================== 에이전트 관리 명령어 ====================

@workflow_builder.group(name='agent')
def agent():
    """Neos 에이전트 관리"""
    pass


@agent.command(name='list')
@click.option('--category', '-c', help='카테고리로 필터링 (search, analysis, generation)')
def list_agents(category: Optional[str]):
    """사용 가능한 에이전트 목록 조회

    예시:
      uv run python -m neos.cli workflow-builder agent list
      uv run python -m neos.cli workflow-builder agent list --category search
    """
    console.print(Panel.fit("🤖 사용 가능한 에이전트 목록", style="bold blue"))

    try:
        agents = agent_registry.list_agents(category=category)

        if not agents:
            console.print("\n⚠️  등록된 에이전트가 없습니다.")
            return

        # 카테고리별로 그룹화
        from collections import defaultdict
        agents_by_category = defaultdict(list)
        for agent in agents:
            agents_by_category[agent.category].append(agent)

        for cat, cat_agents in sorted(agents_by_category.items()):
            console.print(f"\n[bold cyan]{cat.upper()} ({len(cat_agents)}개)[/bold cyan]")

            table = Table(show_header=True, box=None)
            table.add_column("이름", style="green")
            table.add_column("설명", style="white")
            table.add_column("주요 기능", style="yellow")

            for agent in cat_agents:
                capabilities = ", ".join(agent.capabilities[:2])
                if len(agent.capabilities) > 2:
                    capabilities += "..."

                table.add_row(
                    agent.name,
                    agent.description[:50] + "..." if len(agent.description) > 50 else agent.description,
                    capabilities
                )

            console.print(table)

        # 요약
        console.print(f"\n[dim]총 {len(agents)}개의 에이전트 사용 가능[/dim]")
        categories = agent_registry.get_categories()
        console.print(f"[dim]카테고리: {', '.join(categories)}[/dim]")

    except Exception as e:
        console.print(f"\n❌ 오류: {e}", style="red")


@agent.command(name='info')
@click.argument('agent_name')
def agent_info(agent_name: str):
    """에이전트 상세 정보

    예시:
      uv run python -m neos.cli workflow-builder agent info knowledge_search
      uv run python -m neos.cli workflow-builder agent info deep_research
    """
    console.print(Panel.fit(f"ℹ️  에이전트 상세 정보: {agent_name}", style="bold blue"))

    try:
        agent_info_obj = agent_registry.get_agent_info(agent_name)

        if not agent_info_obj:
            console.print(f"\n❌ 에이전트 '{agent_name}'를 찾을 수 없습니다.", style="red")

            # 유사한 에이전트 제안
            all_agents = agent_registry.list_agents()
            console.print("\n[dim]사용 가능한 에이전트:[/dim]")
            for agent in all_agents[:5]:
                console.print(f"  • {agent.name}")
            return

        info_table = Table(show_header=False, box=None)
        info_table.add_column("속성", style="cyan bold")
        info_table.add_column("값", style="white")

        info_table.add_row("이름", agent_info_obj.name)
        info_table.add_row("카테고리", agent_info_obj.category)
        info_table.add_row("설명", agent_info_obj.description)
        info_table.add_row("클래스", agent_info_obj.agent_class.__name__)

        console.print()
        console.print(info_table)

        if agent_info_obj.capabilities:
            console.print("\n[bold cyan]기능:[/bold cyan]")
            for cap in agent_info_obj.capabilities:
                console.print(f"  • {cap}")

        # 사용 예제
        console.print("\n[bold cyan]워크플로우에서 사용:[/bold cyan]")
        console.print(f"""
[dim]builder.add_node(
    name="my_node",
    node_type="agent",
    config={{"agent_name": "{agent_name}"}}
)[/dim]
        """)

    except Exception as e:
        console.print(f"\n❌ 오류: {e}", style="red")


# ==================== 워크플로우 관리 명령어 ====================

@workflow_builder.command(name='create')
@click.option('--name', '-n', required=True, help='워크플로우 이름')
@click.option('--description', '-d', required=True, help='워크플로우 설명')
@click.option('--interactive', '-i', is_flag=True, help='대화형 모드로 생성')
def create_workflow(name: str, description: str, interactive: bool):
    """워크플로우 생성

    예시:
      uv run python -m neos.cli workflow-builder create \\
        --name "my_workflow" \\
        --description "웹 검색 후 분석하는 워크플로우" \\
        --interactive
    """
    console.print(Panel.fit("🏗️  새 워크플로우 생성", style="bold blue"))

    try:
        builder = CustomWorkflowBuilder()

        if interactive:
            _interactive_workflow_creation(builder, name, description)
        else:
            console.print("\n⚠️  --interactive 플래그를 사용하여 대화형 모드로 워크플로우를 생성하세요.")
            return

    except Exception as e:
        console.print(f"\n❌ 오류: {e}", style="red")
        import traceback
        console.print(traceback.format_exc(), style="dim")


def _interactive_workflow_creation(builder: CustomWorkflowBuilder, name: str, description: str):
    """대화형 워크플로우 생성"""
    console.print("\n[bold cyan]워크플로우 노드 추가[/bold cyan]")
    console.print("노드를 추가하세요. 완료하려면 빈 이름을 입력하세요.\n")

    node_count = 0

    while True:
        node_name = Prompt.ask(f"노드 {node_count + 1} 이름 (엔터로 완료)", default="")

        if not node_name:
            break

        console.print("\n노드 타입을 선택하세요:")
        console.print("  1. agent - 에이전트")
        console.print("  2. mcp_tool - MCP 도구")
        console.print("  3. processor - 프로세서")

        node_type_choice = Prompt.ask("선택", choices=["1", "2", "3"])
        node_type_map = {"1": "agent", "2": "mcp_tool", "3": "processor"}
        node_type = node_type_map[node_type_choice]

        config = {}
        mcp_server_name = None

        if node_type == "agent":
            # 에이전트 목록 표시
            agents = agent_registry.list_agents()

            if not agents:
                console.print("\n⚠️  등록된 에이전트가 없습니다.")
                continue

            console.print("\n[bold]사용 가능한 에이전트:[/bold]")

            # 카테고리별로 표시
            from collections import defaultdict
            agents_by_category = defaultdict(list)
            for agent in agents:
                agents_by_category[agent.category].append(agent)

            agent_list = []
            idx = 1
            for cat, cat_agents in sorted(agents_by_category.items()):
                console.print(f"\n[cyan]{cat.upper()}:[/cyan]")
                for agent in cat_agents:
                    console.print(f"  {idx}. {agent.name} - {agent.description[:50]}")
                    agent_list.append(agent)
                    idx += 1

            agent_choice = int(Prompt.ask("에이전트 선택", choices=[str(i) for i in range(1, len(agent_list) + 1)]))
            selected_agent = agent_list[agent_choice - 1]
            config["agent_name"] = selected_agent.name

        elif node_type == "mcp_tool":
            # MCP 서버 목록 표시
            servers = asyncio.run(mcp_server_manager.list_servers(is_active=True))

            if not servers:
                console.print("\n⚠️  활성화된 MCP 서버가 없습니다. 먼저 MCP 서버를 등록하세요.")
                continue

            console.print("\n[bold]사용 가능한 MCP 서버:[/bold]")
            for i, server in enumerate(servers, 1):
                console.print(f"  {i}. {server['name']} ({server['server_type']})")

            server_choice = int(Prompt.ask("MCP 서버 선택", choices=[str(i) for i in range(1, len(servers) + 1)]))
            selected_server = servers[server_choice - 1]
            mcp_server_name = selected_server["name"]

            # MCP 서버 ID를 builder에 추가
            builder.add_mcp_server(selected_server["name"], selected_server["id"])

        elif node_type == "processor":
            console.print("\n프로세서 타입을 선택하세요:")
            console.print("  1. result_integrator - 결과 통합")
            console.print("  2. response_generator - 응답 생성")

            processor_choice = Prompt.ask("선택", choices=["1", "2"])
            processor_map = {"1": "result_integrator", "2": "response_generator"}
            config["processor_type"] = processor_map[processor_choice]

        builder.add_node(node_name, node_type, config, mcp_server_name)
        console.print(f"✅ 노드 '{node_name}' 추가됨\n")
        node_count += 1

    if node_count == 0:
        console.print("\n⚠️  최소 1개의 노드가 필요합니다.")
        return

    # 엣지 추가
    console.print("\n[bold cyan]워크플로우 엣지 추가[/bold cyan]")
    console.print("노드 간 연결을 추가하세요. 완료하려면 빈 값을 입력하세요.\n")

    nodes = [node.name for node in builder.nodes]
    console.print(f"[dim]사용 가능한 노드: {', '.join(nodes)}[/dim]\n")

    while True:
        from_node = Prompt.ask("출발 노드 (엔터로 완료)", default="")

        if not from_node:
            break

        if from_node not in nodes:
            console.print(f"⚠️  '{from_node}'는 존재하지 않는 노드입니다.")
            continue

        to_node = Prompt.ask("도착 노드 (END로 종료 노드)", default="END")

        if to_node != "END" and to_node not in nodes:
            console.print(f"⚠️  '{to_node}'는 존재하지 않는 노드입니다.")
            continue

        builder.add_edge(from_node, to_node)
        console.print(f"✅ 엣지 '{from_node}' → '{to_node}' 추가됨\n")

    # 워크플로우 저장
    console.print("\n[bold cyan]워크플로우 저장[/bold cyan]")

    tags_input = Prompt.ask("태그 (쉼표로 구분)", default="")
    tags = [tag.strip() for tag in tags_input.split(",")] if tags_input else []

    created_by = Prompt.ask("생성자 ID", default="cli_user")

    try:
        workflow_id = asyncio.run(
            builder.save(
                name=name,
                description=description,
                created_by=created_by,
                tags=tags
            )
        )

        console.print("\n✅ 워크플로우가 저장되었습니다!")
        console.print(f"   ID: {workflow_id}")
        console.print(f"   이름: {name}")
        console.print(f"   노드: {len(builder.nodes)}개")
        console.print(f"   엣지: {len(builder.edges)}개")

        console.print("\n[dim]워크플로우를 활성화하려면:[/dim]")
        console.print(f"[dim]  uv run python -m neos.cli workflow-builder activate {workflow_id}[/dim]")

    except Exception as e:
        console.print(f"\n❌ 저장 실패: {e}", style="red")


@workflow_builder.command(name='list')
@click.option('--status', '-s', type=click.Choice(['draft', 'active', 'inactive', 'archived']), help='상태로 필터링')
@click.option('--created-by', help='생성자로 필터링')
def list_workflows(status: Optional[str], created_by: Optional[str]):
    """워크플로우 목록 조회

    예시:
      uv run python -m neos.cli workflow-builder list
      uv run python -m neos.cli workflow-builder list --status active
      uv run python -m neos.cli workflow-builder list --created-by cli_user
    """
    console.print(Panel.fit("📋 워크플로우 목록", style="bold blue"))

    try:
        status_enum = WorkflowStatus[status.upper()] if status else None

        workflows = asyncio.run(
            WorkflowManager.list_workflows(
                status=status_enum,
                created_by=created_by
            )
        )

        if not workflows:
            console.print("\n⚠️  워크플로우가 없습니다.")
            return

        table = Table(title=f"총 {len(workflows)}개의 워크플로우")
        table.add_column("ID", style="cyan")
        table.add_column("이름", style="green")
        table.add_column("상태", style="yellow")
        table.add_column("노드", style="blue")
        table.add_column("실행 횟수", style="magenta")
        table.add_column("생성자", style="white")
        table.add_column("생성일", style="dim")

        for wf in workflows:
            status_emoji = {
                "draft": "📝",
                "active": "✅",
                "inactive": "💤",
                "archived": "📦"
            }

            table.add_row(
                str(wf["id"]),
                wf["name"],
                f"{status_emoji.get(wf['status'], '')} {wf['status']}",
                str(wf["nodes_count"]),
                str(wf["execution_count"]),
                wf["created_by"],
                wf["created_at"][:10]
            )

        console.print()
        console.print(table)

    except Exception as e:
        console.print(f"\n❌ 오류: {e}", style="red")


@workflow_builder.command(name='info')
@click.argument('workflow_id', type=int)
def workflow_info(workflow_id: int):
    """워크플로우 상세 정보

    예시:
      uv run python -m neos.cli workflow-builder info 1
    """
    console.print(Panel.fit(f"ℹ️  워크플로우 상세 정보 (ID: {workflow_id})", style="bold blue"))

    try:
        workflow = asyncio.run(WorkflowManager.get_workflow(workflow_id))

        if not workflow:
            console.print(f"\n❌ ID {workflow_id}인 워크플로우를 찾을 수 없습니다.", style="red")
            return

        # 기본 정보
        info_table = Table(show_header=False, box=None)
        info_table.add_column("속성", style="cyan bold")
        info_table.add_column("값", style="white")

        info_table.add_row("ID", str(workflow["id"]))
        info_table.add_row("이름", workflow["name"])
        info_table.add_row("설명", workflow["description"])
        info_table.add_row("상태", workflow["status"])
        info_table.add_row("생성자", workflow["created_by"])
        info_table.add_row("실행 횟수", str(workflow["execution_count"]))
        info_table.add_row("생성일", workflow["created_at"])

        if workflow["last_executed_at"]:
            info_table.add_row("마지막 실행", workflow["last_executed_at"])

        console.print()
        console.print(info_table)

        # 노드 정보
        if workflow["nodes"]:
            console.print("\n[bold cyan]노드:[/bold cyan]")
            node_table = Table()
            node_table.add_column("이름", style="green")
            node_table.add_column("타입", style="yellow")
            node_table.add_column("MCP 서버", style="blue")

            for node in workflow["nodes"]:
                node_table.add_row(
                    node["name"],
                    node["type"],
                    node.get("mcp_server", "-")
                )

            console.print(node_table)

        # 엣지 정보
        if workflow["edges"]:
            console.print("\n[bold cyan]엣지:[/bold cyan]")
            for edge in workflow["edges"]:
                console.print(f"  {edge['from']} → {edge['to']}")

        # 태그
        if workflow["tags"]:
            console.print(f"\n[bold cyan]태그:[/bold cyan] {', '.join(workflow['tags'])}")

    except Exception as e:
        console.print(f"\n❌ 오류: {e}", style="red")


@workflow_builder.command(name='activate')
@click.argument('workflow_id', type=int)
def activate_workflow(workflow_id: int):
    """워크플로우 활성화

    예시:
      uv run python -m neos.cli workflow-builder activate 1
    """
    try:
        success = asyncio.run(
            WorkflowManager.update_workflow_status(workflow_id, WorkflowStatus.ACTIVE)
        )

        if success:
            console.print(f"\n✅ 워크플로우 ID {workflow_id}가 활성화되었습니다.", style="green")
        else:
            console.print("\n❌ 워크플로우를 찾을 수 없습니다.", style="red")

    except Exception as e:
        console.print(f"\n❌ 오류: {e}", style="red")


@workflow_builder.command(name='deactivate')
@click.argument('workflow_id', type=int)
def deactivate_workflow(workflow_id: int):
    """워크플로우 비활성화

    예시:
      uv run python -m neos.cli workflow-builder deactivate 1
    """
    try:
        success = asyncio.run(
            WorkflowManager.update_workflow_status(workflow_id, WorkflowStatus.INACTIVE)
        )

        if success:
            console.print(f"\n✅ 워크플로우 ID {workflow_id}가 비활성화되었습니다.", style="green")
        else:
            console.print("\n❌ 워크플로우를 찾을 수 없습니다.", style="red")

    except Exception as e:
        console.print(f"\n❌ 오류: {e}", style="red")


@workflow_builder.command(name='execute')
@click.argument('workflow_id', type=int)
@click.option('--query', '-q', required=True, help='실행할 쿼리')
@click.option('--user-id', default='cli_user', help='사용자 ID')
@click.option('--output', '-o', type=click.Choice(['json', 'text']), default='text', help='출력 형식')
def execute_workflow(workflow_id: int, query: str, user_id: str, output: str):
    """워크플로우 실행

    예시:
      uv run python -m neos.cli workflow-builder execute 1 \\
        --query "AI 반도체 시장 동향"
    """
    console.print(Panel.fit(f"🚀 워크플로우 실행 (ID: {workflow_id})", style="bold blue"))
    console.print(f"\n쿼리: {query}\n")

    try:
        executor = WorkflowExecutor(workflow_id)

        # 워크플로우 로드
        asyncio.run(executor.load_workflow())

        console.print(f"워크플로우: {executor.workflow_data.name}")
        console.print(f"설명: {executor.workflow_data.description}")
        console.print(f"노드 수: {len(executor.workflow_data.nodes)}\n")

        # 실행
        from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            TimeElapsedColumn(),
            console=console
        ) as progress:
            task = progress.add_task("워크플로우 실행 중...", total=None)

            result = asyncio.run(
                executor.execute({
                    "query": query,
                    "user_id": user_id,
                    "session_id": f"cli_{datetime.now().timestamp()}"
                })
            )

            progress.update(task, description="✅ 실행 완료")

        # 결과 출력
        if output == 'json':
            console.print("\n[bold cyan]실행 결과:[/bold cyan]")
            console.print(Syntax(json.dumps(result, indent=2, ensure_ascii=False), "json"))
        else:
            console.print("\n" + "="*60)

            if result["success"]:
                console.print("\n[bold green]✅ 실행 성공[/bold green]\n")
                console.print(result.get("response", ""))

                console.print("\n" + "="*60)
                console.print(f"\n실행 시간: {result['execution_time_ms']}ms")

                if result.get("errors"):
                    console.print(f"\n⚠️  경고: {len(result['errors'])}개의 오류 발생")
            else:
                console.print("\n[bold red]❌ 실행 실패[/bold red]\n")
                console.print(f"오류: {result.get('error', 'Unknown error')}")

    except Exception as e:
        console.print(f"\n❌ 오류: {e}", style="red")
        import traceback
        console.print(traceback.format_exc(), style="dim")


@workflow_builder.command(name='delete')
@click.argument('workflow_id', type=int)
@click.option('--yes', '-y', is_flag=True, help='확인 없이 삭제')
def delete_workflow(workflow_id: int, yes: bool):
    """워크플로우 삭제

    예시:
      uv run python -m neos.cli workflow-builder delete 1
      uv run python -m neos.cli workflow-builder delete 1 --yes
    """
    if not yes:
        if not Confirm.ask(f"정말 워크플로우 ID {workflow_id}를 삭제하시겠습니까?"):
            console.print("취소되었습니다.")
            return

    try:
        success = asyncio.run(WorkflowManager.delete_workflow(workflow_id))

        if success:
            console.print(f"\n✅ 워크플로우 ID {workflow_id}가 삭제되었습니다.", style="green")
        else:
            console.print("\n❌ 워크플로우를 찾을 수 없습니다.", style="red")

    except Exception as e:
        console.print(f"\n❌ 오류: {e}", style="red")
