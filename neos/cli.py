#!/usr/bin/env python3
"""
Multi-Agent AI System CLI Tool
에이전트와 워크플로우를 테스트하고 관리하는 CLI 도구
"""

import traceback
import asyncio
import json
import time
import uuid
from datetime import datetime
from typing import Dict, Any, List, Optional
import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn
from rich.prompt import Prompt
from rich.syntax import Syntax
import sys

sys.path.append(".")  # 프로젝트 루트 디렉토리 추가
sys.path.append("..")  # 상위 디렉토리 추가

# 프로젝트 모듈 import
try:
    from neos.config.settings import settings
    from neos.database.connection import db_manager
    from neos.utils.cache import cache_manager
    from neos.utils.embeddings import embedding_manager
    from neos.utils.llm_factory import llm_factory, get_recommended_models
    from neos.workflow.graph import multi_agent_workflow
    from neos.agents.search_agents import KnowledgeSearchAgent, RealtimeInfoSearchAgent, RealtimeDataSearchAgent
    from neos.agents.analysis_agents import DataAnalysisAgent, ComparativeAnalysisAgent
    from neos.agents.generation_agents import ImageGenerationAgent, ApiCallAgent, FileProcessingAgent, TaskCreationAgent
    from neos.tools.mcp_integration import mcp_manager, MCPToolType, MCPToolResult
    from neos.tools.tool_selector import tool_selector
    from neos.dataset import llm_call_collector, dataset_manager
    from neos.cli_workflow_builder import workflow_builder
except ImportError as e:
    click.echo(f"❌ 모듈 import 실패: {e}")
    click.echo("프로젝트 루트 디렉토리에서 실행해주세요.")
    sys.exit(1)

# Rich 콘솔 설정
console = Console()

# 전역 상태
cli_state = {
    "verbose": False,
    "profile": False,
    "session_id": f"cli_{uuid.uuid4()}",  # CLI mode detection via prefix
    "user_id": "cli_user"
}

@click.group()
@click.option('--verbose', '-v', is_flag=True, help='자세한 출력 표시')
@click.option('--profile', '-p', is_flag=True, help='성능 프로파일링 활성화')
@click.version_option(version='1.0.0', prog_name='Multi-Agent AI CLI')
def cli(verbose: bool, profile: bool):
    """🤖 Multi-Agent AI System CLI Tool

    에이전트, 워크플로우, 시스템을 테스트하고 관리하는 도구입니다.
    """
    cli_state["verbose"] = verbose
    cli_state["profile"] = profile

    if verbose:
        console.print("🔧 Verbose mode enabled", style="dim")
    if profile:
        console.print("📊 Performance profiling enabled", style="dim")

# 워크플로우 빌더 명령어 그룹 등록
cli.add_command(workflow_builder)

@cli.command()
def status():
    """시스템 상태 확인"""
    console.print(Panel.fit("🔍 System Status Check", style="bold blue"))
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console
    ) as progress:
        
        task1 = progress.add_task("Checking configuration...", total=None)
        
        # 설정 확인
        config_status = _check_configuration()
        progress.update(task1, description="✅ Configuration checked")
        
        task2 = progress.add_task("Checking services...", total=None)
        
        # 서비스 확인
        services_status = asyncio.run(_check_services())
        progress.update(task2, description="✅ Services checked")
        
        task3 = progress.add_task("Checking agents...", total=None)
        
        # 에이전트 확인
        agents_status = _check_agents()
        progress.update(task3, description="✅ Agents checked")
    
    # 결과 출력
    _display_status_results(config_status, services_status, agents_status)

def _check_configuration() -> Dict[str, Any]:
    """설정 확인"""
    status = {
        "api_keys": {},
        "llm_config": {},
        "database": {},
        "cache": {}
    }
    
    # API 키 확인
    status["api_keys"]["openai"] = bool(settings.OPENAI_API_KEY)
    status["api_keys"]["anthropic"] = bool(settings.ANTHROPIC_API_KEY)
    status["api_keys"]["tavily"] = bool(settings.TAVILY_API_KEY)
    
    # LLM 설정
    status["llm_config"]["provider"] = settings.LLM_PROVIDER
    status["llm_config"]["model"] = settings.LLM_MODEL
    status["llm_config"]["temperature"] = settings.LLM_TEMPERATURE
    
    # 데이터베이스
    status["database"]["url"] = settings.DATABASE_URL.split("@")[-1] if "@" in settings.DATABASE_URL else "configured"
    status["database"]["pool_size"] = settings.DATABASE_POOL_SIZE
    
    # 캐시
    status["cache"]["url"] = settings.REDIS_URL
    status["cache"]["ttl"] = settings.REDIS_TTL
    
    return status

async def _check_services() -> Dict[str, Any]:
    """서비스 상태 확인"""
    status = {
        "database": False,
        "cache": False,
        "openai": False,
        "workflow": False,
        "mcp": False,
        "tool_selector": False
    }
    
    try:
        # 데이터베이스
        status["database"] = await db_manager.health_check()
    except Exception as e:
        if cli_state["verbose"]:
            console.print(f"DB check error: {e}", style="dim red")
    
    try:
        # 캐시
        status["cache"] = await cache_manager.health_check()
    except Exception as e:
        if cli_state["verbose"]:
            console.print(f"Cache check error: {e}", style="dim red")
    
    try:
        # OpenAI
        test_embedding = await embedding_manager.get_embedding("test", use_cache=False)
        status["openai"] = test_embedding is not None
    except Exception as e:
        if cli_state["verbose"]:
            console.print(f"OpenAI check error: {e}", style="dim red")
    
    try:
        # 워크플로우
        status["workflow"] = multi_agent_workflow is not None
    except Exception as e:
        if cli_state["verbose"]:
            console.print(f"Workflow check error: {e}", style="dim red")

    try:
        # MCP 매니저
        if settings.MCP_ENABLED:
            init_results = await mcp_manager.initialize()
            status["mcp"] = any(init_results.values()) if init_results else False
        else:
            status["mcp"] = False
    except Exception as e:
        if cli_state["verbose"]:
            console.print(f"MCP check error: {e}", style="dim red")

    try:
        # 도구 선택기
        status["tool_selector"] = await tool_selector.health_check()
    except Exception as e:
        if cli_state["verbose"]:
            console.print(f"Tool selector check error: {e}", style="dim red")

    return status

def _check_agents() -> Dict[str, Any]:
    """에이전트 상태 확인"""
    agents = {
        "search": {
            "knowledge_search": KnowledgeSearchAgent,
            "realtime_info_search": RealtimeInfoSearchAgent,
            "realtime_data_search": RealtimeDataSearchAgent
        },
        "analysis": {
            "data_analysis": DataAnalysisAgent,
            "comparative_analysis": ComparativeAnalysisAgent
        },
        "generation": {
            "image_generation": ImageGenerationAgent,
            "api_call": ApiCallAgent,
            "file_processing": FileProcessingAgent,
            "task_creation": TaskCreationAgent
        }
    }
    
    status = {}
    for category, agent_classes in agents.items():
        status[category] = {}
        for name, agent_class in agent_classes.items():
            try:
                _ = agent_class()
                status[category][name] = True
            except Exception as e:
                status[category][name] = False
                if cli_state["verbose"]:
                    console.print(f"Agent {name} error: {e}", style="dim red")
    return status

def _display_status_results(config_status: Dict, services_status: Dict, agents_status: Dict):
    """상태 결과 표시"""
    
    # 설정 상태
    config_table = Table(title="📋 Configuration Status")
    config_table.add_column("Category", style="cyan")
    config_table.add_column("Item", style="magenta")
    config_table.add_column("Status", style="green")
    
    for category, items in config_status.items():
        if isinstance(items, dict):
            for key, value in items.items():
                status_icon = "✅" if value else "❌"
                config_table.add_row(category.replace("_", " ").title(), key, f"{status_icon} {value}")
        else:
            config_table.add_row(category.replace("_", " ").title(), "", str(items))
    
    # 서비스 상태
    services_table = Table(title="🔧 Services Status")
    services_table.add_column("Service", style="cyan")
    services_table.add_column("Status", style="green")

    for service, status in services_status.items():
        status_icon = "✅" if status else "❌"
        services_table.add_row(service.replace("_", " ").title(), f"{status_icon} {'Healthy' if status else 'Error'}")
    
    # 에이전트 상태
    agents_table = Table(title="🤖 Agents Status")
    agents_table.add_column("Category", style="cyan")
    agents_table.add_column("Agent", style="magenta")
    agents_table.add_column("Status", style="green")
    
    for category, agents in agents_status.items():
        for agent, status in agents.items():
            status_icon = "✅" if status else "❌"
            agents_table.add_row(category.title(), agent.replace("_", " ").title(), f"{status_icon} {'Ready' if status else 'Error'}")
    
    console.print(config_table)
    console.print()
    console.print(services_table)
    console.print()
    console.print(agents_table)

@cli.group()
def agent():
    """에이전트 테스트 및 관리"""
    pass

@agent.command()
@click.argument('agent_type', type=click.Choice([
    'knowledge_search', 'realtime_info_search', 'realtime_data_search',
    'data_analysis', 'comparative_analysis',
    'image_generation', 'api_call', 'file_processing', 'task_creation'
]))
@click.argument('query')
@click.option('--output', '-o', type=click.Choice(['json', 'table', 'text']), default='text', help='출력 형식')
def test_agent(agent_type: str, query: str, output: str):
    """개별 에이전트 테스트
    
    AGENT_TYPE: 테스트할 에이전트 타입
    QUERY: 테스트 쿼리
    """
    console.print(f"🧪 Testing {agent_type} agent with query: [bold]{query}[/bold]")
    
    result = asyncio.run(_test_single_agent(agent_type, query))
    
    if output == 'json':
        console.print(Syntax(json.dumps(result, indent=2, ensure_ascii=False), "json"))
    elif output == 'table':
        _display_agent_result_table(agent_type, result)
    else:
        _display_agent_result_text(agent_type, result)

