"""Deterministic candidate selection for worker discovery tools.

셀렉터는 '무엇을 제공할지'만 정한다(결정론적). '무엇을 쓸지'는 워커의 LLM이
tool-calling으로 고른다 — 도구 선택은 무결성 레버가 아니라 품질 레버이므로
DeterministicGrader(출처 무관)가 그 자유도를 안전하게 만든다.
"""

from __future__ import annotations

from neos.config.settings import settings

from .models import Effort


class SkillSelector:
    def __init__(
        self,
        registry=None,
        *,
        allowlist: list[str] | None = None,
        cap: int | None = None,
    ) -> None:
        config = settings.config.deep_analysis
        self.registry = registry
        self.allowlist = (
            allowlist if allowlist is not None else list(config.discovery_skills)
        )
        self.cap = cap if cap is not None else config.max_discovery_skills

    def candidates(self, effort: Effort) -> list:
        if effort is not Effort.DIG or self.registry is None:
            return []

        selected = []
        for name in self.allowlist:
            if len(selected) >= self.cap:
                break
            skill = self.registry.get_skill(name)
            if skill is not None:
                selected.append(skill)
        return selected
