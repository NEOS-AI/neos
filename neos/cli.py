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
    "session_id": str(uuid.uuid4()),
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
        "workflow": False
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
            from workflow.state import SearchResult
            context["search_results"] = [
                SearchResult(
                    source="test",
                    title="Test Result",
                    content=f"Test content for query: {query}",
                    score=0.8
                )
            ]
        
        result = await agent.execute(query, context)
        
        execution_time = time.time() - start_time
        
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
                timeout=300  # 5 minutes timeout
            )
        except asyncio.TimeoutError:
            if cli_state["verbose"]:
                console.print("[red]Workflow execution timed out after 5 minutes[/red]")
            return {
                "success": False,
                "error": "Workflow execution timed out after 5 minutes",
                "query": query,
                "timestamp": datetime.now().isoformat()
            }

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
