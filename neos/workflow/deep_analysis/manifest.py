"""런의 유효 구성을 이벤트 하나로 못 박는다 (트랙 H의 H1).

`build_manifest` 는 **계산하지 않는다.** `settings` 를 import 하지 않고,
floor 를 유도하지 않고, 프로파일로 분기하지 않는다. 호출자가 이미 가진 값을
받아 적기만 한다.

그 규율이 이 모듈의 전부다. 기존 지문(`scripts/deep_analysis_funnel_sample.py`)
은 같은 값을 다시 계산했고, 그래서 표본 #20 의 아티팩트가 6런 중 5런에
대해 틀린 캡(300000)을 적었다. 불변식을 검사하는 대신 **어긋난 상태를
표현할 수 없게** 만든다.
"""

from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path
from typing import Any

from neos.config.model_routing import ModelResolution

MANIFEST_KIND = "run_manifest"
MANIFEST_VERSION = 1

# 런 경로가 쓰는 프롬프트만. `prompts/` 에는 9개가 있으나
# `diagnose_bottleneck` 은 F1 진단자 전용이라 런의 구성이 아니다 --
# 넣으면 그 파일을 고칠 때마다 동일한 두 런이 달라 보인다.
RUN_PROMPTS: tuple[str, ...] = (
    "claim_entailment",   # worker.py
    "decompose",          # orchestrator.py
    "final_compose",      # synthesizer.py
    "judge",              # graders/agentic.py
    "node_summary",       # synthesizer.py
    "report_judge",       # graders/report.py
    "subq_review",        # orchestrator.py
    "worker_brief",       # orchestrator.py
)

_PROMPT_DIR = Path(__file__).parent / "prompts"
_PACKAGE_PREFIX = "neos.workflow.deep_analysis."


@lru_cache(maxsize=1)
def prompt_hashes() -> dict[str, str]:
    """런 경로 프롬프트 8개의 내용 해시.

    캐시하는 이유는 `load_prompt` 와 같다 -- 파일은 프로세스 수명 동안
    바뀌지 않는다.
    """
    digests = {}
    for name in RUN_PROMPTS:
        raw = (_PROMPT_DIR / f"{name}.md").read_bytes()
        digests[name] = "sha256:" + hashlib.sha256(raw).hexdigest()
    return digests


def component_id(obj: object | None) -> str | None:
    """이 런이 조립한 부품의 식별자.

    설계 §15.3 은 매니페스트 항목으로 "그래프 토폴로지 해시" 를 적었으나
    심층분석 런은 LangGraph 그래프를 타지 않는다. 이 하네스에서 "무엇이
    조립됐나" 에 해당하는 것은 부품 배선이다.

    소스 해시는 넣지 않는다 -- 클래스 이름이 같고 내용이 바뀐 경우는
    아티팩트의 `git` 항(commit + dirty)이 답한다.
    """
    if obj is None:
        return None
    cls = type(obj)
    module = cls.__module__
    if module.startswith(_PACKAGE_PREFIX):
        module = module[len(_PACKAGE_PREFIX):]
    return f"{module}:{cls.__qualname__}"


def build_manifest(
    *,
    profile: str,
    models: dict[str, ModelResolution],
    budget: dict[str, int | float],
    prompts: dict[str, str],
    skills: list[dict[str, str]] | None,
    components: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    """호출자가 이미 가진 값을 매니페스트 모양으로 정렬한다. 계산 없음."""
    resolved = {
        name: {
            "role": resolution.role,
            "model": resolution.model,
            "source": resolution.source.value,
        }
        for name, resolution in sorted(models.items())
    }
    # E3 를 자백한다. 관측이지 강제가 아니다 -- 해소는 로드맵 §8 W4 다.
    judge = models.get("judge")
    scout = models.get("scout")
    resolved["judge_equals_scout"] = (
        judge is not None and scout is not None and judge.model == scout.model
    )
    return {
        "manifest_version": MANIFEST_VERSION,
        "profile": profile,
        "models": resolved,
        "budget": dict(budget),
        "prompts": dict(prompts),
        "skills": None if skills is None else list(skills),
        "components": dict(components),
        "config": dict(config),
    }
