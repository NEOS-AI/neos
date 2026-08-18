"""Versioned prompt-file loading without Python format-string parsing."""

import re
from functools import lru_cache
from pathlib import Path

# 프롬프트의 치환 자리. snake_case 식별자만 인정하므로 프롬프트 안의 JSON 예시
# (`{"status": ...}`)나 중괄호 리터럴과 섞이지 않는다 -- 그것들은 따옴표나
# 공백으로 시작한다.
_PLACEHOLDER = re.compile(r"\{[a-z][a-z0-9_]*\}")


_PROMPT_DIR = Path(__file__).parent / "prompts"


@lru_cache(maxsize=None)
def load_prompt(name: str) -> str:
    if not name.replace("_", "").isalnum():
        raise ValueError(f"invalid prompt name: {name!r}")
    return (_PROMPT_DIR / f"{name}.md").read_text(encoding="utf-8")


class UnfilledPlaceholder(ValueError):
    """A prompt reached a model with a placeholder nobody supplied."""


def unfilled_placeholders(prompt: str) -> list[str]:
    """아직 채워지지 않은 치환 자리. 없으면 빈 목록.

    `render` 에서 검사하지 않는 이유는 **부분 렌더가 설계**이기 때문이다 --
    오케스트레이터가 `worker_brief` 를 렌더하면서 `{fetched_evidence}` 를
    일부러 남기고, 워커가 검색을 마친 뒤 그 자리를 채운다. 그래서 검사는
    렌더 시점이 아니라 **모델에 보내는 지점**(`llm.py`)에 있다.
    """
    return sorted(set(_PLACEHOLDER.findall(prompt)))


def render(name: str, **values) -> str:
    """프롬프트를 채워 돌려준다.

    치환은 키마다 `str.replace` 라서, 호출자가 값을 빼먹으면 그 자리는 조용히
    리터럴로 남는다 -- 모델은 `{resolve_threshold} 이상이면` 같은 문장을 받고,
    그래도 응답은 그럴듯하게 오므로 산출물을 봐서는 드러나지 않는다.
    그 사고를 막는 것은 `unfilled_placeholders` 이며 LLM 호출 경계가 쓴다.
    """
    rendered = load_prompt(name)
    for key, value in values.items():
        rendered = rendered.replace("{" + key + "}", str(value))
    return rendered
