from neos.agenthub.visualbrowsing_agent.visualbrowsing_agent import (
    VisualBrowsingAgent,
)
from neos.controller.agent import Agent

Agent.register('VisualBrowsingAgent', VisualBrowsingAgent)