async def _test_single_agent(agent_type: str, query: str) -> Dict[str, Any]:
    """단일 에이전트 테스트"""
    agent_classes = {
        'knowledge_search': KnowledgeSearchAgent,
        'realtime_info_search': RealtimeInfoSearchAgent,
        'realtime_data_search': RealtimeDataSearchAgent,
        'data_analysis': DataAnalysisAgent,
        'comparative_analysis': ComparativeAnalysisAgent,
        'image_generation': ImageGenerationAgent,
        'api_call': ApiCallAgent,
        'file_processing': FileProcessingAgent,
        'task_creation': TaskCreationAgent
    }
    
    if agent_type not in agent_classes:
        return {"error": f"Unknown agent type: {agent_type}"}
    
    try:
        start_time = time.time()
        
        agent = agent_classes[agent_type]()
        context = {
            "user_id": cli_state["user_id"],
            "session_id": cli_state["session_id"],
            "query_embedding": await embedding_manager.get_embedding(query) if agent_type.endswith('_search') else None
        }
        
        # 분석 에이전트의 경우 더미 검색 결과 제공
        if agent_type in ['data_analysis', 'comparative_analysis']:
            from neos.workflow.state import SearchResult
            context["search_results"] = [
                SearchResult(
                    source="test_source_1",
                    title=f"{query} - 분석 결과 1",
                    content=f"{query}에 대한 데이터: 성장률 15.3%, 시장 규모 $2.5B, 2024-01-15 기준. 전년 대비 12% 증가.",
                    score=0.85,
                    metadata={"date": "2024-01-15", "category": "analysis"}
                ),
                SearchResult(
                    source="test_source_2",
                    title=f"{query} - 분석 결과 2",
                    content=f"{query} 관련 통계: 평균값 87.2, 중간값 82.5, 최대값 95.8, 최소값 72.3. 표준편차 8.4.",
                    score=0.78,
                    metadata={"date": "2024-02-20", "category": "statistics"}
                ),
                SearchResult(
                    source="test_source_3",
                    title=f"{query} - 트렌드 분석",
                    content=f"{query} 트렌드: Q1 $1.2M, Q2 $1.5M, Q3 $1.8M, Q4 예상 $2.1M. 2023-01-01부터 2023-12-31까지 데이터.",
                    score=0.92,
                    metadata={"date": "2023-12-31", "category": "trend"}
                )
            ]
        
        result = await agent.execute(query, context)

        execution_time = time.time() - start_time

        # 데이터셋 자동 저장 (LLM 호출이 있었다면)
        records = llm_call_collector.get_all_records()
        if records:
            try:
                print(f"[DEBUG] Auto-saving dataset with {len(records)} records...")
                filepath = dataset_manager.save_jsonl(records=records)
                print(f"[DEBUG] Dataset auto-saved to: {filepath}")
                # 저장 후 레코드 초기화
                llm_call_collector.clear_records()
            except Exception as e:
                print(f"[WARNING] Failed to auto-save dataset: {e}")

        return {
            "agent_type": agent_type,
            "query": query,
            "execution_time_ms": int(execution_time * 1000),
            "result": result,
            "timestamp": datetime.now().isoformat()
        }

    except Exception as e:
        return {
            "agent_type": agent_type,
            "query": query,
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }

def _display_agent_result_table(agent_type: str, result: Dict[str, Any]):
    """에이전트 결과를 테이블 형식으로 표시"""
    table = Table(title=f"🤖 {agent_type.replace('_', ' ').title()} Agent Result")
    table.add_column("Field", style="cyan")
    table.add_column("Value", style="green")
    
    table.add_row("Agent Type", agent_type)
    table.add_row("Query", result.get("query", ""))
    table.add_row("Execution Time", f"{result.get('execution_time_ms', 0)}ms")
    table.add_row("Success", "✅" if result.get("result", {}).get("success", False) else "❌")
    
    if "error" in result:
        table.add_row("Error", result["error"])
    
    if "result" in result and "result" in result["result"]:
        agent_result = result["result"]["result"]
        if isinstance(agent_result, list):
            table.add_row("Results Count", str(len(agent_result)))
            if agent_result:
                table.add_row("First Result Type", type(agent_result[0]).__name__)
        else:
            table.add_row("Result Type", type(agent_result).__name__)
    
    console.print(table)

def _display_agent_result_text(agent_type: str, result: Dict[str, Any]):
    """에이전트 결과를 텍스트 형식으로 표시"""
    if result.get("result", {}).get("success", False):
        console.print(f"✅ [green]Agent {agent_type} executed successfully[/green]")
        console.print(f"⏱️  Execution time: {result.get('execution_time_ms', 0)}ms")
        
        agent_result = result.get("result", {}).get("result")
        if isinstance(agent_result, list):
            console.print(f"📊 Results: {len(agent_result)} items")
            for i, item in enumerate(agent_result[:3]):  # 처음 3개만 표시
                console.print(f"  {i+1}. {type(item).__name__}")
                if hasattr(item, 'title'):
                    console.print(f"     Title: {item.title}")
                if hasattr(item, 'content'):
                    console.print(f"     Content: {item.content[:100]}...")
        else:
            console.print(f"📋 Result: {type(agent_result).__name__}")
    else:
        console.print(f"❌ [red]Agent {agent_type} failed[/red]")
        if "error" in result:
            console.print(f"🚨 Error: {result['error']}")

@agent.command()
@click.option('--category', type=click.Choice(['search', 'analysis', 'generation', 'all']), default='all', help='테스트할 에이전트 카테고리')
@click.option('--concurrent', '-c', is_flag=True, help='병렬 실행')
def benchmark_agent(category: str, concurrent: bool):
    """에이전트 성능 벤치마크"""
    console.print(f"🏃‍♂️ Running benchmark for {category} agents...")

    results = asyncio.run(_run_agent_benchmark(category, concurrent))
    _display_benchmark_results(results)

async def _run_agent_benchmark(category: str, concurrent: bool) -> List[Dict[str, Any]]:
    """에이전트 벤치마크 실행"""
    test_queries = {
        'search': [
            "AI 최신 트렌드",
            "머신러닝 발전사",
            "클라우드 컴퓨팅 통계"
        ],
        'analysis': [
            "데이터 분석 결과",
            "A와 B 비교 분석",
            "시장 동향 분석"
        ],
        'generation': [
            "로봇 이미지 생성",
            "날씨 API 호출",
            "엑셀 파일 처리",
            "프로젝트 계획 생성"
        ]
    }
    
    agents_to_test = {
        'search': ['knowledge_search', 'realtime_info_search', 'realtime_data_search'],
        'analysis': ['data_analysis', 'comparative_analysis'],
        'generation': ['image_generation', 'api_call', 'file_processing', 'task_creation']
    }
    
    categories = [category] if category != 'all' else ['search', 'analysis', 'generation']
    
    results = []
    tasks = []
    
    for cat in categories:
        queries = test_queries[cat]
        agents = agents_to_test[cat]
        
        for agent_type in agents:
            for query in queries:
                if concurrent:
                    tasks.append(_test_single_agent(agent_type, query))
                else:
                    result = await _test_single_agent(agent_type, query)
                    results.append(result)
    
    if concurrent and tasks:
        concurrent_results = await asyncio.gather(*tasks, return_exceptions=True)
        for result in concurrent_results:
            if isinstance(result, Exception):
                results.append({"error": str(result)})
            else:
                results.append(result)
    
    return results

def _display_benchmark_results(results: List[Dict[str, Any]]):
    """벤치마크 결과 표시"""
    table = Table(title="📊 Agent Benchmark Results")
    table.add_column("Agent", style="cyan")
    table.add_column("Query", style="magenta")
    table.add_column("Status", style="green")
    table.add_column("Time (ms)", style="yellow")
    table.add_column("Results", style="blue")
    
    total_time = 0
    success_count = 0
    
    for result in results:
        if "error" in result:
            table.add_row("Error", result.get("query", ""), "❌", "-", result["error"][:50])
            continue
        
        agent_type = result.get("agent_type", "")
        query = result.get("query", "")[:30] + "..." if len(result.get("query", "")) > 30 else result.get("query", "")
        exec_time = result.get("execution_time_ms", 0)
        success = result.get("result", {}).get("success", False)
        
        status = "✅" if success else "❌"
        time_str = f"{exec_time}"
        
        agent_result = result.get("result", {}).get("result")
        result_info = ""
        if isinstance(agent_result, list):
            result_info = f"{len(agent_result)} items"
        elif agent_result:
            result_info = type(agent_result).__name__
        
        table.add_row(agent_type, query, status, time_str, result_info)
        
        if success:
            success_count += 1
            total_time += exec_time
    
    console.print(table)
    
    # 요약 통계
    total_tests = len([r for r in results if "error" not in r])
    if total_tests > 0:
        avg_time = total_time / total_tests
        success_rate = (success_count / total_tests) * 100
        
        summary_table = Table(title="📈 Summary Statistics")
        summary_table.add_column("Metric", style="cyan")
        summary_table.add_column("Value", style="green")
        
        summary_table.add_row("Total Tests", str(total_tests))
        summary_table.add_row("Successful", str(success_count))
        summary_table.add_row("Success Rate", f"{success_rate:.1f}%")
        summary_table.add_row("Average Time", f"{avg_time:.0f}ms")
        summary_table.add_row("Total Time", f"{total_time:.0f}ms")
        
        console.print()
        console.print(summary_table)

@cli.group()
def workflow():
    """워크플로우 테스트 및 관리"""
    pass

@workflow.command()
@click.argument('query')
@click.option('--output', '-o', type=click.Choice(['json', 'text']), default='text', help='출력 형식')
@click.option('--user-id', default=None, help='사용자 ID')
@click.option('--session-id', default=None, help='세션 ID')
def test(query: str, output: str, user_id: Optional[str], session_id: Optional[str]):
    """전체 워크플로우 테스트
    
    QUERY: 테스트할 쿼리
    """
    user_id = user_id or cli_state["user_id"]
    session_id = session_id or cli_state["session_id"]
    
    console.print(f"🔄 Testing full workflow with query: [bold]{query}[/bold]")
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TimeElapsedColumn(),
        console=console
    ) as progress:
        
        task = progress.add_task("Executing workflow...", total=None)
        
        result = asyncio.run(_test_full_workflow(query, user_id, session_id, progress, task))
        
        progress.update(task, description="✅ Workflow completed")
    
    if output == 'json':
        console.print(Syntax(json.dumps(result, indent=2, ensure_ascii=False), "json"))
    else:
        _display_workflow_result(result)

