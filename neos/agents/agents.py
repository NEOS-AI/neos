from langgraph.prebuilt import create_react_agent

from neos.config.agents import AGENT_LLM_MAP
from neos.llms.llm import get_llm_by_type
from neos.prompts import apply_prompt_template


# Create agents using configured LLM types
def create_agent(agent_name: str, agent_type: str, tools: list, prompt_template: str):
    """Factory function to create agents with consistent configuration."""
    if agent_type not in AGENT_LLM_MAP:
        llm_type = "basic"
    else:
        llm_type = AGENT_LLM_MAP[agent_type]

    return create_react_agent(
        name=agent_name,
        model=get_llm_by_type(llm_type),
        tools=tools,
        prompt=lambda state: apply_prompt_template(prompt_template, state),
    )
