from pathlib import Path
from typing import Any

from neos.config.loader import load_yaml_file
from neos.config.schema import AppConfig

CONFIG_DIR = Path("config")
PROFILE_FILES = [
    CONFIG_DIR / "neos.default.yaml",
    CONFIG_DIR / "neos.development.yaml",
    CONFIG_DIR / "neos.staging.yaml",
    CONFIG_DIR / "neos.production.yaml",
    CONFIG_DIR / "neos.example.yaml",
]
SECRET_KEY_FRAGMENTS = ("api_key", "secret_key", "password", "access_key")


def is_secret_like_path(key_path: tuple[str, ...]) -> bool:
    joined_path = ".".join(key_path).lower()
    leaf = key_path[-1].lower() if key_path else ""
    if any(fragment in joined_path for fragment in SECRET_KEY_FRAGMENTS):
        return True
    return leaf == "token" or leaf.endswith("_token")


def walk_yaml(value: Any, path: tuple[str, ...] = ()):
    if isinstance(value, dict):
        for key, child in value.items():
            yield from walk_yaml(child, (*path, str(key)))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from walk_yaml(child, (*path, str(index)))
    else:
        yield path, value


def test_committed_config_profiles_exist_and_validate():
    for path in PROFILE_FILES:
        assert path.exists(), f"missing config profile: {path}"
        config = AppConfig.model_validate(load_yaml_file(path))
        assert config.model_routing.anthropic.everyday == "claude-sonnet-5"
        assert config.model_routing.openai.powerful == "gpt-5.6-sol"
        assert config.coding_model.model is None
        assert config.recursive_agent.planner_model is None
        assert config.deep_analysis.models.scout is None
        assert config.deep_analysis.models.dig is None
        assert config.deep_analysis.models.synth is None
        # judge 만 예외다 (E3, 2026-08-29). `None` 이면 `everyday` 로 해석돼
        # scout 과 같은 모델이 되고, 그것이 설계 §6.5 가 금지한 자기 승인
        # 편향이다. 배포 기본값은 `neos.default.yaml` 이 정하고 나머지
        # 프로파일은 **건드리지 않아야** 한다 -- 로더가 default 를 계층으로
        # 병합하므로(loader.py:388) 그래야 모든 환경이 같은 판정자를 쓴다.
        if path.name == "neos.default.yaml":
            assert config.deep_analysis.models.judge == "claude-opus-4-8"
        else:
            assert config.deep_analysis.models.judge is None, (
                f"{path.name} 이 judge 를 덮어썼다 -- 분리가 환경마다 "
                "달라지면 표본 판정이 어느 판정자의 것인지 알 수 없다"
            )


def test_committed_config_profiles_do_not_contain_secrets():
    for path in PROFILE_FILES:
        data = load_yaml_file(path)
        for key_path, value in walk_yaml(data):
            joined_path = ".".join(key_path).lower()
            if path.name != "neos.example.yaml":
                assert not is_secret_like_path(key_path), (
                    f"{path} contains secret-like key {joined_path}"
                )
            if isinstance(value, str):
                assert not ("://" in value and "@" in value), (
                    f"{path} contains credential-bearing URL at {joined_path}"
                )