async def _test_full_workflow(query: str, user_id: str, session_id: str, progress, task) -> Dict[str, Any]:
    """전체 워크플로우 테스트"""
    try:
        start_time = time.time()

        workflow_input = {
            "user_id": user_id,
            "session_id": session_id,
            "query": query
        }

        if cli_state["verbose"]:
            console.print(f"[dim]Starting workflow with input: {workflow_input}[/dim]")

        if progress:
            progress.update(task, description="🔍 Classifying query...")
        await asyncio.sleep(0.1)  # UI 업데이트를 위한 짧은 대기

        if progress:
            progress.update(task, description="🤖 Executing agents...")

        if cli_state["verbose"]:
            console.print("[dim]Calling multi_agent_workflow.execute_workflow...[/dim]")

        # Add timeout to prevent hanging
        try:
            result = await asyncio.wait_for(
                multi_agent_workflow.execute_workflow(workflow_input),
                timeout=600  # 10 minutes timeout (복합검색 에이전트 사용시 더 오래 걸림)
            )
        except asyncio.TimeoutError:
            if cli_state["verbose"]:
                console.print("[red]Workflow execution timed out after 10 minutes[/red]")
            return {
                "success": False,
                "error": "Workflow execution timed out after 10 minutes",
                "query": query,
                "timestamp": datetime.now().isoformat()
            }
        finally:
            # 워크플로우 실행 후 리소스 정리 (aiohttp 세션 닫기)
            try:
                await multi_agent_workflow.cleanup()
            except Exception as cleanup_error:
                if cli_state["verbose"]:
                    console.print(f"[dim]Cleanup warning: {cleanup_error}[/dim]")

        if cli_state["verbose"]:
            console.print(f"[dim]Workflow completed with result keys: {list(result.keys()) if result else 'None'}[/dim]")

        execution_time = time.time() - start_time
        result["total_execution_time_ms"] = int(execution_time * 1000)
        result["query"] = query
        result["user_id"] = user_id
        result["session_id"] = session_id
        result["timestamp"] = datetime.now().isoformat()

        return result

    except Exception as e:
        if cli_state["verbose"]:
            console.print(f"[red]Workflow exception: {e}[/red]")
            console.print(f"[dim]Traceback: {traceback.format_exc()}[/dim]")

        # 예외 발생 시에도 정리
        try:
            await multi_agent_workflow.cleanup()
        except Exception:
            pass

        return {
            "success": False,
            "error": str(e),
            "query": query,
            "timestamp": datetime.now().isoformat(),
            "traceback": traceback.format_exc() if cli_state["verbose"] else None
        }

def _display_workflow_result(result: Dict[str, Any]):
    """워크플로우 결과 표시"""
    console.print(result)
    if result.get("success", False):
        console.print("✅ [green]Workflow executed successfully[/green]")
        
        # 기본 정보
        info_table = Table(title="📋 Workflow Information")
        info_table.add_column("Field", style="cyan")
        info_table.add_column("Value", style="green")
        
        info_table.add_row("Query", result.get("query", ""))
        info_table.add_row("User ID", result.get("user_id", ""))
        info_table.add_row("Session ID", result.get("session_id", ""))
        info_table.add_row("Total Execution Time", f"{result.get('total_execution_time_ms', 0)}ms")
        info_table.add_row("Workflow Execution Time", f"{result.get('execution_time_ms', 0)}ms")
        info_table.add_row("Quality Score", f"{result.get('quality_score', 0):.2f}")
        info_table.add_row("Cache Hit", "✅" if result.get("cache_hit", False) else "❌")
        
        console.print(info_table)
        
        # 메타데이터
        if "metadata" in result:
            metadata = result["metadata"]
            meta_table = Table(title="📊 Execution Metadata")
            meta_table.add_column("Metric", style="cyan")
            meta_table.add_column("Value", style="green")
            
            for key, value in metadata.items():
                meta_table.add_row(key.replace("_", " ").title(), str(value))
            
            console.print()
            console.print(meta_table)
        
        # 응답 내용
        console.print()
        console.print(Panel(result.get("response", "No response"), title="💬 Response", style="blue"))
        
        # 에러가 있다면 표시
        if result.get("errors"):
            console.print()
            error_panel = Panel("\n".join(result["errors"]), title="⚠️ Errors", style="red")
            console.print(error_panel)
    
    else:
        console.print("❌ [red]Workflow execution failed[/red]")
        if "error" in result:
            console.print(Panel(result["error"], title="🚨 Error", style="red"))

@workflow.command()
@click.option('--queries', '-q', multiple=True, help='테스트할 쿼리들 (여러 개 가능)')
@click.option('--file', '-f', type=click.Path(exists=True), help='쿼리가 포함된 파일')
@click.option('--concurrent', '-c', is_flag=True, help='병렬 실행')
def benchmark(queries: tuple, file: Optional[str], concurrent: bool):
    """워크플로우 성능 벤치마크"""
    
    # 쿼리 준비
    test_queries = list(queries) if queries else []
    
    if file:
        with open(file, 'r', encoding='utf-8') as f:
            file_queries = [line.strip() for line in f if line.strip()]
            test_queries.extend(file_queries)
    
    if not test_queries:
        test_queries = [
            "2024년 AI 트렌드를 분석해주세요",
            "iPhone과 Galaxy를 비교해주세요",
            "로봇 이미지를 생성해주세요",
            "프로젝트 계획을 세워주세요",
            "최신 기술 동향을 조사해주세요"
        ]
    
    console.print(f"🏁 Running workflow benchmark with {len(test_queries)} queries...")
    console.print(f"🔄 Execution mode: {'Concurrent' if concurrent else 'Sequential'}")
    
    results = asyncio.run(_run_workflow_benchmark(test_queries, concurrent))
    _display_workflow_benchmark_results(results)

async def _run_workflow_benchmark(queries: List[str], concurrent: bool) -> List[Dict[str, Any]]:
    """워크플로우 벤치마크 실행"""
    if concurrent:
        tasks = []
        for i, query in enumerate(queries):
            user_id = f"bench_user_{i}"
            session_id = f"bench_session_{i}"
            task = _test_full_workflow(query, user_id, session_id, None, None)
            tasks.append(task)
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return [r if not isinstance(r, Exception) else {"error": str(r)} for r in results]
    
    else:
        results = []
        for i, query in enumerate(queries):
            console.print(f"🔄 Processing query {i+1}/{len(queries)}: {query[:50]}...")
            user_id = f"bench_user_{i}"
            session_id = f"bench_session_{i}"
            result = await _test_full_workflow(query, user_id, session_id, None, None)
            results.append(result)
        
        return results

def _display_workflow_benchmark_results(results: List[Dict[str, Any]]):
    """워크플로우 벤치마크 결과 표시"""
    table = Table(title="🚀 Workflow Benchmark Results")
    table.add_column("Query", style="cyan")
    table.add_column("Status", style="green")
    table.add_column("Time (ms)", style="yellow")
    table.add_column("Quality", style="blue")
    table.add_column("Cache", style="magenta")
    
    total_time = 0
    success_count = 0
    quality_scores = []
    cache_hits = 0
    
    for result in results:
        if "error" in result and "success" not in result:
            table.add_row("Error", "❌", "-", "-", "-")
            continue
        
        query = result.get("query", "")[:40] + "..." if len(result.get("query", "")) > 40 else result.get("query", "")
        success = result.get("success", False)
        exec_time = result.get("total_execution_time_ms", 0)
        quality = result.get("quality_score", 0)
        cache_hit = result.get("cache_hit", False)
        
        status = "✅" if success else "❌"
        time_str = f"{exec_time}"
        quality_str = f"{quality:.2f}"
        cache_str = "✅" if cache_hit else "❌"
        
        table.add_row(query, status, time_str, quality_str, cache_str)
        
        if success:
            success_count += 1
            total_time += exec_time
            quality_scores.append(quality)
            if cache_hit:
                cache_hits += 1
    
    console.print(table)
    
    # 요약 통계
    total_tests = len([r for r in results if not ("error" in r and "success" not in r)])
    if total_tests > 0:
        avg_time = total_time / total_tests if total_tests > 0 else 0
        success_rate = (success_count / total_tests) * 100
        avg_quality = sum(quality_scores) / len(quality_scores) if quality_scores else 0
        cache_hit_rate = (cache_hits / total_tests) * 100
        
        summary_table = Table(title="📈 Benchmark Summary")
        summary_table.add_column("Metric", style="cyan")
        summary_table.add_column("Value", style="green")
        
        summary_table.add_row("Total Tests", str(total_tests))
        summary_table.add_row("Successful", str(success_count))
        summary_table.add_row("Success Rate", f"{success_rate:.1f}%")
        summary_table.add_row("Average Time", f"{avg_time:.0f}ms")
        summary_table.add_row("Average Quality", f"{avg_quality:.2f}")
        summary_table.add_row("Cache Hit Rate", f"{cache_hit_rate:.1f}%")
        summary_table.add_row("Total Time", f"{total_time:.0f}ms")
        
        console.print()
        console.print(summary_table)


@workflow.command()
@click.argument('query')
@click.option('--output', '-o', type=click.Choice(['json', 'text']), default='text', help='출력 형식')
@click.option('--user-id', default=None, help='사용자 ID')
@click.option('--session-id', default=None, help='세션 ID')
def deep_research(query: str, output: str, user_id: Optional[str], session_id: Optional[str]):
    """Deep Research 모드 - 장시간 심층 조사 및 고품질 리포트 생성

    QUERY: 조사할 주제

    예시:
      uv run python -m neos.cli workflow deep-research "AI 반도체 시장 전망 및 주요 기업 분석"
    """
    user_id = user_id or cli_state["user_id"]
    session_id = session_id or cli_state["session_id"]

    console.print(Panel.fit(
        f"🔬 [bold]Deep Research Mode[/bold]\n"
        f"주제: {query}\n\n"
        f"예상 소요 시간: 15-25분\n"
        f"수집 예상 소스: 30-50개\n"
        f"처리 단계: 4단계 (탐색 → Gap분석 → 검증 → 리포트)",
        style="bold blue"
    ))

    console.print()
    console.print("[yellow]⚠️  Deep Research는 장시간 실행됩니다. 진행 상황을 모니터링하세요.[/yellow]")
    console.print()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TimeElapsedColumn(),
        console=console
    ) as progress:

        task = progress.add_task("Executing deep research...", total=None)

        result = asyncio.run(_test_deep_research(query, user_id, session_id, progress, task))

        progress.update(task, description="✅ Deep Research completed")

    if output == 'json':
        console.print(Syntax(json.dumps(result, indent=2, ensure_ascii=False), "json"))
    else:
        _display_deep_research_result(result)


