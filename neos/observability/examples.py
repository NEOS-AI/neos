"""
Usage examples for NEOS observability module.
Demonstrates how to integrate Phoenix observability into your workflows and agents.
"""

import asyncio
import logging
from typing import Any, Dict, List

from ..config.settings import Settings
from .core import ObservabilityManager
from .decorators import create_observability_decorators
from .middleware import ObservabilityMiddleware, LangGraphObservabilityHook, CrewAIObservabilityHook


logger = logging.getLogger(__name__)


# Example 1: Basic observability setup
async def basic_observability_setup():
    """Example of basic observability setup for NEOS."""

    # Initialize settings
    settings = Settings()

    # Create observability manager
    obs_manager = ObservabilityManager(settings)
    await obs_manager.initialize()

    try:
        # Your application code here
        print("Observability is running!")
        print(f"Phoenix UI available at: http://{settings.PHOENIX_HOST}:{settings.PHOENIX_PORT}")

        # Get some basic metrics
        real_time_metrics = await obs_manager.get_real_time_metrics()
        print(f"Current metrics: {real_time_metrics}")

    finally:
        # Always shutdown properly
        await obs_manager.shutdown()


# Example 2: Using decorators for automatic tracing
async def decorator_examples():
    """Example of using observability decorators."""

    settings = Settings()
    obs_manager = ObservabilityManager(settings)
    await obs_manager.initialize()

    # Create decorators
    obs = create_observability_decorators(obs_manager)

    @obs.workflow(workflow_type="search_analysis")
    async def search_and_analyze_workflow(query: str) -> Dict[str, Any]:
        """Example workflow with automatic tracing."""

        @obs.agent(agent_type="search_agent")
        async def search_knowledge(task: str) -> List[str]:
            """Search agent with automatic tracing."""

            @obs.llm_call(provider="openai", model="gpt-4")
            async def call_llm(prompt: str) -> str:
                """LLM call with automatic tracing."""
                # Simulate LLM call
                await asyncio.sleep(0.1)
                return f"Response to: {prompt}"

            # Simulate search
            search_prompt = f"Search for information about: {task}"
            result = await call_llm(search_prompt)
            return [result]

        @obs.agent(agent_type="analysis_agent")
        async def analyze_results(task: str, search_results: List[str]) -> str:
            """Analysis agent with automatic tracing."""

            # Simulate analysis
            analysis_prompt = f"Analyze these results: {search_results}"

            @obs.llm_call(provider="openai", model="gpt-4")
            async def analyze_with_llm(prompt: str) -> str:
                await asyncio.sleep(0.2)
                return f"Analysis: {prompt}"

            return await analyze_with_llm(analysis_prompt)

        # Execute workflow steps
        search_results = await search_knowledge(f"Search for: {query}")
        analysis = await analyze_results(f"Analyze: {query}", search_results)

        return {
            "query": query,
            "search_results": search_results,
            "analysis": analysis
        }

    try:
        # Run the workflow
        result = await search_and_analyze_workflow("AI trends 2024")
        print(f"Workflow result: {result}")

        # Get metrics
        workflow_metrics = await obs_manager.get_workflow_metrics()
        agent_metrics = await obs_manager.get_agent_metrics()
        llm_metrics = await obs_manager.get_llm_metrics()

        print(f"Workflow metrics: {workflow_metrics}")
        print(f"Agent metrics: {agent_metrics}")
        print(f"LLM metrics: {llm_metrics}")

    finally:
        await obs_manager.shutdown()


# Example 3: Manual workflow and agent tracking
async def manual_tracking_example():
    """Example of manual workflow and agent tracking."""

    settings = Settings()
    obs_manager = ObservabilityManager(settings)
    await obs_manager.initialize()

    try:
        # Start workflow session
        async with obs_manager.trace_workflow(
            workflow_id="manual_example",
            workflow_type="manual_workflow",
            metadata={"user_id": "user123", "session": "session456"}
        ) as workflow_session_id:

            print(f"Started workflow session: {workflow_session_id}")

            # Start agent execution
            async with obs_manager.trace_agent(
                agent_id="search_agent_1",
                agent_type="knowledge_search",
                task="Search for AI information",
                workflow_session_id=workflow_session_id
            ) as agent_execution_id:

                print(f"Started agent execution: {agent_execution_id}")

                # Track LLM call
                await obs_manager.track_llm_call(
                    execution_id=agent_execution_id,
                    provider="openai",
                    model="gpt-4-turbo",
                    prompt="What are the latest AI trends?",
                    response="AI trends include multimodal models, agentic AI, and improved reasoning capabilities.",
                    tokens_used=150,
                    cost=0.003
                )

                # Simulate work
                await asyncio.sleep(0.5)

                print("Agent execution completed")

            print("Workflow completed")

        # Get final metrics
        metrics = await obs_manager.get_real_time_metrics()
        print(f"Final metrics: {metrics}")

    finally:
        await obs_manager.shutdown()


