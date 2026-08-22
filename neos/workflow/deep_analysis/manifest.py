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
from types import MappingProxyType
from typing import Any, Mapping

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
def prompt_hashes() -> Mapping[str, str]:
    """런 경로 프롬프트 8개의 내용 해시.

    캐시하는 이유는 `load_prompt` 와 같다 -- 파일은 프로세스 수명 동안
    바뀌지 않는다. `lru_cache` 는 매 호출에 같은 dict 객체를 돌려주므로,
    가변 dict 를 그대로 반환하면 한 호출자의 변형이 프로세스의 나머지
    전부를 감지 불가능하게 오염시킨다. `MappingProxyType` 으로 감싸서
    반환값을 읽기 전용으로 만든다.
    """
    digests = {}
    for name in RUN_PROMPTS:
        raw = (_PROMPT_DIR / f"{name}.md").read_bytes()
        digests[name] = "sha256:" + hashlib.sha256(raw).hexdigest()
    return MappingProxyType(digests)


def component_id_for_class(cls: type) -> str:
    """`component_id` 와 같은 식별자를, 인스턴스 없이 클래스만으로 낸다.

    `build_orchestrator` 는 `synthesizer`/`citation_renderer` kwargs 를 항상
    `None` 으로 넘긴다 -- 그런데 `Orchestrator.__init__` 은 그 경우 기본으로
    `Synthesizer`/`CitationRenderer` 를 **무조건** 만든다. 즉 인스턴스가
    없다고 해서 부품이 안 조립된 것이 아니라, `build_orchestrator` 가 그
    인스턴스를 쥐고 있지 않을 뿐이다. 무엇이 실제로 도는지는 클래스로 이미
    알 수 있으므로, 인스턴스를 만들지 않고도 같은 식별자를 낸다.
    """
    module = cls.__module__
    if module.startswith(_PACKAGE_PREFIX):
        module = module[len(_PACKAGE_PREFIX):]
    return f"{module}:{cls.__qualname__}"


def component_id(obj: object | None) -> str | None:
    """이 런이 조립한 부품의 식별자.

    설계 §15.3 은 매니페스트 항목으로 "그래프 토폴로지 해시" 를 적었으나
    심층분석 런은 LangGraph 그래프를 타지 않는다. 이 하네스에서 "무엇이
    조립됐나" 에 해당하는 것은 부품 배선이다.

    소스 해시는 넣지 않는다 -- 클래스 이름이 같고 내용이 바뀐 경우는
    아티팩트의 `git` 항(commit + dirty)이 답한다.

    `obj` 가 `None` 이면 "배선 안 됨" 이다 -- 실제로 조립되는 부품을 클래스만
    아는 상태로 기록해야 한다면 `component_id_for_class` 를 대신 쓴다.
    """
    if obj is None:
        return None
    return component_id_for_class(type(obj))


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
    # 최상위 키다: `models` 의 다른 모든 값은 resolution dict 라서, 같은
    # 키 아래 bool 을 두면 `models.items()` 를 순회하는 소비자가 전부
    # 깨진다. 지금이 이 결정을 고칠 수 있는 유일한 무료 순간이다 --
    # `manifest_version: 1` 이 표본에 한 번 찍히고 나면 같은 이동에
    # 버전 상승이 든다.
    judge = models.get("judge")
    scout = models.get("scout")
    judge_equals_scout = (
        judge is not None and scout is not None and judge.model == scout.model
    )
    return {
        "manifest_version": MANIFEST_VERSION,
        "profile": profile,
        "models": resolved,
        "judge_equals_scout": judge_equals_scout,
        "budget": dict(budget),
        "prompts": dict(prompts),
        "skills": None if skills is None else list(skills),
        "components": dict(components),
        "config": dict(config),
    }