@workflow.command()
@click.argument('query')
@click.option('--output', '-o', type=click.Choice(['json', 'text']), default='text', help='출력 형식')
@click.option('--user-id', default=None, help='사용자 ID')
@click.option('--session-id', default=None, help='세션 ID')
def hyper_deep_research(query: str, output: str, user_id: Optional[str], session_id: Optional[str]):
    """HyperDeepResearch 모드 - 최고 수준의 체계적 심층 조사 및 DB 저장

    QUERY: 조사할 주제

    예시:
      uv run python -m neos.cli workflow hyper-deep-research "2025년 글로벌 AI 시장 전망과 주요 기업 전략 분석"
    """
    user_id = user_id or cli_state["user_id"]
    session_id = session_id or cli_state["session_id"]

    console.print(Panel.fit(
        f"🚀 [bold]HyperDeepResearch Mode[/bold]\n"
        f"주제: {query}\n\n"
        f"예상 소요 시간: 30-60분\n"
        f"수집 예상 소스: 200-320개 (복합 검색 포함)\n"
        f"처리 단계: 8단계 (주제분석 → 방법론 → 데이터수집 → 심층분석 → 갭분석 → 교차검증 → 비판적사고 → 보고서)\n"
        f"🔄 복합 검색: 8회 multi-query 검색 실행\n"
        f"💾 모든 결과가 데이터베이스에 저장됩니다",
        style="bold cyan"
    ))

    console.print()
    console.print("[yellow]⚠️  HyperDeepResearch는 매우 장시간 실행됩니다. 진행 상황을 모니터링하세요.[/yellow]")
    console.print()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TimeElapsedColumn(),
        console=console
    ) as progress:

        task = progress.add_task("Executing HyperDeepResearch...", total=None)

        result = asyncio.run(_test_hyper_deep_research(query, user_id, session_id, progress, task))

        progress.update(task, description="✅ HyperDeepResearch completed")

    if output == 'json':
        console.print(Syntax(json.dumps(result, indent=2, ensure_ascii=False), "json"))
    else:
        _display_hyper_deep_research_result(result)

async def _test_deep_research(query: str, user_id: str, session_id: str, progress, task) -> Dict[str, Any]:
    """Deep Research 실행 - 직접 에이전트 호출"""
    try:
        start_time = time.time()

        if progress:
            progress.update(task, description="Phase 1/4: Initial Exploration...")
        await asyncio.sleep(0.1)

        # Deep Research 에이전트 직접 생성 및 실행
        from neos.agents.search_agents.deep_research import DeepResearchAgent
        from neos.utils.language_detection import detect_language

        deep_agent = DeepResearchAgent()

        # 언어 감지
        detected_language = detect_language(query)

        context = {
            "user_id": user_id,
            "session_id": session_id,
            "detected_language": detected_language
        }

        # 긴 타임아웃 설정 (30분)
        try:
            agent_result = await asyncio.wait_for(
                deep_agent.execute(query, context),
                timeout=1800  # 30 minutes timeout for deep research
            )
        except asyncio.TimeoutError:
            return {
                "success": False,
                "error": "Deep research timed out after 30 minutes",
                "query": query,
                "timestamp": datetime.now().isoformat()
            }

        # 결과 변환
        if agent_result.get("success") and agent_result.get("results"):
            search_result = agent_result["results"][0]

            # Handle both dict and SearchResult objects
            if isinstance(search_result, dict):
                content = search_result.get("content", "")
                metadata = search_result.get("metadata", {})
                score = search_result.get("score", 0.95)
            else:
                # SearchResult object
                content = getattr(search_result, 'content', '')
                metadata = getattr(search_result, 'metadata', {})
                score = getattr(search_result, 'score', 0.95)

            result = {
                "success": True,
                "response": content,
                "metadata": metadata,
                "quality_score": score
            }
        else:
            result = {
                "success": False,
                "error": agent_result.get("error", "Unknown error"),
                "response": ""
            }

        execution_time = time.time() - start_time
        result["total_execution_time_ms"] = int(execution_time * 1000)
        result["query"] = query
        result["user_id"] = user_id
        result["session_id"] = session_id
        result["timestamp"] = datetime.now().isoformat()

        return result

    except Exception as e:
        import traceback
        return {
            "success": False,
            "error": str(e),
            "query": query,
            "timestamp": datetime.now().isoformat(),
            "traceback": traceback.format_exc()
        }

def _display_deep_research_result(result: Dict[str, Any]):
    """Deep Research 결과 표시"""
    if result.get("success", False):
        console.print("✅ [green]Deep Research completed successfully[/green]")

        # 기본 정보
        info_table = Table(title="🔬 Deep Research Information")
        info_table.add_column("Field", style="cyan")
        info_table.add_column("Value", style="green")

        info_table.add_row("Query", result.get("query", ""))
        info_table.add_row("User ID", result.get("user_id", ""))
        info_table.add_row("Session ID", result.get("session_id", ""))
        info_table.add_row("Total Time", f"{result.get('total_execution_time_ms', 0) / 1000:.1f}s")
        info_table.add_row("Quality Score", f"{result.get('quality_score', 0):.2f}")

        console.print(info_table)

        # 메타데이터
        if "metadata" in result:
            metadata = result["metadata"]
            meta_table = Table(title="📊 Research Statistics")
            meta_table.add_column("Metric", style="cyan")
            meta_table.add_column("Value", style="green")

            meta_table.add_row("Total Sources", str(metadata.get("total_sources", 0)))
            meta_table.add_row("Processing Steps", str(metadata.get("processing_steps", 0)))

            console.print()
            console.print(meta_table)

        # 리포트 내용 - Deep Research는 매우 긴 리포트를 생성하므로 Markdown으로 렌더링
        console.print()
        response_text = result.get("response", "No response")

        # Markdown 형식으로 렌더링 (Deep Research 리포트는 마크다운 형식)
        try:
            from rich.markdown import Markdown
            console.print(Panel(
                Markdown(response_text),
                title="📝 Deep Research Report",
                style="blue",
                expand=True
            ))
        except Exception:
            # Markdown 렌더링 실패시 일반 텍스트로 표시
            console.print(Panel(
                response_text,
                title="📝 Deep Research Report",
                style="blue",
                expand=True
            ))

    else:
        console.print("❌ [red]Deep Research failed[/red]")
        if "error" in result:
            console.print(Panel(result["error"], title="🚨 Error", style="red"))


async def _test_hyper_deep_research(query: str, user_id: str, session_id: str, progress, task) -> Dict[str, Any]:
    """HyperDeepResearch 실행 - 직접 에이전트 호출"""
    try:
        start_time = time.time()

        if progress:
            progress.update(task, description="Phase 1/8: Multi-Dimensional Topic Analysis...")
        await asyncio.sleep(0.1)

        # HyperDeepResearch 에이전트 직접 생성 및 실행
        from neos.agents.search_agents.hyper_deep_research import HyperDeepResearchAgent
        from neos.utils.language_detection import detect_language

        hyper_agent = HyperDeepResearchAgent()

        # 언어 감지
        detected_language = detect_language(query)

        context = {
            "user_id": user_id,
            "session_id": session_id,
            "detected_language": detected_language
        }

        # 매우 긴 타임아웃 설정 (120분)
        try:
            agent_result = await asyncio.wait_for(
                hyper_agent.execute(query, context),
                timeout=14400  # 240 minutes timeout for hyper deep research
            )
        except asyncio.TimeoutError:
            return {
                "success": False,
                "error": "HyperDeepResearch timed out after 240 minutes",
                "query": query,
                "timestamp": datetime.now().isoformat()
            }

        # 결과 변환
        print(f"[DEBUG] HyperDeepResearch agent result keys: {agent_result.keys() if agent_result else 'None'}")
        print(f"[DEBUG] HyperDeepResearch agent result success: {agent_result.get('success') if agent_result else 'None'}")

        if agent_result.get("success") and agent_result.get("results"):
            search_result = agent_result["results"][0]

            if isinstance(search_result, dict):
                result = {
                    "success": True,
                    "response": search_result.get("content", ""),
                    "metadata": search_result.get("metadata", {}),
                    "quality_score": search_result.get("score", 0.95)
                }
            else:
                # SearchResult
                result = {
                    "success": True,
                    "response": search_result.content,
                    "metadata": search_result.metadata,
                    "quality_score": search_result.score
                }
        else:
            error_msg = agent_result.get("error", "Unknown error") if agent_result else "No result returned"
            print(f"[DEBUG] HyperDeepResearch failed or no results. Error: {error_msg}")
            print(f"[DEBUG] Full agent_result: {agent_result}")
            result = {
                "success": False,
                "error": error_msg,
                "response": ""
            }

        execution_time = time.time() - start_time
        result["total_execution_time_ms"] = int(execution_time * 1000)
        result["query"] = query
        result["user_id"] = user_id
        result["session_id"] = session_id
        result["timestamp"] = datetime.now().isoformat()

        # 데이터셋 수집 종료 및 저장
        try:
            from neos.dataset import dataset_manager

            dataset_manager.export_by_session(session_id)
        except Exception as e:
            print(f"[WARNING] Failed to save HyperDeepResearch dataset: {e}")

        return result

    except Exception as e:
        import traceback
        # 에러 발생 시에도 데이터셋 저장 시도
        try:
            from neos.dataset import dataset_manager

            dataset_manager.export_by_session(session_id)
        except Exception:
            print(f"[WARNING] Failed to save HyperDeepResearch dataset: {e}")

        return {
            "success": False,
            "error": str(e),
            "query": query,
            "timestamp": datetime.now().isoformat(),
            "traceback": traceback.format_exc()
        }


def _display_hyper_deep_research_result(result: Dict[str, Any]):
    """HyperDeepResearch 결과 표시"""
    if result.get("success", False):
        console.print("✅ [green]HyperDeepResearch completed successfully[/green]")

        # 기본 정보
        info_table = Table(title="🚀 HyperDeepResearch Information")
        info_table.add_column("Field", style="cyan")
        info_table.add_column("Value", style="green")

        info_table.add_row("Query", result.get("query", ""))
        info_table.add_row("User ID", result.get("user_id", ""))
        info_table.add_row("Session ID", result.get("session_id", ""))
        info_table.add_row("Total Time", f"{result.get('total_execution_time_ms', 0) / 1000:.1f}s")
        info_table.add_row("Quality Score", f"{result.get('quality_score', 0):.2f}")

        console.print(info_table)

        # 메타데이터 - HyperDeepResearch 전용
        if "metadata" in result:
            metadata = result["metadata"]
            meta_table = Table(title="📊 HyperDeepResearch Statistics")
            meta_table.add_column("Metric", style="cyan")
            meta_table.add_column("Value", style="green")

            meta_table.add_row("Report ID", str(metadata.get("report_id", "N/A")))
            meta_table.add_row("Total Sections", str(metadata.get("total_sections", 0)))
            meta_table.add_row("Total Sources", str(metadata.get("total_sources", 0)))
            meta_table.add_row("Total Queries", str(metadata.get("total_queries", 0)))
            meta_table.add_row("Complex Searches", str(metadata.get("multi_query_searches", 0)) if metadata.get("multi_query_searches") else "N/A")
            meta_table.add_row("Unique Domains", str(metadata.get("unique_domains", 0)))
            meta_table.add_row("DB Stored", "✅ Yes" if metadata.get("db_stored") else "❌ No")

            console.print()
            console.print(meta_table)

        # 리포트 내용
        console.print()
        response_text = result.get("response", "No response")

        try:
            from rich.markdown import Markdown
            console.print(Panel(
                Markdown(response_text),
                title="📝 HyperDeepResearch Report",
                style="cyan",
                expand=True
            ))
        except Exception:
            console.print(Panel(
                response_text,
                title="📝 HyperDeepResearch Report",
                style="cyan",
                expand=True
            ))

    else:
        console.print("❌ [red]HyperDeepResearch failed[/red]")
        if "error" in result:
            console.print(Panel(result["error"], title="🚨 Error", style="red"))


