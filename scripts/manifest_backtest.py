"""표본 아티팩트만으로 런 구성을 복원할 수 있는지 칸별로 판정한다 (H1 관문).

라이브 표본을 한 건도 쓰지 않는다 -- 디스크에 이미 있는 아티팩트만 읽는다.
로드맵 §13.3 F1 과 같은 값싼 백테스트다.

관문의 산출물은 "통과/실패" 가 아니라 **칸별 복원 가능 여부 표**다.
과거 아티팩트에 프롬프트 해시도 스킬 목록도 components 도 없다는 것은
예상된 결과이고, 그 사실 자체가 H1 의 근거다.

MANIFEST_FIELDS 는 이 스크립트 안에서 직접 정의한다 (neos/workflow/deep_analysis/
manifest.py 에서 임포트하지 않는다). 이 도구의 목적은 그 모듈이 존재하기 전에 쓰인
옛 아티팩트를 읽는 것이므로, 런타임 코드에 의존하면 옛 모양을 못 읽는다.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

MANIFEST_FIELDS = (
    "profile",
    "models",
    "budget",
    "prompts",
    "skills",
    "components",
    "config",
)

# 옛 지문에서 새 매니페스트의 칸을 (부분적으로라도) 복원할 수 있는 키.
_LEGACY_SOURCES = {
    "models": ("resolved_models", "models"),
    "budget": ("global_token_cap",),
    "config": ("max_depth", "quote_match_threshold"),
}


def recoverable_fields(artifact_manifest: dict) -> dict[str, bool]:
    fingerprint = artifact_manifest.get("config_fingerprint") or {}
    runs = fingerprint.get("runs")
    if isinstance(runs, dict) and runs:
        sample = next(iter(runs.values()))
        return {field: field in sample for field in MANIFEST_FIELDS}
    return {
        field: any(key in fingerprint for key in _LEGACY_SOURCES.get(field, ()))
        for field in MANIFEST_FIELDS
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact_dirs", nargs="+", type=Path)
    args = parser.parse_args()

    print("| 표본 | " + " | ".join(MANIFEST_FIELDS) + " |")
    print("|---" * (len(MANIFEST_FIELDS) + 1) + "|")
    for directory in args.artifact_dirs:
        data = json.loads((directory / "manifest.json").read_text())
        recovered = recoverable_fields(data)
        cells = " | ".join(
            "✅" if recovered[field] else "❌" for field in MANIFEST_FIELDS
        )
        print(f"| {directory.name} | {cells} |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
