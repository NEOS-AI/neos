from neos.security.analyzer import SecurityAnalyzer
from neos.security.invariant.analyzer import InvariantAnalyzer
from neos.security.llm.analyzer import LLMRiskAnalyzer

SecurityAnalyzers: dict[str, type[SecurityAnalyzer]] = {
    'invariant': InvariantAnalyzer,
    'llm': LLMRiskAnalyzer,
}