@workflow.command()
@click.argument('urls', nargs=-1, required=True)
@click.option('--query', '-q', default=None, help='URL 콘텐츠에 대한 질문 (선택사항)')
@click.option('--output', '-o', type=click.Choice(['json', 'text']), default='text', help='출력 형식')
@click.option('--dynamic', '-d', is_flag=True, help='Playwright로 동적 페이지 렌더링 (JavaScript 지원)')
@click.option('--user-id', default=None, help='사용자 ID')
@click.option('--session-id', default=None, help='세션 ID')
def web_lookup(urls: tuple, query: Optional[str], output: str, dynamic: bool, user_id: Optional[str], session_id: Optional[str]):
    """WebLookUp 에이전트 - URL 콘텐츠 추출 및 분석

    URLS: 분석할 URL(들) (여러 개 가능)

    예시:
      # 단일 URL 분석
      uv run python -m neos.cli workflow web-lookup https://www.anthropic.com/claude

      # 다중 URL 비교
      uv run python -m neos.cli workflow web-lookup https://github.com https://gitlab.com

      # 특정 질문과 함께
      uv run python -m neos.cli workflow web-lookup https://blog.openai.com/chatgpt --query "이 글의 핵심 내용은?"

      # 동적 페이지 렌더링 (JavaScript 지원)
      uv run python -m neos.cli workflow web-lookup https://spa-app.com --dynamic
    """
    user_id = user_id or cli_state["user_id"]
    session_id = session_id or cli_state["session_id"]

    # URL 리스트를 쿼리 형식으로 변환
    if query:
        full_query = f"{' '.join(urls)} {query}"
    else:
        full_query = f"{' '.join(urls)} 이 페이지의 내용을 분석해줘"

    rendering_method = "🎭 Playwright (동적)" if dynamic else "📄 Static HTML"
    estimated_time = "10-30초" if dynamic else "5-15초"

    console.print(Panel.fit(
        f"🔗 [bold]WebLookUp Agent[/bold]\n"
        f"URL(s): {', '.join(urls)}\n"
        f"질문: {query or '기본 분석'}\n"
        f"렌더링 방식: {rendering_method}\n\n"
        f"URL 개수: {len(urls)}개\n"
        f"예상 소요 시간: {estimated_time} (URL당)",
        style="bold green"
    ))

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TimeElapsedColumn(),
        console=console
    ) as progress:

        task = progress.add_task("Executing WebLookUp...", total=None)

        result = asyncio.run(_test_web_lookup(full_query, urls, dynamic, user_id, session_id, progress, task))

        progress.update(task, description="✅ WebLookUp completed")

    if output == 'json':
        console.print(Syntax(json.dumps(result, indent=2, ensure_ascii=False), "json"))
    else:
        _display_web_lookup_result(result)


async def _test_web_lookup(query: str, urls: tuple, dynamic: bool, user_id: str, session_id: str, progress, task) -> Dict[str, Any]:
    """WebLookUp 에이전트 실행"""
    try:
        start_time = time.time()

        if progress:
            rendering_desc = "with Playwright" if dynamic else "statically"
            progress.update(task, description=f"Fetching {len(urls)} URL(s) {rendering_desc}...")
        await asyncio.sleep(0.1)

        # WebLookUp 에이전트 직접 생성 및 실행
        from neos.agents.search_agents import WebLookUpAgent
        from neos.utils.language_detection import detect_language

        web_agent = WebLookUpAgent(use_playwright=dynamic)

        # 언어 감지
        detected_language = detect_language(query)

        context = {
            "user_id": user_id,
            "session_id": session_id,
            "detected_language": detected_language,
            "use_playwright": dynamic
        }

        if progress:
            progress.update(task, description="Parsing HTML and extracting content...")

        # 타임아웃 설정 (URL당 30초 + 여유)
        timeout = max(60, len(urls) * 30 + 30)

        try:
            agent_result = await asyncio.wait_for(
                web_agent.execute(query, context),
                timeout=timeout
            )
        except asyncio.TimeoutError:
            return {
                "success": False,
                "error": f"WebLookUp timed out after {timeout} seconds",
                "query": query,
                "urls": list(urls),
                "timestamp": datetime.now().isoformat()
            }

        if progress:
            progress.update(task, description="Analyzing content with LLM...")

        # 결과 변환
        if agent_result.get("success") and agent_result.get("result"):
            search_results = agent_result["result"]

            # SearchResult 객체들을 딕셔너리로 변환
            if search_results and hasattr(search_results[0], '__dict__'):
                response_parts = []
                sources_info = []

                for sr in search_results:
                    response_parts.append(sr.content)

                    # 메타데이터에서 소스 정보 추출
                    if sr.metadata and "sources" in sr.metadata:
                        sources_info.extend(sr.metadata["sources"])

                # 렌더링 방식 추출
                rendering_method = "playwright" if dynamic else "static"
                if search_results and search_results[0].metadata:
                    # SearchResult의 메타데이터에서 실제 렌더링 방식 확인
                    if search_results[0].metadata.get("sources"):
                        sources = search_results[0].metadata.get("sources", [])
                        if sources and sources[0].get("rendering_method"):
                            rendering_method = sources[0]["rendering_method"]

                result = {
                    "success": True,
                    "response": "\n\n".join(response_parts),
                    "metadata": {
                        "urls_processed": list(urls),
                        "urls_count": len(urls),
                        "sources": sources_info,
                        "processing_type": "web_lookup",
                        "rendering_method": rendering_method
                    },
                    "quality_score": search_results[0].score if search_results else 0.0
                }
            else:
                result = {
                    "success": True,
                    "response": str(search_results),
                    "metadata": {
                        "urls_processed": list(urls),
                        "urls_count": len(urls)
                    },
                    "quality_score": 0.8
                }
        else:
            result = {
                "success": False,
                "error": agent_result.get("error", "Unknown error"),
                "query": query,
                "urls": list(urls)
            }

        execution_time = time.time() - start_time
        result["total_execution_time_ms"] = int(execution_time * 1000)
        result["query"] = query
        result["urls"] = list(urls)
        result["user_id"] = user_id
        result["session_id"] = session_id
        result["timestamp"] = datetime.now().isoformat()

        return result

    except Exception as e:
        import traceback
        return {
            "success": False,
            "error": str(e),
            "query": query,
            "urls": list(urls),
            "timestamp": datetime.now().isoformat(),
            "traceback": traceback.format_exc() if cli_state["verbose"] else None
        }


def _display_web_lookup_result(result: Dict[str, Any]):
    """WebLookUp 결과 표시"""
    if result.get("success", False):
        console.print("✅ [green]WebLookUp completed successfully[/green]")

        # 기본 정보
        info_table = Table(title="🔗 WebLookUp Information")
        info_table.add_column("Field", style="cyan")
        info_table.add_column("Value", style="green")

        rendering_method = result.get("metadata", {}).get("rendering_method", "static")
        rendering_display = "🎭 Playwright (동적)" if rendering_method == "playwright" else "📄 Static HTML"

        info_table.add_row("Query", result.get("query", ""))
        info_table.add_row("Rendering Method", rendering_display)
        info_table.add_row("URLs Processed", str(result.get("metadata", {}).get("urls_count", len(result.get("urls", [])))))
        info_table.add_row("Total Time", f"{result.get('total_execution_time_ms', 0)}ms")
        info_table.add_row("Quality Score", f"{result.get('quality_score', 0):.2f}")

        console.print(info_table)

        # URL 목록
        if result.get("urls"):
            urls_table = Table(title="📄 Analyzed URLs")
            urls_table.add_column("#", style="cyan", width=4)
            urls_table.add_column("URL", style="blue")

            for i, url in enumerate(result["urls"], 1):
                urls_table.add_row(str(i), url)

            console.print()
            console.print(urls_table)

        # 소스 정보
        if result.get("metadata", {}).get("sources"):
            sources = result["metadata"]["sources"]
            sources_table = Table(title="📚 Source Details")
            sources_table.add_column("#", style="cyan", width=4)
            sources_table.add_column("Title", style="yellow")
            sources_table.add_column("URL", style="blue")

            for i, source in enumerate(sources[:10], 1):  # 최대 10개만 표시
                title = source.get("title", "N/A")[:50]
                url = source.get("url", "N/A")[:60]
                sources_table.add_row(str(i), title, url)

            console.print()
            console.print(sources_table)

            if len(sources) > 10:
                console.print(f"[dim]... and {len(sources) - 10} more sources[/dim]")

        # 분석 결과
        console.print()
        response_text = result.get("response", "No response")

        try:
            from rich.markdown import Markdown
            console.print(Panel(
                Markdown(response_text),
                title="💬 Analysis Result",
                style="green",
                expand=True
            ))
        except Exception:
            console.print(Panel(
                response_text,
                title="💬 Analysis Result",
                style="green",
                expand=True
            ))

    else:
        console.print("❌ [red]WebLookUp failed[/red]")
        if "error" in result:
            console.print(Panel(result["error"], title="🚨 Error", style="red"))
        if cli_state["verbose"] and "traceback" in result:
            console.print()
            console.print(Panel(result["traceback"], title="🐛 Traceback", style="dim red"))


