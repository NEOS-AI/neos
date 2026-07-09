"""Versioned prompt-file loading without Python format-string parsing."""

from functools import lru_cache
from pathlib import Path


_PROMPT_DIR = Path(__file__).parent / "prompts"


@lru_cache(maxsize=None)
def load_prompt(name: str) -> str:
    if not name.replace("_", "").isalnum():
        raise ValueError(f"invalid prompt name: {name!r}")
    return (_PROMPT_DIR / f"{name}.md").read_text(encoding="utf-8")


def render(name: str, **values) -> str:
    rendered = load_prompt(name)
    for key, value in values.items():
        rendered = rendered.replace("{" + key + "}", str(value))
    return rendered
