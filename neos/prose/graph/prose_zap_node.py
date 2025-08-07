import logging

from langchain.schema import HumanMessage, SystemMessage

from neos.config.agents import AGENT_LLM_MAP
from neos.llms.llm import get_llm_by_type
from neos.prompts.template import get_prompt_template
from neos.prose.graph.state import ProseState

logger = logging.getLogger(__name__)


def prose_zap_node(state: ProseState):
    logger.info("Generating prose zap content...")
    model = get_llm_by_type(AGENT_LLM_MAP["prose_writer"])
    prose_content = model.invoke(
        [
            SystemMessage(content=get_prompt_template("prose/prose_zap")),
            HumanMessage(
                content=f"For this text: {state['content']}.\nYou have to respect the command: {state['command']}"
            ),
        ],
    )
    logger.info(f"prose_content: {prose_content}")
    return {"output": prose_content.content}