@cli.command()
def interactive():
    """대화형 모드"""
    console.print(Panel.fit("🤖 Multi-Agent AI Interactive Mode", style="bold blue"))
    console.print("Type 'exit' to quit, 'help' for commands")
    console.print()

    session_id = str(uuid.uuid4())
    user_id = "interactive_user"
    
    while True:
        try:
            query = Prompt.ask("\n[bold cyan]Query[/bold cyan]")
            
            if query.lower() in ['exit', 'quit', 'q']:
                console.print("👋 Goodbye!")
                break
            
            elif query.lower() == 'help':
                _show_interactive_help()
                continue
            
            elif query.lower() == 'status':
                asyncio.run(_interactive_status())
                continue
            
            elif query.lower().startswith('agent '):
                parts = query.split(' ', 2)
                if len(parts) >= 3:
                    agent_type = parts[1]
                    agent_query = parts[2]
                    result = asyncio.run(_test_single_agent(agent_type, agent_query))
                    _display_agent_result_text(agent_type, result)
                else:
                    console.print("❌ Usage: agent <type> <query>")
                continue
            
            # 일반 쿼리 - 워크플로우 실행
            with console.status("🤔 Thinking..."):
                result = asyncio.run(_test_full_workflow(query, user_id, session_id, None, None))
            
            if result.get("success", False):
                console.print("\n💬 [bold green]Response:[/bold green]")
                console.print(Panel(result.get("response", "No response"), style="blue"))
                
                # 간단한 메타데이터 표시
                metadata = result.get("metadata", {})
                time_ms = result.get("execution_time_ms", 0)
                quality = result.get("quality_score", 0)
                
                console.print(f"⏱️  Time: {time_ms}ms | 📊 Quality: {quality:.2f} | 🎯 Sources: {metadata.get('total_sources', 0)}")
            else:
                console.print(f"❌ [red]Error:[/red] {result.get('error', 'Unknown error')}")
        
        except KeyboardInterrupt:
            console.print("\n👋 Goodbye!")
            break
        except Exception as e:
            console.print(f"❌ [red]Unexpected error:[/red] {e}")

def _show_interactive_help():
    """대화형 모드 도움말"""
    help_table = Table(title="🔧 Interactive Mode Commands")
    help_table.add_column("Command", style="cyan")
    help_table.add_column("Description", style="green")
    
    help_table.add_row("exit, quit, q", "Exit interactive mode")
    help_table.add_row("help", "Show this help")
    help_table.add_row("status", "Check system status")
    help_table.add_row("agent <type> <query>", "Test specific agent")
    help_table.add_row("<any query>", "Execute full workflow")
    
    console.print(help_table)

async def _interactive_status():
    """대화형 모드에서 상태 확인"""
    services_status = await _check_services()
    
    status_table = Table(title="🔍 Quick Status")
    status_table.add_column("Service", style="cyan")
    status_table.add_column("Status", style="green")
    
    for service, status in services_status.items():
        status_icon = "✅" if status else "❌"
        status_table.add_row(service.title(), f"{status_icon} {'OK' if status else 'Error'}")
    
    console.print(status_table)

@cli.command()
def config():
    """설정 확인 및 관리"""
    console.print(Panel.fit("⚙️ Configuration Management", style="bold blue"))
    
    # LLM Provider 정보
    providers_table = Table(title="🤖 LLM Providers")
    providers_table.add_column("Provider", style="cyan")
    providers_table.add_column("Available", style="green")
    providers_table.add_column("Current", style="yellow")
    providers_table.add_column("Models", style="magenta")
    
    available_providers = llm_factory.get_available_providers()
    current_provider = settings.LLM_PROVIDER
    
    for provider in ["openai", "anthropic"]:
        is_available = provider in available_providers
        is_current = provider == current_provider
        
        models = get_recommended_models(provider)
        model_list = ", ".join([f"{k}:{v}" for k, v in models.items()]) if models else "None"
        
        providers_table.add_row(
            provider.title(),
            "✅" if is_available else "❌",
            "🔥" if is_current else "",
            model_list[:50] + "..." if len(model_list) > 50 else model_list
        )
    
    console.print(providers_table)
    
    # 현재 설정
    current_table = Table(title="📋 Current Configuration")
    current_table.add_column("Setting", style="cyan")
    current_table.add_column("Value", style="green")
    
    current_table.add_row("LLM Provider", settings.LLM_PROVIDER)
    current_table.add_row("LLM Model", settings.LLM_MODEL)
    current_table.add_row("LLM Temperature", str(settings.LLM_TEMPERATURE))
    current_table.add_row("Embedding Model", settings.EMBEDDING_MODEL)
    current_table.add_row("Search System", "Hybrid (Vector + Keyword)")
    current_table.add_row("Vector Extension", "pgvector")
    current_table.add_row("Debug Mode", str(settings.DEBUG))
    current_table.add_row("Log Level", settings.LOG_LEVEL)

    console.print()
    console.print(current_table)

@cli.group()
def mcp():
    """MCP (Model Context Protocol) 관리"""
    pass

@mcp.command()
def mcp_status():
    """MCP 서버 및 도구 상태 확인"""
    console.print(Panel.fit("🔧 MCP Status Check", style="bold blue"))

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console
    ) as progress:

        task = progress.add_task("Checking MCP status...", total=None)

        status_result = asyncio.run(_check_mcp_status())

        progress.update(task, description="✅ MCP status checked")

    _display_mcp_status(status_result)

async def _check_mcp_status() -> Dict[str, Any]:
    """MCP 상태 확인"""
    status = {
        "enabled": settings.MCP_ENABLED,
        "config": {
            "host": settings.MCP_SERVER_HOST,
            "port": settings.MCP_SERVER_PORT,
            "timeout": settings.MCP_TIMEOUT,
            "retry_count": settings.MCP_RETRY_COUNT,
            "fallback_enabled": settings.MCP_FALLBACK_ENABLED
        },
        "manager_status": False,
        "initialized_tools": {},
        "available_tools": [],
        "tool_selector_status": False
    }

    if not settings.MCP_ENABLED:
        return status

    try:
        # MCP 매니저 초기화 및 상태 확인
        init_results = await mcp_manager.initialize()
        status["manager_status"] = True
        status["initialized_tools"] = init_results

        # 사용 가능한 도구 목록
        available_tools = mcp_manager.get_available_tools()
        status["available_tools"] = [
            {
                "name": tool.name,
                "type": tool.tool_type.value,
                "description": tool.description,
                "capabilities": tool.capabilities
            }
            for tool in available_tools
        ]

    except Exception as e:
        status["error"] = str(e)

    try:
        # 도구 선택기 상태
        status["tool_selector_status"] = await tool_selector.health_check()
    except Exception as e:
        status["tool_selector_error"] = str(e)

    return status

def _display_mcp_status(status: Dict[str, Any]):
    """MCP 상태 표시"""

    # 기본 설정
    config_table = Table(title="⚙️ MCP Configuration")
    config_table.add_column("Setting", style="cyan")
    config_table.add_column("Value", style="green")

    config_table.add_row("Enabled", "✅" if status["enabled"] else "❌")
    config_table.add_row("Host", status["config"]["host"])
    config_table.add_row("Port", str(status["config"]["port"]))
    config_table.add_row("Timeout", f"{status['config']['timeout']}s")
    config_table.add_row("Retry Count", str(status["config"]["retry_count"]))
    config_table.add_row("Fallback Enabled", "✅" if status["config"]["fallback_enabled"] else "❌")
    config_table.add_row("Manager Status", "✅" if status["manager_status"] else "❌")
    config_table.add_row("Tool Selector", "✅" if status["tool_selector_status"] else "❌")

    console.print(config_table)

    if not status["enabled"]:
        console.print("\n[yellow]MCP is disabled. Set MCP_ENABLED=true to enable.[/yellow]")
        return

    # 초기화된 도구들
    if status.get("initialized_tools"):
        init_table = Table(title="🔧 Tool Initialization Results")
        init_table.add_column("Tool", style="cyan")
        init_table.add_column("Status", style="green")

        for tool_name, is_init in status["initialized_tools"].items():
            status_icon = "✅" if is_init else "❌"
            init_table.add_row(tool_name, f"{status_icon} {'Initialized' if is_init else 'Failed'}")

        console.print()
        console.print(init_table)

    # 사용 가능한 도구들
    if status.get("available_tools"):
        tools_table = Table(title="🛠️ Available MCP Tools")
        tools_table.add_column("Name", style="cyan")
        tools_table.add_column("Type", style="magenta")
        tools_table.add_column("Description", style="green")
        tools_table.add_column("Capabilities", style="blue")

        for tool in status["available_tools"]:
            capabilities = ", ".join(tool["capabilities"][:3])
            if len(tool["capabilities"]) > 3:
                capabilities += "..."

            tools_table.add_row(
                tool["name"],
                tool["type"],
                tool["description"][:50] + "..." if len(tool["description"]) > 50 else tool["description"],
                capabilities
            )

        console.print()
        console.print(tools_table)

    # 에러가 있다면 표시
    if status.get("error"):
        console.print()
        console.print(Panel(status["error"], title="❌ Error", style="red"))

@mcp.command()
@click.argument('tool_name')
@click.option('--params', '-p', help='도구 실행 파라미터 (JSON 형식)')
def test_tool(tool_name: str, params: Optional[str]):
    """특정 MCP 도구 테스트"""
    console.print(f"🧪 Testing MCP tool: [bold]{tool_name}[/bold]")

    # 파라미터 파싱
    tool_params = {}
    if params:
        try:
            tool_params = json.loads(params)
        except json.JSONDecodeError as e:
            console.print(f"❌ Invalid JSON parameters: {e}")
            return

    result = asyncio.run(_test_mcp_tool(tool_name, tool_params))
    _display_mcp_tool_result(tool_name, result)

async def _test_mcp_tool(tool_name: str, params: Dict[str, Any]) -> MCPToolResult:
    """MCP 도구 테스트"""
    try:
        if not settings.MCP_ENABLED:
            return MCPToolResult(
                success=False,
                data=None,
                error="MCP is not enabled",
                tool_name=tool_name
            )

        # MCP 매니저 초기화 (필요시)
        if not mcp_manager.initialization_complete:
            await mcp_manager.initialize()

        return await mcp_manager.execute_tool(tool_name, params)

    except Exception as e:
        return MCPToolResult(
            success=False,
            data=None,
            error=str(e),
            tool_name=tool_name
        )

