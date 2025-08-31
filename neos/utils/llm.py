import warnings

import httpx

with warnings.catch_warnings():
    warnings.simplefilter('ignore')
    import litellm

from neos.core.config import LLMConfig, OpenHandsConfig
from neos.core.logger import openhands_logger as logger
from neos.llm import bedrock


def get_supported_llm_models(config: OpenHandsConfig) -> list[str]:
    """Get all models supported by LiteLLM.

    This function combines models from litellm and Bedrock, removing any
    error-prone Bedrock models.

    Returns:
        list[str]: A sorted list of unique model names.
    """
    litellm_model_list = litellm.model_list + list(litellm.model_cost.keys())
    litellm_model_list_without_bedrock = bedrock.remove_error_modelId(
        litellm_model_list
    )
    # TODO: for bedrock, this is using the default config
    llm_config: LLMConfig = config.get_llm_config()
    bedrock_model_list = []
    if (
        llm_config.aws_region_name
        and llm_config.aws_access_key_id
        and llm_config.aws_secret_access_key
    ):
        bedrock_model_list = bedrock.list_foundation_models(
            llm_config.aws_region_name,
            llm_config.aws_access_key_id.get_secret_value(),
            llm_config.aws_secret_access_key.get_secret_value(),
        )
    model_list = litellm_model_list_without_bedrock + bedrock_model_list
    for llm_config in config.llms.values():
        ollama_base_url = llm_config.ollama_base_url
        if llm_config.model.startswith('ollama'):
            if not ollama_base_url:
                ollama_base_url = llm_config.base_url
        if ollama_base_url:
            ollama_url = ollama_base_url.strip('/') + '/api/tags'
            try:
                ollama_models_list = httpx.get(ollama_url, timeout=3).json()['models']  # noqa: ASYNC100
                for model in ollama_models_list:
                    model_list.append('ollama/' + model['name'])
                break
            except httpx.HTTPError as e:
                logger.error(f'Error getting OLLAMA models: {e}')

    # Add NEOS provider models
    neos_models = [
        'neos/claude-sonnet-4-20250514',
        'neos/gpt-5-2025-08-07',
        'neos/gpt-5-mini-2025-08-07',
        'neos/claude-opus-4-20250514',
        'neos/gemini-2.5-pro',
        'neos/o3',
        'neos/o4-mini',
        'neos/devstral-small-2505',
        'neos/devstral-small-2507',
        'neos/devstral-medium-2507',
        'neos/kimi-k2-0711-preview',
        'neos/qwen3-coder-480b',
    ]
    model_list = neos_models + model_list

    return list(sorted(set(model_list)))
