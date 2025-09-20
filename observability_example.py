#!/usr/bin/env python3
"""
NEOS Observability Quick Start Example

This script demonstrates how to quickly set up and use Phoenix observability
in your NEOS multi-agent AI system.

Run this script to see observability in action:
    python observability_example.py
"""

import asyncio
import logging
from datetime import datetime

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# NEOS imports
from neos.config.settings import Settings
from neos.observability import (
    ObservabilityManager,
    trace_workflow,
    trace_agent,
    trace_llm_call
)
from neos.observability.integration import (
    setup_observability,
    trace_workflow as global_trace_workflow,
    trace_agent as global_trace_agent
)


async def quick_start_example():
    """Quick start example with basic observability."""

    print("🚀 NEOS Observability Quick Start")
    print("=" * 50)

    # Setup observability
    settings = Settings()
    obs = await setup_observability(settings)

    print(f"📊 Phoenix UI: http://{settings.PHOENIX_HOST}:{settings.PHOENIX_PORT}")
    print("🔄 Running example workflow with observability...")

    # Example workflow using global decorators
    @global_trace_workflow(workflow_type="example_workflow")
    async def example_workflow(query: str):
        """Example workflow with observability."""

        @global_trace_agent(agent_type="search_agent")
        async def search_agent(task: str):
            """Search agent example."""
            print(f"  🔍 Search agent executing: {task}")

            # Simulate LLM call
            await simulate_llm_call("search", "gpt-4", f"Search for: {task}")

            # Simulate work
            await asyncio.sleep(0.2)
            return f"Search results for: {task}"

        @global_trace_agent(agent_type="analysis_agent")
        async def analysis_agent(task: str, search_results: str):
            """Analysis agent example."""
            print(f"  📊 Analysis agent executing: {task}")

            # Simulate LLM call
            await simulate_llm_call("analysis", "gpt-4", f"Analyze: {search_results}")

            # Simulate work
            await asyncio.sleep(0.3)
            return f"Analysis of: {search_results}"

        # Execute workflow steps
        search_results = await search_agent(f"Search information about: {query}")
        analysis = await analysis_agent(f"Analyze query: {query}", search_results)

        return {
            "query": query,
            "search_results": search_results,
            "analysis": analysis,
            "timestamp": datetime.now().isoformat()
        }

    # Simulate LLM call helper
    async def simulate_llm_call(provider: str, model: str, prompt: str):
        """Simulate an LLM API call."""
        if obs and obs.is_enabled:
            await obs.track_llm_call_manually(
                execution_id="current_execution",
                provider=provider,
                model=model,
                prompt=prompt,
                response=f"Response to: {prompt[:50]}...",
                tokens_used=150,
                cost=0.003
            )

        # Simulate API delay
        await asyncio.sleep(0.1)

    try:
        # Run example workflows
        queries = [
            "Latest AI trends 2024",
            "Multi-agent systems benefits",
            "Phoenix observability features"
        ]

        results = []
        for query in queries:
            print(f"\n🔄 Processing: {query}")
            result = await example_workflow(query)
            results.append(result)
            print(f"✅ Completed: {query}")

        print(f"\n🎯 Processed {len(results)} workflows successfully!")

        # Show metrics
        if obs and obs.is_enabled:
            print("\n📈 Observability Metrics:")
            print("-" * 30)

            metrics = await obs.get_metrics()

            # Real-time metrics
            real_time = metrics.get("real_time", {})
            print(f"Active workflows: {real_time.get('active_workflows', 0)}")
            print(f"Active agents: {real_time.get('active_agents', 0)}")
            print(f"Workflows today: {real_time.get('total_workflows_today', 0)}")
            print(f"Agents today: {real_time.get('total_agents_today', 0)}")
            print(f"Success rate: {real_time.get('success_rate', 0):.1%}")
            print(f"Cost today: ${real_time.get('cost_today', 0):.4f}")

            # Workflow metrics
            workflow_metrics = metrics.get("workflows", {})
            if workflow_metrics.get("total_workflows", 0) > 0:
                print(f"\nWorkflow Summary:")
                print(f"  Total: {workflow_metrics['total_workflows']}")
                print(f"  Completed: {workflow_metrics['completed_workflows']}")
                print(f"  Success rate: {workflow_metrics['success_rate']:.1%}")
                print(f"  Avg duration: {workflow_metrics['average_duration']:.2f}s")

            # Agent metrics
            agent_metrics = metrics.get("agents", {})
            if agent_metrics.get("total_executions", 0) > 0:
                print(f"\nAgent Summary:")
                print(f"  Total executions: {agent_metrics['total_executions']}")
                print(f"  Success rate: {agent_metrics['success_rate']:.1%}")
                print(f"  Avg duration: {agent_metrics['average_duration']:.2f}s")
                print(f"  Total tokens: {agent_metrics['total_tokens']}")
                print(f"  Total cost: ${agent_metrics['total_cost']:.4f}")

            # LLM metrics
            llm_metrics = metrics.get("llm", {})
            if llm_metrics.get("total_calls", 0) > 0:
                print(f"\nLLM Summary:")
                print(f"  Total calls: {llm_metrics['total_calls']}")
                print(f"  Total tokens: {llm_metrics['total_tokens']}")
                print(f"  Total cost: ${llm_metrics['total_cost']:.4f}")
                print(f"  Providers: {list(llm_metrics.get('provider_stats', {}).keys())}")

        print(f"\n🎊 Example completed successfully!")
        print(f"📊 View detailed traces at: http://{settings.PHOENIX_HOST}:{settings.PHOENIX_PORT}")

        return results

    except Exception as e:
        print(f"❌ Error in example: {e}")
        raise

    finally:
        # Cleanup
        from neos.observability.integration import shutdown_observability
        await shutdown_observability()
        print("🔄 Observability shutdown completed")