def _display_mcp_tool_result(tool_name: str, result: MCPToolResult):
    """MCP 도구 결과 표시"""
    if result.success:
        console.print(f"✅ [green]MCP tool {tool_name} executed successfully[/green]")

        result_table = Table(title=f"🛠️ {tool_name} Result")
        result_table.add_column("Field", style="cyan")
        result_table.add_column("Value", style="green")

        result_table.add_row("Tool Name", result.tool_name)
        result_table.add_row("Execution Time", f"{result.execution_time_ms}ms")
        result_table.add_row("Success", "✅")

        if result.metadata:
            for key, value in result.metadata.items():
                result_table.add_row(key.replace("_", " ").title(), str(value))

        console.print(result_table)

        # 결과 데이터 표시
        if result.data:
            console.print()
            if isinstance(result.data, (list, dict)):
                console.print(Panel(Syntax(json.dumps(result.data, indent=2, ensure_ascii=False), "json"), title="📊 Data", style="blue"))
            else:
                console.print(Panel(str(result.data), title="📊 Data", style="blue"))

    else:
        console.print(f"❌ [red]MCP tool {tool_name} failed[/red]")
        if result.error:
            console.print(Panel(result.error, title="🚨 Error", style="red"))

@mcp.command()
@click.option('--type', 'tool_type', type=click.Choice(['web_search', 'file_processing', 'data_analysis', 'api_integration', 'code_execution', 'image_processing']), help='특정 도구 타입만 테스트')
def test_all(tool_type: Optional[str]):
    """모든 MCP 도구 테스트"""
    console.print("🔄 Testing all MCP tools...")

    results = asyncio.run(_test_all_mcp_tools(tool_type))
    _display_all_mcp_results(results)

async def _test_all_mcp_tools(tool_type_filter: Optional[str]) -> List[Dict[str, Any]]:
    """모든 MCP 도구 테스트"""
    results = []

    try:
        if not settings.MCP_ENABLED:
            return [{"error": "MCP is not enabled"}]

        # MCP 매니저 초기화
        await mcp_manager.initialize()

        # 도구 타입 필터링
        if tool_type_filter:
            tool_type_enum = MCPToolType(tool_type_filter)
            available_tools = mcp_manager.get_available_tools(tool_type_enum)
        else:
            available_tools = mcp_manager.get_available_tools()

        # 각 도구별 테스트 파라미터
        test_params = {
            "web_search_mcp": {"query": "AI technology trends 2024", "max_results": 3},
            "file_processing_mcp": {"operation": "list", "file_path": "."},
            "database_mcp": {"operation": "health_check"},
            "git_mcp": {"operation": "status"},
        }

        # 특정 도구별 추가 테스트 케이스
        additional_test_cases = {
            "database_mcp": [
                {"operation": "query", "query": "SELECT 1 as test_column"},
                {"operation": "query", "query": "WITH test_cte AS (SELECT 1 as id) SELECT * FROM test_cte"}
            ]
        }

        for tool in available_tools:
            # 기본 테스트 실행
            start_time = time.time()
            params = test_params.get(tool.name, {"test": True})
            result = await mcp_manager.execute_tool(tool.name, params)
            execution_time = int((time.time() - start_time) * 1000)

            results.append({
                "tool_name": tool.name,
                "tool_type": tool.tool_type.value,
                "success": result.success,
                "error": result.error,
                "execution_time_ms": execution_time,
                "data_size": len(str(result.data)) if result.data else 0,
                "metadata": result.metadata,
                "test_case": "basic"
            })

            # 추가 테스트 케이스 실행 (있는 경우)
            if tool.name in additional_test_cases:
                for i, additional_params in enumerate(additional_test_cases[tool.name]):
                    start_time = time.time()
                    result = await mcp_manager.execute_tool(tool.name, additional_params)
                    execution_time = int((time.time() - start_time) * 1000)

                    results.append({
                        "tool_name": f"{tool.name}_case_{i+1}",
                        "tool_type": tool.tool_type.value,
                        "success": result.success,
                        "error": result.error,
                        "execution_time_ms": execution_time,
                        "data_size": len(str(result.data)) if result.data else 0,
                        "metadata": result.metadata,
                        "test_case": f"additional_{i+1}",
                        "params": additional_params
                    })

    except Exception as e:
        results.append({"error": str(e)})

    return results

def _display_all_mcp_results(results: List[Dict[str, Any]]):
    """모든 MCP 도구 결과 표시"""
    table = Table(title="🧪 MCP Tools Test Results")
    table.add_column("Tool", style="cyan")
    table.add_column("Type", style="magenta")
    table.add_column("Status", style="green")
    table.add_column("Time (ms)", style="yellow")
    table.add_column("Data Size", style="blue")

    success_count = 0
    total_time = 0

    for result in results:
        if "error" in result and "tool_name" not in result:
            table.add_row("System Error", "-", "❌", "-", result["error"][:50])
            continue

        tool_name = result.get("tool_name", "Unknown")
        tool_type = result.get("tool_type", "Unknown")
        success = result.get("success", False)
        exec_time = result.get("execution_time_ms", 0)
        data_size = result.get("data_size", 0)

        status = "✅" if success else "❌"
        time_str = f"{exec_time}"
        size_str = f"{data_size} chars"

        table.add_row(tool_name, tool_type, status, time_str, size_str)

        if success:
            success_count += 1
        total_time += exec_time

    console.print(table)

    # 요약 통계
    total_tests = len([r for r in results if "tool_name" in r])
    if total_tests > 0:
        avg_time = total_time / total_tests
        success_rate = (success_count / total_tests) * 100

        summary_table = Table(title="📈 Test Summary")
        summary_table.add_column("Metric", style="cyan")
        summary_table.add_column("Value", style="green")

        summary_table.add_row("Total Tests", str(total_tests))
        summary_table.add_row("Successful", str(success_count))
        summary_table.add_row("Success Rate", f"{success_rate:.1f}%")
        summary_table.add_row("Average Time", f"{avg_time:.0f}ms")

        console.print()
        console.print(summary_table)

@mcp.command()
@click.argument('name')
@click.argument('tool_type', type=click.Choice(['web_search', 'file_processing', 'data_analysis', 'api_integration', 'code_execution', 'image_processing']))
@click.option('--description', '-d', default="Custom MCP tool", help='도구 설명')
@click.option('--capabilities', '-c', multiple=True, help='도구 기능 목록')
def register(name: str, tool_type: str, description: str, capabilities: tuple):
    """새로운 MCP 도구 등록 (예제 코드 생성)"""
    console.print(f"📝 Generating MCP tool template: [bold]{name}[/bold]")

    template = _generate_mcp_tool_template(name, tool_type, description, list(capabilities))

    console.print()
    console.print(Panel(Syntax(template, "python"), title=f"🛠️ {name} MCP Tool Template", style="blue"))

    console.print("\n[yellow]💡 이 템플릿을 사용하여 새로운 MCP 도구를 구현하고 mcp_manager.register_tool()로 등록하세요.[/yellow]")

@mcp.command()
@click.argument('query')
@click.option('--format', '-f', type=click.Choice(['json', 'table']), default='table', help='출력 형식')
def test_query(query: str, format: str):
    """데이터베이스 쿼리 테스트 (SELECT 및 CTE WITH 문 지원)"""
    console.print(f"🔍 Testing database query: [bold]{query[:50]}...[/bold]")

    params = {"operation": "query", "query": query}
    result = asyncio.run(_test_mcp_tool("database_mcp", params))

    if result.success:
        console.print("✅ [green]Query validation successful[/green]")

        if format == 'json':
            console.print(Panel(Syntax(json.dumps(result.data, indent=2, ensure_ascii=False), "json"), title="📊 Query Result", style="blue"))
        else:
            result_table = Table(title="🔍 Query Test Result")
            result_table.add_column("Field", style="cyan")
            result_table.add_column("Value", style="green")

            result_table.add_row("Query", query)
            result_table.add_row("Validation", "✅ Passed")
            result_table.add_row("Execution Time", f"{result.execution_time_ms}ms")

            if result.metadata:
                for key, value in result.metadata.items():
                    result_table.add_row(key.replace("_", " ").title(), str(value))

            console.print(result_table)
    else:
        console.print("❌ [red]Query validation failed[/red]")
        console.print(Panel(result.error, title="🚨 Error", style="red"))

@mcp.command()
def demo_queries():
    """CTE 및 복잡한 쿼리 데모"""
    console.print(Panel.fit("📚 Database Query Examples", style="bold blue"))

    demo_queries = [
        {
            "name": "Simple SELECT",
            "query": "SELECT 1 as test_column, 'Hello' as message",
            "description": "기본 SELECT 문"
        },
        {
            "name": "Basic CTE",
            "query": "WITH test_cte AS (SELECT 1 as id, 'Test' as name) SELECT * FROM test_cte",
            "description": "기본 CTE (Common Table Expression)"
        },
        {
            "name": "Multiple CTE",
            "query": """WITH
                users_cte AS (SELECT 1 as user_id, 'Alice' as name),
                orders_cte AS (SELECT 1 as order_id, 1 as user_id, 100 as amount)
            SELECT u.name, o.amount
            FROM users_cte u
            JOIN orders_cte o ON u.user_id = o.user_id""",
            "description": "다중 CTE 및 JOIN"
        },
        {
            "name": "Recursive CTE",
            "query": """WITH RECURSIVE numbers AS (
                SELECT 1 as n
                UNION ALL
                SELECT n + 1 FROM numbers WHERE n < 5
            ) SELECT * FROM numbers""",
            "description": "재귀 CTE"
        }
    ]

    for demo in demo_queries:
        console.print(f"\n[bold cyan]{demo['name']}[/bold cyan]: {demo['description']}")
        console.print(Panel(Syntax(demo['query'], "sql"), style="dim"))

        # 실제 테스트 실행
        params = {"operation": "query", "query": demo['query']}
        result = asyncio.run(_test_mcp_tool("database_mcp", params))

        if result.success:
            console.print(f"✅ [green]Valid query[/green] ({result.execution_time_ms}ms)")
        else:
            console.print(f"❌ [red]Invalid query: {result.error}[/red]")

@cli.group()
def dataset():
    """LLM 호출 데이터셋 관리"""
    pass