# Example 4: FastAPI integration
def fastapi_integration_example():
    """Example of integrating observability with FastAPI."""

    from fastapi import FastAPI

    app = FastAPI(title="NEOS with Observability")

    # Initialize observability
    settings = Settings()
    obs_manager = ObservabilityManager(settings)

    # Add observability middleware
    app.add_middleware(
        ObservabilityMiddleware,
        observability_manager=obs_manager,
        track_requests=True,
        track_responses=True,
        track_errors=True,
        exclude_paths=["/health", "/metrics", "/docs"]
    )

    @app.on_event("startup")
    async def startup():
        await obs_manager.initialize()
        print("Observability initialized")

    @app.on_event("shutdown")
    async def shutdown():
        await obs_manager.shutdown()
        print("Observability shutdown")

    @app.get("/api/v1/query")
    async def process_query(query: str):
        """API endpoint with automatic observability tracking."""

        # Create decorators
        obs = create_observability_decorators(obs_manager)

        @obs.workflow(workflow_type="api_query")
        async def process_user_query(user_query: str):

            @obs.agent(agent_type="query_processor")
            async def process_query_agent(task: str):
                # Simulate processing
                await asyncio.sleep(0.1)
                return f"Processed: {task}"

            result = await process_query_agent(user_query)
            return {"query": user_query, "result": result}

        return await process_user_query(query)

    @app.get("/api/v1/metrics")
    async def get_metrics():
        """Get observability metrics."""
        real_time = await obs_manager.get_real_time_metrics()
        daily_stats = await obs_manager.get_daily_stats()

        return {
            "real_time": real_time,
            "daily_stats": daily_stats,
            "phoenix_url": f"http://{settings.PHOENIX_HOST}:{settings.PHOENIX_PORT}"
        }

    return app


# Example 5: LangGraph integration
class LangGraphIntegrationExample:
    """Example of integrating observability with LangGraph."""

    def __init__(self):
        self.settings = Settings()
        self.obs_manager = ObservabilityManager(self.settings)
        self.langgraph_hook = LangGraphObservabilityHook(self.obs_manager)

    async def initialize(self):
        await self.obs_manager.initialize()

    async def shutdown(self):
        await self.obs_manager.shutdown()

    async def run_langgraph_workflow(self):
        """Example LangGraph workflow with observability."""

        thread_id = "example_thread_123"
        config = {
            "workflow_id": "example_langgraph_workflow",
            "workflow_type": "multi_agent_search",
            "description": "Example workflow"
        }

        # Start workflow tracking
        await self.langgraph_hook.on_workflow_start(thread_id, config)

        try:
            # Simulate node executions
            nodes = ["search_node", "analysis_node", "synthesis_node"]

            for node_name in nodes:
                await self.langgraph_hook.on_node_start(thread_id, node_name, {"input": "test"})

                # Simulate node work
                await asyncio.sleep(0.1)

                await self.langgraph_hook.on_node_end(thread_id, node_name, {"output": f"result_{node_name}"})

            # End workflow
            final_result = {"final_output": "workflow completed"}
            await self.langgraph_hook.on_workflow_end(thread_id, final_result)

            print(f"LangGraph workflow completed: {thread_id}")

        except Exception as e:
            await self.langgraph_hook.on_workflow_end(thread_id, error=str(e))
            raise


# Example 6: CrewAI integration
class CrewAIIntegrationExample:
    """Example of integrating observability with CrewAI."""

    def __init__(self):
        self.settings = Settings()
        self.obs_manager = ObservabilityManager(self.settings)
        self.crewai_hook = CrewAIObservabilityHook(self.obs_manager)

    async def initialize(self):
        await self.obs_manager.initialize()

    async def shutdown(self):
        await self.obs_manager.shutdown()

    async def run_crewai_workflow(self):
        """Example CrewAI workflow with observability."""

        crew_id = "example_crew_456"
        crew_config = {
            "name": "Research Crew",
            "agents": ["researcher", "analyst", "writer"],
            "tools": ["search", "analysis", "writing"]
        }

        # Start crew tracking
        await self.crewai_hook.on_crew_start(crew_id, crew_config)

        try:
            # Simulate agent executions
            agents = [
                {"id": "researcher", "role": "research_specialist", "task": "Research AI trends"},
                {"id": "analyst", "role": "data_analyst", "task": "Analyze research findings"},
                {"id": "writer", "role": "content_writer", "task": "Write summary report"}
            ]

            for agent in agents:
                await self.crewai_hook.on_agent_start(
                    crew_id, agent["id"], agent["role"], agent["task"]
                )

                # Simulate LLM calls during agent execution
                await self.crewai_hook.on_llm_call(
                    agent_id=agent["id"],
                    provider="openai",
                    model="gpt-4",
                    prompt=f"Task: {agent['task']}",
                    response=f"Completed: {agent['task']}",
                    tokens_used=100,
                    cost=0.002
                )

                # Simulate agent work
                await asyncio.sleep(0.2)

                await self.crewai_hook.on_agent_end(
                    crew_id, agent["id"], {"result": f"completed_{agent['id']}"}
                )

            # End crew
            final_result = {"crew_output": "All agents completed successfully"}
            await self.crewai_hook.on_crew_end(crew_id, final_result)

            print(f"CrewAI workflow completed: {crew_id}")

        except Exception as e:
            await self.crewai_hook.on_crew_end(crew_id, error=str(e))
            raise


