"""
모델 설정 로더

YAML 파일에서 VLM, LLM, Embedding 모델 설정을 로드합니다.
dotenv를 사용하지 않고 별도의 설정 파일로 모델 ID를 관리합니다.
"""
import os
import yaml
from typing import Dict, Any, Optional
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


class ModelConfig:
    """
    모델 설정 싱글톤 클래스

    models.yaml 파일에서 모델 설정을 로드하고 캐싱합니다.
    """
    _instance: Optional['ModelConfig'] = None
    _config: Optional[Dict[str, Any]] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self._config is None:
            self._load_config()

    def _load_config(self):
        """YAML 설정 파일 로드"""
        # 설정 파일 경로
        config_path = Path(__file__).parent / "models.yaml"

        # 환경 변수로 오버라이드 가능
        custom_config_path = os.getenv("NEOS_MODEL_CONFIG_PATH")
        if custom_config_path:
            config_path = Path(custom_config_path)

        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                self._config = yaml.safe_load(f)
            logger.info(f"Model configuration loaded from: {config_path}")
        except FileNotFoundError:
            logger.error(f"Model configuration file not found: {config_path}")
            # 기본 설정 사용
            self._config = self._get_default_config()
        except yaml.YAMLError as e:
            logger.error(f"Error parsing YAML configuration: {e}")
            self._config = self._get_default_config()

    def _get_default_config(self) -> Dict[str, Any]:
        """기본 설정 (fallback)"""
        return {
            'vision_models': {
                'gpt4o': {'model_id': 'gpt-4o', 'provider': 'openai'},
                'claude': {'model_id': 'claude-sonnet-4-5-20250929', 'provider': 'anthropic'},
                'gemini': {'model_id': 'gemini-1.5-pro-latest', 'provider': 'google'},
            },
            'defaults': {
                'vision': 'gpt4o',
                'llm': 'claude_sonnet',
                'embedding': 'openai_small',
            }
        }

    def get_vision_model(self, model_name: str) -> Dict[str, Any]:
        """
        Vision 모델 설정 조회

        Args:
            model_name: 모델 이름 (예: 'gpt4o', 'claude', 'gemini')

        Returns:
            모델 설정 딕셔너리

        Raises:
            ValueError: 모델이 설정에 없는 경우
        """
        if not self._config:
            self._load_config()

        vision_models = self._config.get('vision_models', {})
        if model_name not in vision_models:
            available = ', '.join(vision_models.keys())
            raise ValueError(
                f"Vision model '{model_name}' not found in configuration. "
                f"Available models: {available}"
            )

        return vision_models[model_name]

    def get_vision_model_id(self, model_name: str) -> str:
        """Vision 모델 ID만 조회"""
        return self.get_vision_model(model_name)['model_id']

    def get_llm_model(self, model_name: str) -> Dict[str, Any]:
        """LLM 모델 설정 조회"""
        if not self._config:
            self._load_config()

        llm_models = self._config.get('llm_models', {})
        if model_name not in llm_models:
            available = ', '.join(llm_models.keys())
            raise ValueError(
                f"LLM model '{model_name}' not found in configuration. "
                f"Available models: {available}"
            )

        return llm_models[model_name]

    def get_llm_model_id(self, model_name: str) -> str:
        """LLM 모델 ID만 조회"""
        return self.get_llm_model(model_name)['model_id']

    def get_embedding_model(self, model_name: str) -> Dict[str, Any]:
        """Embedding 모델 설정 조회"""
        if not self._config:
            self._load_config()

        embedding_models = self._config.get('embedding_models', {})
        if model_name not in embedding_models:
            available = ', '.join(embedding_models.keys())
            raise ValueError(
                f"Embedding model '{model_name}' not found in configuration. "
                f"Available models: {available}"
            )

        return embedding_models[model_name]

    def get_embedding_model_id(self, model_name: str) -> str:
        """Embedding 모델 ID만 조회"""
        return self.get_embedding_model(model_name)['model_id']

    def get_default_vision_model(self) -> str:
        """기본 Vision 모델 이름"""
        return self._config.get('defaults', {}).get('vision', 'gpt4o')

    def get_default_llm_model(self) -> str:
        """기본 LLM 모델 이름"""
        return self._config.get('defaults', {}).get('llm', 'claude_sonnet')

    def get_default_embedding_model(self) -> str:
        """기본 Embedding 모델 이름"""
        return self._config.get('defaults', {}).get('embedding', 'openai_small')

    def list_vision_models(self) -> list[str]:
        """사용 가능한 Vision 모델 목록"""
        return list(self._config.get('vision_models', {}).keys())

    def list_llm_models(self) -> list[str]:
        """사용 가능한 LLM 모델 목록"""
        return list(self._config.get('llm_models', {}).keys())

    def list_embedding_models(self) -> list[str]:
        """사용 가능한 Embedding 모델 목록"""
        return list(self._config.get('embedding_models', {}).keys())

    def reload(self):
        """설정 파일 재로드 (개발 환경용)"""
        self._config = None
        self._load_config()
        logger.info("Model configuration reloaded")


# 싱글톤 인스턴스
model_config = ModelConfig()


# 편의 함수들
def get_vision_model_id(model_name: str = None) -> str:
    """
    Vision 모델 ID 조회

    Args:
        model_name: 모델 이름. None이면 기본 모델 사용

    Returns:
        모델 ID (예: "gpt-4o")
    """
    if model_name is None:
        model_name = model_config.get_default_vision_model()
    return model_config.get_vision_model_id(model_name)


def get_llm_model_id(model_name: str = None) -> str:
    """
    LLM 모델 ID 조회

    Args:
        model_name: 모델 이름. None이면 기본 모델 사용

    Returns:
        모델 ID
    """
    if model_name is None:
        model_name = model_config.get_default_llm_model()
    return model_config.get_llm_model_id(model_name)


def get_embedding_model_id(model_name: str = None) -> str:
    """
    Embedding 모델 ID 조회

    Args:
        model_name: 모델 이름. None이면 기본 모델 사용

    Returns:
        모델 ID
    """
    if model_name is None:
        model_name = model_config.get_default_embedding_model()
    return model_config.get_embedding_model_id(model_name)