async def advanced_example():
    """Advanced example with manual tracking."""

    print("\n🚀 Advanced Observability Example")
    print("=" * 50)

    # Initialize observability manager directly
    settings = Settings()
    obs_manager = ObservabilityManager(settings)
    await obs_manager.initialize()

    try:
        # Manual workflow tracking
        async with obs_manager.trace_workflow(
            workflow_id="advanced_example",
            workflow_type="manual_tracking",
            metadata={"example": "advanced", "user": "demo"}
        ) as workflow_session_id:

            print(f"📝 Started workflow session: {workflow_session_id}")

            # Manual agent tracking
            async with obs_manager.trace_agent(
                agent_id="manual_agent",
                agent_type="demo_agent",
                task="Demonstrate manual tracking",
                workflow_session_id=workflow_session_id
            ) as agent_execution_id:

                print(f"🤖 Started agent execution: {agent_execution_id}")

                # Manual LLM tracking
                await obs_manager.track_llm_call(
                    execution_id=agent_execution_id,
                    provider="openai",
                    model="gpt-4-turbo",
                    prompt="This is a demo prompt for manual tracking",
                    response="This is a demo response showing manual LLM tracking",
                    tokens_used=200,
                    cost=0.004
                )

                print("💬 Tracked LLM call manually")

                # Simulate agent work
                await asyncio.sleep(0.5)

                print("✅ Agent execution completed")

            print("✅ Workflow completed")

        # Get final metrics
        print("\n📊 Final Metrics:")
        real_time = await obs_manager.get_real_time_metrics()
        print(f"Real-time metrics: {real_time}")

    finally:
        await obs_manager.shutdown()
        print("🔄 Advanced example cleanup completed")


def main():
    """Main function to run examples."""

    print("🌟 NEOS Phoenix Observability Examples")
    print("🔍 This demonstrates Phoenix observability integration")
    print("📊 Monitor your multi-agent AI workflows in real-time")
    print()

    # Check if we should run both examples
    import sys
    run_advanced = "--advanced" in sys.argv

    async def run_examples():
        # Run quick start
        await quick_start_example()

        # Run advanced example if requested
        if run_advanced:
            await advanced_example()

        print("\n🎉 All examples completed!")
        print("💡 Tips:")
        print("  - Run with --advanced flag for additional examples")
        print("  - Check Phoenix UI for detailed trace visualization")
        print("  - Integrate observability into your NEOS workflows")
        print("  - Monitor performance and optimize based on metrics")

    # Run the examples
    asyncio.run(run_examples())


if __name__ == "__main__":
    main()