@dataset.command()
def dataset_status():
    """데이터셋 수집 상태 확인"""
    console.print(Panel.fit("📊 Dataset Collection Status", style="bold blue"))

    stats = llm_call_collector.get_statistics()

    status_table = Table(title="📈 Collection Statistics")
    status_table.add_column("Metric", style="cyan")
    status_table.add_column("Value", style="green")

    status_table.add_row("Enabled", "✅" if stats.get("enabled") else "❌")
    status_table.add_row("Total Records", str(stats.get("total_records", 0)))
    status_table.add_row("Successful Calls", str(stats.get("successful_calls", 0)))
    status_table.add_row("Failed Calls", str(stats.get("failed_calls", 0)))
    status_table.add_row("Success Rate", f"{stats.get('success_rate', 0) * 100:.1f}%")
    status_table.add_row("Total Tokens", f"{stats.get('total_tokens', 0):,}")
    status_table.add_row("Avg Latency", f"{stats.get('average_latency_ms', 0):.1f}ms")

    console.print(status_table)

    # 워크플로우 단계별
    if stats.get("workflow_steps"):
        steps_table = Table(title="🔄 Workflow Steps")
        steps_table.add_column("Step", style="cyan")

        for step in stats.get("workflow_steps", []):
            steps_table.add_row(step)

        console.print()
        console.print(steps_table)

    # 에이전트별
    if stats.get("agents"):
        agents_table = Table(title="🤖 Agents")
        agents_table.add_column("Agent", style="magenta")

        for agent in stats.get("agents", []):
            agents_table.add_row(agent)

        console.print()
        console.print(agents_table)

    # 모델별
    if stats.get("models"):
        models_table = Table(title="🧠 Models")
        models_table.add_column("Provider", style="yellow")
        models_table.add_column("Model", style="blue")

        for provider in stats.get("providers", []):
            for model in stats.get("models", []):
                if provider in model.lower():
                    models_table.add_row(provider, model)

        console.print()
        console.print(models_table)

@dataset.command()
@click.option('--format', '-f', type=click.Choice(['jsonl', 'json', 'csv', 'openai', 'anthropic']), default='jsonl', help='출력 형식')
@click.option('--session', '-s', help='특정 세션만 내보내기')
@click.option('--agent', '-a', help='특정 에이전트만 내보내기')
@click.option('--step', help='특정 워크플로우 단계만 내보내기')
def export(format: str, session: Optional[str], agent: Optional[str], step: Optional[str]):
    """데이터셋 내보내기"""
    console.print(f"💾 Exporting dataset in {format} format...")

    try:
        # 필터링된 내보내기
        if session:
            filepath = dataset_manager.export_by_session(session, format if format in ['jsonl', 'json', 'csv'] else 'jsonl')
        elif agent:
            filepath = dataset_manager.export_by_agent(agent, format if format in ['jsonl', 'json', 'csv'] else 'jsonl')
        elif step:
            filepath = dataset_manager.export_by_workflow_step(step, format if format in ['jsonl', 'json', 'csv'] else 'jsonl')
        else:
            # 전체 내보내기
            if format == 'openai':
                filepath = dataset_manager.save_training_format(format_type='openai')
            elif format == 'anthropic':
                filepath = dataset_manager.save_training_format(format_type='anthropic')
            elif format == 'jsonl':
                filepath = dataset_manager.save_jsonl()
            elif format == 'json':
                filepath = dataset_manager.save_json()
            elif format == 'csv':
                filepath = dataset_manager.save_csv()
            else:
                console.print(f"❌ Unsupported format: {format}")
                return

        if filepath:
            console.print("✅ [green]Dataset exported successfully![/green]")
            console.print(f"📁 File: {filepath}")

            # 파일 정보 표시
            from pathlib import Path
            file_size = Path(filepath).stat().st_size
            console.print(f"📊 Size: {file_size:,} bytes")
        else:
            console.print("⚠️  [yellow]No records to export[/yellow]")

    except Exception as e:
        console.print(f"❌ [red]Export failed:[/red] {e}")
        if cli_state.get("verbose"):
            import traceback
            console.print(traceback.format_exc())

@dataset.command()
def clear():
    """수집된 데이터 초기화"""
    from rich.prompt import Confirm

    if Confirm.ask("⚠️  정말로 모든 수집된 데이터를 삭제하시겠습니까?"):
        count = llm_call_collector.clear_records()
        console.print(f"✅ [green]{count}개의 레코드가 삭제되었습니다.[/green]")
    else:
        console.print("취소되었습니다.")

@dataset.command()
def enable():
    """데이터 수집 활성화"""
    llm_call_collector.enable()
    console.print("✅ [green]Dataset collection enabled[/green]")

@dataset.command()
def disable():
    """데이터 수집 비활성화"""
    llm_call_collector.disable()
    console.print("⏸️  [yellow]Dataset collection disabled[/yellow]")

@dataset.command()
def list_files():
    """저장된 데이터셋 파일 목록"""
    console.print(Panel.fit("📚 Saved Datasets", style="bold blue"))

    datasets = dataset_manager.list_datasets()

    if not datasets:
        console.print("📭 No datasets found")
        return

    table = Table(title=f"Found {len(datasets)} dataset(s)")
    table.add_column("Name", style="cyan")
    table.add_column("Size", style="yellow")
    table.add_column("Modified", style="green")

    for ds in datasets:
        size_kb = ds['size_bytes'] / 1024
        table.add_row(
            ds['name'],
            f"{size_kb:.1f} KB",
            ds['modified_at'][:19]
        )

    console.print(table)

@dataset.command()
@click.argument('filepath')
def info(filepath: str):
    """데이터셋 파일 정보 확인"""
    console.print(f"📊 Loading dataset info from: {filepath}")

    try:
        if filepath.endswith('.jsonl'):
            records = dataset_manager.load_jsonl(filepath)
            metadata = None
        elif filepath.endswith('.json'):
            records, metadata = dataset_manager.load_json(filepath)
        else:
            console.print("❌ Unsupported file format. Use .jsonl or .json")
            return

        if not records:
            console.print("⚠️  No records found in file")
            return

        # 통계 생성
        from neos.dataset.models import DatasetMetadata
        if metadata is None:
            metadata = DatasetMetadata()
            metadata.update_statistics(records)

        # 메타데이터 표시
        info_table = Table(title="📋 Dataset Information")
        info_table.add_column("Field", style="cyan")
        info_table.add_column("Value", style="green")

        info_table.add_row("Dataset ID", metadata.dataset_id[:8] + "...")
        info_table.add_row("Name", metadata.name)
        info_table.add_row("Total Records", str(metadata.total_records))
        info_table.add_row("Sessions", str(metadata.total_sessions))
        info_table.add_row("Users", str(metadata.total_users))
        info_table.add_row("Total Tokens", f"{metadata.total_tokens:,}")
        info_table.add_row("Avg Latency", f"{metadata.average_latency_ms:.1f}ms")
        info_table.add_row("Success Rate", f"{metadata.success_rate * 100:.1f}%")

        console.print(info_table)

        # 상세 통계
        if metadata.step_counts:
            steps_table = Table(title="🔄 Workflow Steps")
            steps_table.add_column("Step", style="cyan")
            steps_table.add_column("Count", style="yellow")

            for step, count in sorted(metadata.step_counts.items(), key=lambda x: x[1], reverse=True):
                steps_table.add_row(step, str(count))

            console.print()
            console.print(steps_table)

        if metadata.agent_counts:
            agents_table = Table(title="🤖 Agents")
            agents_table.add_column("Agent", style="magenta")
            agents_table.add_column("Count", style="yellow")

            for agent, count in sorted(metadata.agent_counts.items(), key=lambda x: x[1], reverse=True):
                agents_table.add_row(agent, str(count))

            console.print()
            console.print(agents_table)

    except Exception as e:
        console.print(f"❌ [red]Failed to load dataset:[/red] {e}")
        if cli_state.get("verbose"):
            import traceback
            console.print(traceback.format_exc())

def _generate_mcp_tool_template(name: str, tool_type: str, description: str, capabilities: List[str]) -> str:
    """MCP 도구 템플릿 생성"""
    class_name = ''.join(word.capitalize() for word in name.split('_')) + 'MCPTool'

    template = f'''from neos.tools.mcp_integration import MCPTool, MCPToolType, MCPToolResult
from typing import Dict, Any
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class {class_name}(MCPTool):
    """{description}"""

    def __init__(self):
        super().__init__(
            name="{name}",
            tool_type=MCPToolType.{tool_type.upper()},
            description="{description}",
            capabilities={capabilities}
        )
        self.client = None

    async def initialize(self) -> bool:
        """도구 초기화"""
        try:
            # TODO: MCP 서버 연결 또는 클라이언트 초기화 로직 구현
            logger.info(f"Initializing {{self.name}} MCP tool")

            # 예: 외부 API 클라이언트 초기화
            # self.client = SomeAPIClient(api_key=settings.API_KEY)

            self.is_available = True
            return True
        except Exception as e:
            logger.error(f"Failed to initialize {{self.name}} MCP tool: {{e}}")
            return False

    async def execute(self, params: Dict[str, Any]) -> MCPToolResult:
        """도구 실행"""
        start_time = datetime.now()

        try:
            # TODO: 파라미터 검증
            required_params = ["param1"]  # 필요한 파라미터 목록
            for param in required_params:
                if param not in params:
                    return MCPToolResult(
                        success=False,
                        data=None,
                        error=f"Required parameter '{{param}}' is missing",
                        tool_name=self.name
                    )

            # TODO: 실제 도구 실행 로직 구현
            result_data = {{
                "message": f"{{self.name}} executed successfully",
                "params": params,
                "timestamp": datetime.now().isoformat()
            }}

            execution_time = int((datetime.now() - start_time).total_seconds() * 1000)

            return MCPToolResult(
                success=True,
                data=result_data,
                tool_name=self.name,
                execution_time_ms=execution_time,
                metadata={{"source": "mcp", "tool_type": "{tool_type}"}}
            )

        except Exception as e:
            execution_time = int((datetime.now() - start_time).total_seconds() * 1000)
            return MCPToolResult(
                success=False,
                data=None,
                error=str(e),
                tool_name=self.name,
                execution_time_ms=execution_time
            )

    async def cleanup(self) -> None:
        """도구 정리"""
        if self.client:
            try:
                # TODO: 클라이언트 정리 로직
                logger.info(f"Cleaning up {{self.name}} MCP tool")
            except Exception as e:
                logger.error(f"Error cleaning up {{self.name}} MCP tool: {{e}}")

# 사용 예제:
# from neos.tools.mcp_integration import mcp_manager
#
# # 도구 등록
# custom_tool = {class_name}()
# mcp_manager.register_tool(custom_tool)
#
# # 도구 사용
# result = await mcp_manager.execute_tool("{name}", {{"param1": "value1"}})
'''

    return template


if __name__ == '__main__':
    try:
        cli()
    except KeyboardInterrupt:
        console.print("\n👋 CLI interrupted by user")
    except Exception as e:
        console.print(f"\n❌ [red]CLI Error:[/red] {e}")
        if cli_state.get("verbose", False):
            import traceback
            console.print(traceback.format_exc())
        sys.exit(1)