# Example 7: Performance monitoring and analysis
async def performance_monitoring_example():
    """Example of performance monitoring and analysis."""

    settings = Settings()
    obs_manager = ObservabilityManager(settings)
    await obs_manager.initialize()

    try:
        # Create some sample data
        obs = create_observability_decorators(obs_manager)

        @obs.workflow(workflow_type="performance_test")
        async def performance_test_workflow():
            tasks = []

            @obs.agent(agent_type="test_agent")
            async def test_agent(task: str):
                @obs.llm_call(provider="openai", model="gpt-3.5-turbo")
                async def quick_llm_call(prompt: str):
                    await asyncio.sleep(0.05)  # Fast call
                    return f"Quick response to: {prompt}"

                return await quick_llm_call(task)

            # Run multiple agents in parallel
            for i in range(5):
                task = asyncio.create_task(test_agent(f"task_{i}"))
                tasks.append(task)

            return await asyncio.gather(*tasks)

        # Run performance test
        print("Running performance test...")
        await performance_test_workflow()

        # Analyze performance
        print("\n=== Performance Analysis ===")

        # Get real-time metrics
        real_time = await obs_manager.get_real_time_metrics()
        print(f"Real-time metrics: {real_time}")

        # Get workflow metrics
        workflow_metrics = await obs_manager.get_workflow_metrics()
        print("\nWorkflow metrics:")
        print(f"  Total workflows: {workflow_metrics['total_workflows']}")
        print(f"  Success rate: {workflow_metrics['success_rate']:.2%}")
        print(f"  Average duration: {workflow_metrics['average_duration']:.2f}s")

        # Get agent metrics
        agent_metrics = await obs_manager.get_agent_metrics()
        print("\nAgent metrics:")
        print(f"  Total executions: {agent_metrics['total_executions']}")
        print(f"  Success rate: {agent_metrics['success_rate']:.2%}")
        print(f"  Average duration: {agent_metrics['average_duration']:.2f}s")
        print(f"  Total tokens: {agent_metrics['total_tokens']}")
        print(f"  Total cost: ${agent_metrics['total_cost']:.4f}")

        # Get LLM metrics
        llm_metrics = await obs_manager.get_llm_metrics()
        print("\nLLM metrics:")
        print(f"  Total calls: {llm_metrics['total_calls']}")
        print(f"  Total tokens: {llm_metrics['total_tokens']}")
        print(f"  Total cost: ${llm_metrics['total_cost']:.4f}")
        print(f"  Provider stats: {llm_metrics['provider_stats']}")

        # Get daily stats
        daily_stats = await obs_manager.get_daily_stats(days=1)
        print(f"\nDaily stats: {daily_stats}")

    finally:
        await obs_manager.shutdown()


# Main function to run examples
async def main():
    """Run all examples."""

    print("🔍 NEOS Observability Examples")
    print("=" * 50)

    examples = [
        ("Basic Setup", basic_observability_setup),
        ("Decorator Examples", decorator_examples),
        ("Manual Tracking", manual_tracking_example),
        ("Performance Monitoring", performance_monitoring_example),
    ]

    for name, example_func in examples:
        print(f"\n🚀 Running: {name}")
        print("-" * 30)
        try:
            await example_func()
            print(f"✅ {name} completed successfully")
        except Exception as e:
            print(f"❌ {name} failed: {e}")
        print()

    # Framework integration examples (these require actual framework setup)
    print("\n📋 Framework Integration Examples:")
    print("- FastAPI: See fastapi_integration_example()")
    print("- LangGraph: See LangGraphIntegrationExample class")
    print("- CrewAI: See CrewAIIntegrationExample class")

    print("\n🎯 Phoenix UI available at: http://localhost:6006")
    print("📊 Observability examples completed!")


if __name__ == "__main__":
    asyncio.run(main())